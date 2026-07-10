"""Two-pass counting orchestration (stage 3, plan_A4_stage3_2026-07-10).

Pass 2 = ALL semantics, minutes from cache, re-runnable:
  1. corpus discovery — the bank builder runs over the camera's pass-1
     raw-track dump, giving per-cell volumes observed over the SAME window
     that gets counted (scale-1 merge expecteds; A4a retired extrapolation)
     plus the missing-movement QA. **The corpus bank does NOT replace the
     camera's APPLIED bank for attribution**: the 2026-07-09 bank audit
     measured that swap as catastrophic (cam5 drawn-direct arm: 38.9% MAE,
     +161 phantom NB-rights; cam2 §2c: −18.5%) — attribution stays on the
     operator-applied bank; the corpus result feeds expecteds + QA only.
  2. replay-classify through the production chain (A2 parity: exact);
  3. volume-gated turn-fragment merge, corpus expecteds (A4a: cam5 beat its
     live baseline with exactly this split);
  4. QA: rebuild_flags with the S5 merge-borderline rows (B4/A4b).

Everything lands in a WORKING DB first; `apply=True` swaps the camera's
events + bank into project.db atomically with a backup — the established
apply pattern. Gated by config.TWO_PASS_ENABLED (default OFF): the legacy
live pipeline path is untouched until the stage-3 gate + operator dry-run.

GT-free throughout (prime directive): raw video + operator calibration only.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

_CELL_RE = re.compile(r"L(\d+)->L(\d+)")

from backend.database import get_connection, get_db_path
from backend.services.detection_cache import compute_video_content_hash, parquet_path
from backend.services.flag_feeders import rebuild_flags
from backend.services.cardinals import bound_approach
from backend.services.pass2_replay import load_dump, replay_camera, tracks_dir
from backend.services.turn_merge import merge_replay_turns, s5_flags

logger = logging.getLogger(__name__)


def _dump_tracks_pointlists(rows: np.ndarray) -> list[list[tuple]]:
    """Group dump rows into per-track point lists (build_bank input shape)."""
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append((float(r[2]), float(r[3])))
    return list(tracks.values())


def run_pass1(project_id: str, camera_id: int, *, variant: str,
              start_frame: int, end_frame: int, backend: str | None = None,
              resume: bool = True, progress=None) -> dict:
    """Pass 1: raw-track dump for one camera window from its detection cache —
    the productized core of scripts/dump_raw_tracks.py (the CLI wraps this).
    Semantics-free: no legs, channels, or classification; live-parity tracking
    input (per-camera pre-track NMS -> bbox buffer -> tracker, full frame
    schedule incl. empty updates — the A2 tier-1 lessons).

    backend: None -> the camera's calib_pass1_backend (default bytetrack).
    'botsort+reid' loads the pre-built ReID sidecar (build_reid_cache);
    missing sidecar is an actionable error, not an implicit hours-long build.
    resume: continue from the count.txt high-water mark when the existing
    dump's recipe matches (recipe mismatch = hard error)."""
    import numpy as _np
    from numpy.lib.format import open_memmap

    from backend.config import PRE_TRACK_NMS_IOU
    from backend.database import get_camera_calibration_params
    from backend.services.detection_cache import DetectionCacheReader
    from backend.services.pipeline import _class_agnostic_nms
    from backend.services.tracker import create_tracker_backend

    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    video = conn.execute(
        "SELECT * FROM videos WHERE camera_id = ? ORDER BY sort_order LIMIT 1",
        (camera_id,)).fetchone()
    conn.close()
    if video is None:
        raise ValueError(f"camera {camera_id}: no video row")
    fps = float(video["fps"])
    chash, _ = compute_video_content_hash(
        video["path"], file_size_bytes=video["file_size_bytes"],
        total_frames=video["total_frames"])
    pq = parquet_path(project_id, camera_id, chash, variant)
    if not pq.exists():
        raise FileNotFoundError(
            f"no detection cache at {pq} — run a processing pass first "
            f"(the pipeline writes the cache as it detects)")
    out = tracks_dir(pq)

    calib = get_camera_calibration_params(project_id, camera_id)
    recipe = (backend or calib.get("pass1_backend") or "bytetrack").lower()
    with_reid = recipe.endswith("+reid")
    tracker_backend = recipe.replace("+reid", "")
    activation = float(calib.get("tracker_activation_threshold") or 0.25)
    match = float(calib.get("tracker_match_threshold") or 0.8)
    buf = float(calib.get("bbox_buffer_scale") or 1.0)
    nms_iou = calib.get("pre_track_nms_iou")
    if nms_iou is None:
        nms_iou = PRE_TRACK_NMS_IOU
    ntt = calib.get("new_track_thresh")
    tracker_kwargs: dict = {}
    if ntt is not None and tracker_backend == "botsort":
        tracker_kwargs["new_track_thresh"] = float(ntt)
    if with_reid:
        side = pq.with_name(pq.stem + ".reid")
        if not side.exists():
            side_npz = pq.with_name(pq.stem + ".reid.npz")
            if side_npz.exists():
                side = side_npz
            else:
                raise FileNotFoundError(
                    f"recipe '{recipe}' needs the ReID sidecar at {side} — "
                    f"build it first: py scripts/build_reid_cache.py "
                    f"--camera {camera_id} --variant {variant}")
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
        from reid_embedding_cache import ReidEmbeddingCache
        tracker_kwargs["with_reid"] = True
        tracker_kwargs["reid_embeddings"] = ReidEmbeddingCache(side)
    be = create_tracker_backend(
        tracker_backend, track_activation_threshold=activation,
        minimum_matching_threshold=match, frame_rate=int(fps), **tracker_kwargs)

    meta = {
        "format": 2,
        "cols": ["track_id", "frame", "cx", "cy", "bw", "bh", "conf", "class_id"],
        "backend": recipe, "camera": camera_id, "variant": variant,
        "frames": [start_frame, end_frame],
        "nms_iou": nms_iou, "new_track_thresh": ntt,
        "activation": activation, "match": match, "bbox_buffer": buf,
    }
    reader = DetectionCacheReader(pq)
    n_dets = sum(len(d) for f, d in reader.iter_frames()
                 if start_frame <= f < end_frame)
    cap_rows = int(n_dets * 1.2) + 1000

    out.mkdir(parents=True, exist_ok=True)
    w = 0
    resume_from = start_frame
    if resume and (out / "rows.npy").exists() and (out / "count.txt").exists():
        old_meta = json.loads((out / "meta.json").read_text())
        mismatches = [k for k in ("format", "frames", "backend", "nms_iou",
                                  "activation", "match", "bbox_buffer")
                      if old_meta.get(k) != meta.get(k)]
        if mismatches:
            raise ValueError(
                f"pass-1 resume: existing dump differs on {mismatches} — "
                f"delete {out} to start over")
        mm = open_memmap(out / "rows.npy", mode="r+")
        w0 = int((out / "count.txt").read_text())
        if w0 > 0:
            f_last = int(mm[w0 - 1, 1])
            w = w0
            while w > 0 and int(mm[w - 1, 1]) == f_last:
                w -= 1
            resume_from = f_last
    else:
        mm = open_memmap(out / "rows.npy", mode="w+", dtype=_np.float32,
                         shape=(cap_rows, 8))
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    reader_iter = DetectionCacheReader(pq).iter_frames()
    nxt = next(reader_iter, None)
    done = 0
    for fidx in range(resume_from, end_frame):
        while nxt is not None and nxt[0] < fidx:
            nxt = next(reader_iter, None)
        if nxt is not None and nxt[0] == fidx:
            dets = nxt[1]
            nxt = next(reader_iter, None)
        else:
            dets = []
        if nms_iou is not None and len(dets) > 1:
            dets = _class_agnostic_nms(dets, float(nms_iou))
        if buf != 1.0 and dets:
            inflated = []
            for d in dets:
                x1, y1, x2, y2 = d["bbox"]
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                hw, hh = (x2 - x1) * buf / 2, (y2 - y1) * buf / 2
                d = dict(d); d["bbox"] = [cx - hw, cy - hh, cx + hw, cy + hh]
                inflated.append(d)
            dets = inflated
        for t in be.update(dets, fidx):
            if w >= mm.shape[0]:
                raise RuntimeError(f"pass-1 row capacity {mm.shape[0]} exceeded")
            cx, cy = t["center"]
            mm[w] = (float(t["track_id"]), float(fidx), float(cx), float(cy),
                     float(t.get("bbox_width", 0.0)), float(t.get("bbox_height", 0.0)),
                     float(t.get("confidence", 0.0)), float(t.get("class_id", -1)))
            w += 1
        done += 1
        if done % 5000 == 0:
            mm.flush()
            (out / "count.txt").write_text(str(w))
            if progress:
                progress(done, end_frame - resume_from, w)
    mm.flush(); del mm
    (out / "count.txt").write_text(str(w))
    return {"camera_id": camera_id, "variant": variant, "recipe": recipe,
            "rows": w, "frames": [start_frame, end_frame], "tracks_dir": str(out)}


def _apply_window_events(proj_db: Path, out_db: Path, camera_id: int,
                         t_lo: float, t_hi: float) -> None:
    """Swap ONE trim window's events into project.db, scoped by the event's
    crossing timestamp (the two-pass binning convention) — applying a study
    day's three windows must not wipe each other. The applied bank is never
    touched here."""
    c = sqlite3.connect(proj_db)
    cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)")
            if r[1] != "event_id"]
    collist = ",".join(cols)
    with c:
        c.execute("ATTACH DATABASE ? AS w", (str(out_db),))
        c.execute("DELETE FROM vehicle_events WHERE camera_id = ? AND "
                  "timestamp_video >= ? AND timestamp_video < ?",
                  (camera_id, t_lo, t_hi))
        c.execute(f"INSERT INTO vehicle_events ({collist}) "
                  f"SELECT {collist} FROM w.vehicle_events WHERE camera_id = ? "
                  f"AND timestamp_video >= ? AND timestamp_video < ?",
                  (camera_id, t_lo, t_hi))
    c.execute("DETACH DATABASE w")
    c.close()


def run_pass2(project_id: str, camera_id: int, *, variant: str,
              workdir: str | Path, apply: bool = False) -> dict:
    """Pass 2 for one camera from its pass-1 dump. Returns stats incl. the
    working DB path; apply=True additionally swaps events+bank into project.db
    (backup first) and rebuilds the intersection's flag queue with S5 rows."""
    # scripts/ is on the path for build_bank_gtfree (Phase-2 productized entry
    # point that still lives there; the CLI and this service share it).
    scripts = str(Path(__file__).resolve().parent.parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from build_bank_gtfree import build_gtfree_bank as build_bank

    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    video = conn.execute(
        "SELECT * FROM videos WHERE camera_id = ? ORDER BY sort_order LIMIT 1",
        (camera_id,)).fetchone()
    cam_row = conn.execute(
        "SELECT intersection_id FROM cameras WHERE camera_id = ?",
        (camera_id,)).fetchone()
    conn.close()
    if video is None or cam_row is None:
        raise ValueError(f"camera {camera_id}: missing video/camera row")
    intersection_id = cam_row["intersection_id"]
    fps = float(video["fps"])

    chash, _ = compute_video_content_hash(
        video["path"], file_size_bytes=video["file_size_bytes"],
        total_frames=video["total_frames"])
    tdir = tracks_dir(parquet_path(project_id, camera_id, chash, variant))
    if not (tdir / "count.txt").exists():
        raise FileNotFoundError(
            f"pass-1 dump missing/incomplete at {tdir} — run pass 1 first")
    meta = json.loads((tdir / "meta.json").read_text())
    f_lo, f_hi = meta["frames"]
    window_seconds = (f_hi - f_lo) / fps
    rows = load_dump(tdir)

    # --- 1. corpus bank: discovery over the dump's own tracks ---------------
    from datetime import timedelta
    rec_start = datetime.fromisoformat(video["recording_start_datetime"])
    start_hms = (rec_start + timedelta(seconds=f_lo / fps)).strftime("%H:%M:%S")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    bank_res = build_bank(
        camera=camera_id, project=project_id,
        out=str(workdir / f"twopass_bank_cam{camera_id}_{variant}.json"),
        start_hms=start_hms, minutes=window_seconds / 60.0,
        tracks=_dump_tracks_pointlists(rows))
    # Scale-1 merge expecteds = per-cell observed n from the corpus QA (any
    # admission status — a rejected path's traffic still counts toward the
    # gate's expectation), falling back to admitted-path supports. The A4a
    # harness recipe, productized.
    expected: dict[tuple, float] = {}
    for cell in bank_res.get("qa", {}).get("cells", []):
        m = _CELL_RE.match(cell.get("cell", ""))
        if m and "n" in cell:
            key = (int(m.group(1)), int(m.group(2)))
            expected[key] = max(expected.get(key, 0.0), float(cell["n"]))
    for p in bank_res["paths"]:
        key = (p["origin_leg_id"], p["destination_leg_id"])
        expected.setdefault(key, float(p.get("supporting_count", 0)))

    # --- 2+3. replay-classify (APPLIED bank), then the turn merge ------------
    # Variant in the name: a study day runs one pass-2 per trim window and the
    # working DBs must coexist (measure-then-apply per window).
    out_db = workdir / f"twopass_cam{camera_id}_{variant}.db"
    stats = replay_camera(project_id, camera_id, variant=variant, out_db=out_db)
    merge = merge_replay_turns(out_db, camera_id, window_seconds=window_seconds,
                               expected_by_cell=expected)

    result = {
        "camera_id": camera_id, "intersection_id": intersection_id,
        "variant": variant, "window_seconds": window_seconds,
        "corpus_bank_paths": len(bank_res["paths"]),
        "missing_movements": bank_res.get("missing_movements"),
        "replay": stats, "merge": {k: v for k, v in merge.items()
                                   if k != "borderline"},
        "borderline": merge["borderline"], "out_db": str(out_db),
        "applied": False,
    }
    if not apply:
        return result

    # --- 4. apply: swap this WINDOW's events into project.db (the applied
    # bank stays — it is the operator's attribution authority; other windows'
    # events stay — a study day is applied one trim window at a time), then
    # rebuild the queue with the S5 rows ---------------------------------
    proj_db = get_db_path(project_id)
    backup = proj_db.parent / "backups" / (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_pre_twopass_cam{camera_id}.db")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(proj_db, backup)
    _apply_window_events(proj_db, out_db, camera_id,
                         f_lo / fps, f_hi / fps)
    c = sqlite3.connect(proj_db)
    card = {lid: cd for lid, cd in c.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id = ?",
        (camera_id,))}
    c.close()

    extra = s5_flags(camera_id, merge["borderline"], card, bound_approach)
    flag_summary = rebuild_flags(project_id, intersection_id, extra_flags=extra)
    result.update({"applied": True, "backup": str(backup),
                   "flags": flag_summary})
    logger.info("two-pass apply cam%s: %s events (applied bank kept), backup %s",
                camera_id, stats["events"], backup)
    return result
