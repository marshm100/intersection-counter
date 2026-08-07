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

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

_CELL_RE = re.compile(r"L(\d+)->L(\d+)")

from backend.config import (
    EVIDENCE_ACTIVATION_COVERAGE,
    EVIDENCE_ACTIVATION_ENABLED,
    ORIGIN_POSTERIOR_ENABLED,
)
from backend.database import get_connection, get_db_path
from backend.services.detection_cache import compute_video_content_hash, parquet_path
from backend.services.flag_feeders import rebuild_flags
from backend.services.cardinals import bound_approach
from backend.services.pass2_replay import (
    JobCancelled, load_dump, replay_camera, tracks_dir,
)
from backend.services.turn_merge import merge_replay_turns, s5_flags

logger = logging.getLogger(__name__)

# Trim→window contract (stage 3.4 plan doc). A dump "satisfies" a derived
# window on coverage within this slack, not equality — a few-second trim edit
# (or the clamped-vs-unclamped start difference) must not orphan a multi-hour
# dump. Time-based, converted per camera fps (corridor cams are 10–25 fps).
WINDOW_SLACK_SECONDS = 5.0
# Legacy dumps (pre-"complete" marker) count as complete when the last dumped
# row is within this of the window end — cam3's gated study_0000 has a 118 s
# empty-midnight tail gap, so the tolerance must comfortably exceed that.
LEGACY_COMPLETE_TAIL_SECONDS = 300.0
# Every pass-1 resume restarts the tracker COLD, truncating tracks alive at
# the seam (the §2c edge-padding problem, at seams). Warm the tracker over
# this much preceding footage before the write boundary — long enough for a
# signal cycle + queue discharge. Time-based; converted per camera fps.
PASS1_SEAM_WARMUP_SECONDS = 90.0
# Detect-at-ingest writes the cache in closed per-chunk parquet parts so a
# crash resumes at chunk granularity instead of re-detecting hours.
PASS1_INGEST_CHUNK_SECONDS = 900.0


def _first_video(conn: sqlite3.Connection, camera_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM videos WHERE camera_id = ? ORDER BY sort_order LIMIT 1",
        (camera_id,)).fetchone()


def calib_fingerprint(project_id: str, camera_id: int) -> str:
    """Digest of every piece of OPERATOR state pass 2 consumes: calibration
    params, legs, the applied bank (attribution authority), and drawn channels
    (feed corpus-bank builds — standing rule 1 keeps them out of attribution).
    The pass-2 reuse sidecar keys on this + the dump meta, so a calibration
    edit invalidates a stale working DB (the stage-3.3 known limitation)."""
    from backend.database import get_camera_calibration_params
    calib = get_camera_calibration_params(project_id, camera_id)
    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    try:
        state = {"calib": calib}
        for name, table, order in (("legs", "legs", "leg_id"),
                                   ("paths", "intersection_paths", "path_id"),
                                   ("channels", "channels", "channel_id")):
            state[name] = [dict(r) for r in conn.execute(
                f"SELECT * FROM {table} WHERE camera_id = ? ORDER BY {order}",
                (camera_id,))]
    finally:
        conn.close()
    blob = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def schema_fingerprint(project_id: str) -> str:
    """Digest of the vehicle_events schema pass 2 writes through (ordered
    PRAGMA column names). The reuse sidecar keys on this alongside the calib
    fingerprint: a working DB computed before a schema migration must be
    RECOMPUTED, never re-applied — _apply_window_events INSERT-SELECTs
    project.db's live column list against the attached working DB, so a
    pre-migration one dies with "no such column ..." (int2's Error card,
    blind product test 2026-07-31)."""
    conn = get_connection(project_id)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(vehicle_events)")]
    finally:
        conn.close()
    return hashlib.sha256(",".join(cols).encode()).hexdigest()


def sidecar_reusable(prior: dict, meta: dict, calib_fp: str,
                     schema_fp: str) -> bool:
    """One source of truth for 'this pass-2 sidecar still describes reality':
    same dump, same operator state, same vehicle_events schema. Legacy
    sidecars missing a key fail closed (recompute once, then carry it)."""
    return (prior.get("dump_meta") == meta
            and prior.get("calib_fingerprint") == calib_fp
            and prior.get("schema_fingerprint") == schema_fp)


def _trim_datetimes(trim: dict, rec_start: datetime) -> tuple[datetime, datetime]:
    """Trim wallclock HH:MM:SS → datetimes on the recording's date. '24:00:00'
    and end-before-start both mean 'past midnight' (next day)."""
    date = rec_start.date().isoformat()

    def _parse(hms: str, *, bump_day: bool = False) -> datetime:
        if hms.startswith("24:"):
            dt = datetime.fromisoformat(f"{date}T00{hms[2:]}") + timedelta(days=1)
        else:
            dt = datetime.fromisoformat(f"{date}T{hms}")
        return dt + timedelta(days=1) if bump_day else dt

    t_start = _parse(trim["start_wallclock"])
    t_end = _parse(trim["end_wallclock"])
    if t_end <= t_start:
        t_end = _parse(trim["end_wallclock"], bump_day=True)
    return t_start, t_end


def derive_windows(project_id: str, intersection_id: int) -> list[dict]:
    """Map the card's trims to per-camera pass-1 dump windows — the naming
    contract the corridor dumps already follow, now written down:
      variant = 'study_' + trim start %H%M
      frames  = round((trim_wallclock − recording_start) × fps), UNCLAMPED
    (cam3's gated study_0000 starts at frame −20: a 00:00:00 trim against a
    00:00:02 recording start). Verified against all five corridor dump metas."""
    from backend.database import list_trims
    trims = list_trims(project_id, intersection_id)
    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    try:
        cams = conn.execute(
            "SELECT camera_id, label FROM cameras WHERE intersection_id = ? "
            "ORDER BY sort_order, camera_id", (intersection_id,)).fetchall()
        out: list[dict] = []
        for cam in cams:
            video = _first_video(conn, cam["camera_id"])
            if video is None:
                continue
            fps = float(video["fps"])
            rec_start = datetime.fromisoformat(video["recording_start_datetime"])
            for trim in trims:
                t_start, t_end = _trim_datetimes(trim, rec_start)
                out.append({
                    "camera_id": cam["camera_id"],
                    "camera_label": cam["label"],
                    "trim_id": trim["trim_id"],
                    "variant": f"study_{t_start.strftime('%H%M')}",
                    "start_frame": int(round((t_start - rec_start).total_seconds() * fps)),
                    "end_frame": int(round((t_end - rec_start).total_seconds() * fps)),
                    "start_wallclock": trim["start_wallclock"],
                    "end_wallclock": trim["end_wallclock"],
                    "fps": fps,
                })
        return out
    finally:
        conn.close()


def _camera_parquet(project_id: str, camera_id: int, variant: str) -> Path:
    from backend.services.detection_cache import HASH_METHOD
    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    try:
        video = _first_video(conn, camera_id)
    finally:
        conn.close()
    if video is None:
        raise ValueError(f"camera {camera_id}: no video row")
    # Prefer the persisted hash — plan_intersection runs on card open and a
    # fresh 128 MiB hash per camera per view would make the card feel stuck.
    if (video["content_hash"]
            and video["content_hash_method"] == HASH_METHOD):
        chash = video["content_hash"]
    else:
        chash, _ = compute_video_content_hash(
            video["path"], file_size_bytes=video["file_size_bytes"],
            total_frames=video["total_frames"])
    return parquet_path(project_id, camera_id, chash, variant)


def dump_status(pq: Path, start_frame: int, end_frame: int, fps: float) -> dict:
    """Classify a pass-1 dump against a derived window: ready | partial |
    missing | mismatch (coverage rule + completeness marker, plan doc §1)."""
    tdir = tracks_dir(pq)
    meta_p, count_p = tdir / "meta.json", tdir / "count.txt"
    if not (meta_p.exists() and count_p.exists() and (tdir / "rows.npy").exists()):
        return {"status": "missing"}
    meta = json.loads(meta_p.read_text())
    f_lo, f_hi = meta.get("frames", [None, None])
    slack = WINDOW_SLACK_SECONDS * fps
    if f_lo is None or f_lo > start_frame + slack or f_hi < end_frame - slack:
        return {"status": "mismatch", "frames": meta.get("frames")}
    if meta.get("complete"):
        return {"status": "ready", "frames": [f_lo, f_hi], "recipe": meta.get("backend")}
    # Legacy dump (pre-marker): complete iff the last dumped row is near the
    # window end. Empty-tail tolerance covers cam3's 118 s midnight gap.
    try:
        n = int(count_p.read_text())
        rows = np.load(tdir / "rows.npy", mmap_mode="r")
        last_frame = int(rows[n - 1, 1]) if n else f_lo
    except Exception:
        return {"status": "partial", "frames": [f_lo, f_hi]}
    if last_frame >= f_hi - LEGACY_COMPLETE_TAIL_SECONDS * fps:
        return {"status": "ready", "frames": [f_lo, f_hi], "recipe": meta.get("backend")}
    return {"status": "partial", "frames": [f_lo, f_hi], "last_frame": last_frame}


def plan_intersection(project_id: str, intersection_id: int,
                      workdir: str | Path) -> list[dict]:
    """The card's two-pass readiness view: each derived window + cache/dump/
    pass-2 status. pass2 'current' = a reuse sidecar that matches BOTH the
    dump meta and the live calibration fingerprint."""
    from backend.services.detection_cache import cache_exists
    workdir = Path(workdir)
    plan = derive_windows(project_id, intersection_id)
    fp_cache: dict[int, str] = {}
    schema_fp: str | None = None
    for w in plan:
        cid = w["camera_id"]
        try:
            pq = _camera_parquet(project_id, cid, w["variant"])
        except (ValueError, OSError):
            # no video row / video file unreadable — everything's missing
            w.update(cache="missing", dump={"status": "missing"}, pass2="missing")
            continue
        w["cache"] = "ready" if cache_exists(pq) else "missing"
        w["dump"] = dump_status(pq, w["start_frame"], w["end_frame"], w["fps"])
        stats_p = workdir / f"twopass_cam{cid}_{w['variant']}.stats.json"
        w["pass2"] = "missing"
        if stats_p.exists() and w["dump"]["status"] == "ready":
            try:
                prior = json.loads(stats_p.read_text())
                meta = json.loads((tracks_dir(pq) / "meta.json").read_text())
                if cid not in fp_cache:
                    fp_cache[cid] = calib_fingerprint(project_id, cid)
                if schema_fp is None:
                    schema_fp = schema_fingerprint(project_id)
                if sidecar_reusable(prior, meta, fp_cache[cid], schema_fp):
                    w["pass2"] = "current"
                else:
                    w["pass2"] = "stale"
            except Exception:
                w["pass2"] = "stale"
    return plan


def _dump_tracks_pointlists(rows: np.ndarray) -> list[list[tuple]]:
    """Group dump rows into per-track point lists (build_bank input shape)."""
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append((float(r[2]), float(r[3])))
    return list(tracks.values())


_ADDITIVE = ("branch1", "rescue_full", "rescue_supports")
_ADDITIVE_RANK = {"rescue_full": 0, "branch1": 1, "rescue_supports": 2}


def conserve_replay_additions(db: str | Path, camera_id: int,
                              chain_map: dict) -> dict:
    """The conservation pass (plan_conservation_pass_2026-07-15): at most one
    counted event per fragment CHAIN, and additive events (posterior_source
    branch1/rescue_*) always lose to legacy events. Write-then-reject, the
    turn-merge pattern (rejected=1, non-destructive). Singleton/unmapped
    tracks are untouched. Returns counter stats."""
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT event_id, vehicle_track_id, posterior_source, "
        "COALESCE(classifier_num_points, 0) FROM vehicle_events "
        "WHERE camera_id = ? AND COALESCE(rejected, 0) = 0",
        (camera_id,)).fetchall()
    groups: dict = {}
    for eid, tid, src, npts in rows:
        cid = chain_map.get(int(tid))
        if cid is None:
            continue
        groups.setdefault(cid, []).append((eid, src, npts))
    reject: list = []
    n_legacy_dupe = n_additive_dupe = 0
    for evs in groups.values():
        if len(evs) < 2:
            continue
        additive = [e for e in evs if e[1] in _ADDITIVE]
        if not additive:
            continue                      # legacy multi-counts pre-date us
        if len(additive) < len(evs):
            # the chain already has a legacy event: every additive one is a
            # duplicate of a counted vehicle
            reject += [e[0] for e in additive]
            n_legacy_dupe += len(additive)
        else:
            # all additive: keep the single best-evidenced (longest breaks
            # ties), reject the rest
            additive.sort(key=lambda e: (_ADDITIVE_RANK.get(e[1], 9),
                                         -e[2], e[0]))
            reject += [e[0] for e in additive[1:]]
            n_additive_dupe += len(additive) - 1
    with conn:
        conn.executemany(
            "UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?",
            [(eid,) for eid in reject])
    conn.close()
    return {"chains_with_events": len(groups), "rejected": len(reject),
            "rejected_vs_legacy": n_legacy_dupe,
            "rejected_vs_additive": n_additive_dupe}


def conserve_pass(project_id: str, camera_id: int, rows: np.ndarray,
                  fps: float, out_db: str | Path) -> dict:
    """Convenience wrapper for run_pass2 + the ablation harness: build the
    pinned gates + fragment-chain map from the dump, then conserve."""
    from backend.database import list_paths_for_camera
    from backend.services.entry_gates import build_gates
    from backend.services.track_chains import build_chain_map
    conn = get_connection(project_id)
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id = ?", (camera_id,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
    conn.close()
    if not mouths:
        return {"skipped": "no leg mouths"}
    gates = build_gates(mouths, list_paths_for_camera(project_id, camera_id),
                        heads)
    if not gates:
        return {"skipped": "no gates"}
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append(
            (float(r[1]), float(r[2]), float(r[3])))
    chain_map = build_chain_map(tracks, gates, fps)
    return conserve_replay_additions(out_db, camera_id, chain_map)


def census_expecteds(project_id: str, camera_id: int, rows: np.ndarray,
                     fps: float) -> dict:
    """Gate-evidence merge expecteds (posterior half stage 3,
    plan_posterior_half_2026-07-15): per-cell observed n from the dump's own
    entry/exit-gate crossings instead of the bank builder's flip-prone shape
    assignment. Gates = operator mouths + the APPLIED bank's tangents — the
    same pinned geometry the pipeline's evidence gate uses. Shared by
    run_pass2 and the ablation harness (one source of truth)."""
    from backend.database import list_paths_for_camera
    from backend.services.entry_gates import build_gates, cell_census
    conn = get_connection(project_id)
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id = ?", (camera_id,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
    conn.close()
    if not mouths:
        return {}
    gates = build_gates(mouths, list_paths_for_camera(project_id, camera_id),
                        heads)
    if not gates:
        return {}
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append(
            (float(r[1]), float(r[2]), float(r[3])))
    return cell_census(tracks.values(), gates, fps)


def strict_full_census(project_id: str, camera_id: int, rows: np.ndarray,
                       fps: float) -> dict:
    """FULL gate-to-gate journeys per cell (classify tag=='full') — the
    V2-demotion selector's census. cell_census's partial-evidence credits
    are too loose for flood detection (day-6b: cam2 28->29 loose census
    >=110 vs 54 strict fulls masked the 4.1x flood ratio)."""
    from backend.database import list_paths_for_camera
    from backend.services.entry_gates import build_gates, classify
    conn = get_connection(project_id)
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id = ?", (camera_id,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
    conn.close()
    if not mouths:
        return {}
    gates = build_gates(mouths, list_paths_for_camera(project_id, camera_id),
                        heads)
    if not gates:
        return {}
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append(
            (float(r[1]), float(r[2]), float(r[3])))
    # channel families by origin, for the entanglement measure
    paths = list_paths_for_camera(project_id, camera_id)
    chans: dict[int, list] = {}
    for p in paths:
        if p.get("polyline"):
            chans.setdefault(int(p["origin_leg_id"]), []).append(p["polyline"])

    def _mean_dist(poly, pts):
        best = [float("inf")] * len(pts)
        for i in range(len(poly) - 1):
            ax, ay = poly[i]
            bx, by = poly[i + 1]
            vx, vy = bx - ax, by - ay
            L2 = vx * vx + vy * vy
            if L2 < 1e-9:
                continue
            for k, (px, py) in enumerate(pts):
                t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
                d = ((px - (ax + t * vx)) ** 2 + (py - (ay + t * vy)) ** 2) ** 0.5
                if d < best[k]:
                    best[k] = d
        return sum(best) / len(best) if best else float("inf")

    out: dict[tuple, int] = {}
    conf_n: dict[int, int] = {}
    conf_r: dict[int, int] = {}
    full_by_tid: dict[int, tuple] = {}
    for tid, tr in tracks.items():
        o, d, _of, _df, _op, _dp, tag = classify(tr, gates, fps)
        if tag != "full":
            continue
        o, d = int(o), int(d)
        out[(o, d)] = out.get((o, d), 0) + 1
        full_by_tid[int(tid)] = (o, d, float(_of) if _of is not None else None)
        early = [(x, y) for _f, x, y in tr[:12]]
        d_own = min((_mean_dist(p, early) for p in chans.get(o, [])),
                    default=float("inf"))
        d_riv = min((_mean_dist(p, early) for ol, ps in chans.items()
                     if ol != o for p in ps), default=float("inf"))
        conf_n[o] = conf_n.get(o, 0) + 1
        if d_riv < d_own:
            conf_r[o] = conf_r.get(o, 0) + 1
    confusion = {o: conf_r.get(o, 0) / n for o, n in conf_n.items() if n}
    return out, confusion, full_by_tid


def run_pass1(project_id: str, camera_id: int, *, variant: str,
              start_frame: int, end_frame: int, backend: str | None = None,
              resume: bool = True, progress=None, should_cancel=None) -> dict:
    """Pass 1: raw-track dump for one camera window — the productized core of
    scripts/dump_raw_tracks.py (the CLI wraps this). Semantics-free: no legs,
    channels, or classification; live-parity tracking input (per-camera
    pre-track NMS -> bbox buffer -> tracker, full frame schedule incl. empty
    updates — the A2 tier-1 lessons).

    Detection source (stage 3.4): the variant's detection cache when it
    exists; otherwise DETECT-AT-INGEST — decode the window once, detect with
    the project's processing-mode config, write-through the cache in closed
    ~15-min parquet chunks (crash-resumable; a ParquetWriter file without its
    footer is unreadable), and merge to the variant parquet at completion.
    First run = detect+cache+dump; re-runs = pass 2 only.

    backend: None -> the camera's calib_pass1_backend (default bytetrack).
    'botsort+reid' loads the pre-built ReID sidecar (build_reid_cache);
    missing sidecar is an actionable error, not an implicit hours-long build.
    resume: continue from the high-water mark when the existing dump's recipe
    matches (recipe mismatch = hard error). Every resume warms the tracker
    over the preceding ~PASS1_SEAM_WARMUP_SECONDS so the seam doesn't
    truncate tracks mid-intersection (the §2c edge-padding problem, at seams;
    ID reuse across the seam is handled downstream by the finalize-gap)."""
    import numpy as _np
    from numpy.lib.format import open_memmap

    from backend.config import PRE_TRACK_NMS_IOU
    from backend.database import get_camera_calibration_params
    from backend.services.detection_cache import cache_exists
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
    chash, hash_method = compute_video_content_hash(
        video["path"], file_size_bytes=video["file_size_bytes"],
        total_frames=video["total_frames"])
    pq = parquet_path(project_id, camera_id, chash, variant)
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
    out.mkdir(parents=True, exist_ok=True)
    warm_frames = int(PASS1_SEAM_WARMUP_SECONDS * fps)

    def _check_resume_meta():
        old_meta = json.loads((out / "meta.json").read_text())
        mismatches = [k for k in ("format", "frames", "backend", "nms_iou",
                                  "activation", "match", "bbox_buffer")
                      if old_meta.get(k) != meta.get(k)]
        if mismatches:
            raise ValueError(
                f"pass-1 resume: existing dump differs on {mismatches} — "
                f"delete {out} to start over")

    # Shared per-frame step: NMS -> bbox buffer -> tracker -> dump rows.
    # write=False = warm-up (tracker state only, nothing persisted).
    state = {"mm": None, "w": 0}

    def _grow_rows(extra: int) -> None:
        """rows.npy capacity is an estimate; grow by copy when it falls short
        (the ingest path has no detection count to estimate from)."""
        import os
        mm = state["mm"]
        if state["w"] + extra <= mm.shape[0]:
            return
        new_cap = max(mm.shape[0] * 2, state["w"] + extra + 1000)
        mm.flush(); del mm
        state["mm"] = None
        tmp = out / "rows_grow.npy"
        new = open_memmap(tmp, mode="w+", dtype=_np.float32, shape=(new_cap, 8))
        old = open_memmap(out / "rows.npy", mode="r")
        new[:state["w"]] = old[:state["w"]]
        del old
        new.flush(); del new
        os.replace(tmp, out / "rows.npy")
        state["mm"] = open_memmap(out / "rows.npy", mode="r+")

    def _step(fidx: int, dets: list, write: bool = True) -> None:
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
        tracks = be.update(dets, fidx)
        if not write:
            return
        _grow_rows(len(tracks))
        mm = state["mm"]
        for t in tracks:
            cx, cy = t["center"]
            mm[state["w"]] = (
                float(t["track_id"]), float(fidx), float(cx), float(cy),
                float(t.get("bbox_width", 0.0)), float(t.get("bbox_height", 0.0)),
                float(t.get("confidence", 0.0)), float(t.get("class_id", -1)))
            state["w"] += 1

    if cache_exists(pq):
        _pass1_from_cache(
            pq, out, meta, start_frame, end_frame, warm_frames, resume,
            progress, state, _step, _check_resume_meta, open_memmap, _np,
            should_cancel)
    else:
        _pass1_ingest(
            project_id, video, chash, hash_method, pq, out, meta, fps,
            start_frame, end_frame, warm_frames, resume, progress, state,
            _step, _check_resume_meta, open_memmap, _np, should_cancel)

    mm = state["mm"]
    mm.flush(); del mm
    state["mm"] = None
    (out / "count.txt").write_text(str(state["w"]))
    # Positive completeness marker (plan doc §1): nothing else distinguishes a
    # finished dump from an interrupted one (count.txt updates mid-run). The
    # start-of-run meta write deliberately omits it, so a resumed dump reads
    # incomplete until this line runs.
    meta["complete"] = True
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return {"camera_id": camera_id, "variant": variant, "recipe": recipe,
            "rows": state["w"], "frames": [start_frame, end_frame],
            "tracks_dir": str(out)}


def _pass1_from_cache(pq, out, meta, start_frame, end_frame, warm_frames,
                      resume, progress, state, step, check_resume_meta,
                      open_memmap, _np, should_cancel=None) -> None:
    """Pass-1 tracking over an existing detection-cache parquet (the original
    stage-3.3 path, plus the resume seam warm-up)."""
    from backend.services.detection_cache import DetectionCacheReader

    reader = DetectionCacheReader(pq)
    n_dets = sum(len(d) for f, d in reader.iter_frames()
                 if start_frame <= f < end_frame)
    cap_rows = int(n_dets * 1.2) + 1000

    resume_from = start_frame
    if resume and (out / "rows.npy").exists() and (out / "count.txt").exists():
        check_resume_meta()
        mm = open_memmap(out / "rows.npy", mode="r+")
        w0 = int((out / "count.txt").read_text())
        if w0 > 0:
            f_last = int(mm[w0 - 1, 1])
            w = w0
            while w > 0 and int(mm[w - 1, 1]) == f_last:
                w -= 1
            state["w"] = w
            resume_from = f_last
        state["mm"] = mm
    if state["mm"] is None:
        state["mm"] = open_memmap(out / "rows.npy", mode="w+",
                                  dtype=_np.float32, shape=(cap_rows, 8))
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    # Warm the tracker over the seam so resumed tracks aren't born cold at
    # the boundary (rows before resume_from are already in the dump).
    loop_start = resume_from
    if resume_from > start_frame:
        loop_start = max(start_frame, resume_from - warm_frames)

    reader_iter = DetectionCacheReader(pq).iter_frames()
    nxt = next(reader_iter, None)
    done = 0
    for fidx in range(loop_start, end_frame):
        if should_cancel is not None and should_cancel():
            # flush so the resume high-water mark reflects everything written
            state["mm"].flush()
            (out / "count.txt").write_text(str(state["w"]))
            raise JobCancelled(f"pass-1 cancelled at frame {fidx} (resumable)")
        while nxt is not None and nxt[0] < fidx:
            nxt = next(reader_iter, None)
        if nxt is not None and nxt[0] == fidx:
            dets = nxt[1]
            nxt = next(reader_iter, None)
        else:
            dets = []
        step(fidx, dets, write=(fidx >= resume_from))
        done += 1
        if done % 5000 == 0:
            state["mm"].flush()
            (out / "count.txt").write_text(str(state["w"]))
            if progress:
                progress(done, end_frame - loop_start, state["w"])


def _pass1_ingest(project_id, video, chash, hash_method, pq, out, meta, fps,
                  start_frame, end_frame, warm_frames, resume, progress,
                  state, step, check_resume_meta, open_memmap, _np,
                  should_cancel=None) -> None:
    """Detect-at-ingest: no cache for this variant — decode the window ONCE,
    detect with the project's processing-mode config, write-through the cache
    in closed per-chunk parquet parts (resume at chunk granularity; a crashed
    ParquetWriter file has no footer and is unreadable), track+dump in the
    same pass, merge parts -> the variant parquet at completion."""
    import cv2

    from backend.config import DEFAULT_PROCESSING_MODE, get_processing_mode_config
    from backend.database import get_project_info
    from backend.services.detection_cache import (
        DetectionCacheReader, DetectionCacheWriter)

    mode_name = (get_project_info(project_id, "processing_mode")
                 or DEFAULT_PROCESSING_MODE)
    cfg = get_processing_mode_config(mode_name)
    skip = int(cfg.get("detection_skip") or 1)
    chunk_frames = max(1, int(PASS1_INGEST_CHUNK_SECONDS * fps))
    n_chunks = max(1, -(-(end_frame - start_frame) // chunk_frames))

    def part_path(k: int) -> Path:
        return pq.with_name(f"{pq.stem}.part{k:05d}.parquet")

    # Resume point = the first chunk whose part is missing or unreadable.
    k0 = 0
    for k in range(n_chunks):
        p = part_path(k)
        if not p.exists():
            break
        try:
            DetectionCacheReader(p)
        except Exception:
            break
        k0 = k + 1
    resume_from = start_frame + k0 * chunk_frames
    if (k0 and resume and (out / "rows.npy").exists()
            and (out / "count.txt").exists()):
        check_resume_meta()
        mm = open_memmap(out / "rows.npy", mode="r+")
        # Truncate to rows strictly before the resume chunk: count.txt is
        # written after the part closes, so a crash between the two leaves
        # either stale count (no-op here) or rows past the last closed part
        # (dropped here) — both orders reconverge.
        w = int((out / "count.txt").read_text())
        while w > 0 and int(mm[w - 1, 1]) >= resume_from:
            w -= 1
        state["mm"], state["w"] = mm, w
    else:
        k0 = 0
        resume_from = start_frame
        for k in range(n_chunks):
            part_path(k).unlink(missing_ok=True)
        cap_rows = (end_frame - start_frame) * 8 + 1000
        state["mm"] = open_memmap(out / "rows.npy", mode="w+",
                                  dtype=_np.float32, shape=(cap_rows, 8))
        state["w"] = 0
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    # Seam warm-up from the tail of the last closed part.
    if k0 > 0:
        warm_from = max(start_frame, resume_from - warm_frames)
        rd = DetectionCacheReader(part_path(k0 - 1)).iter_frames()
        nxt = next(rd, None)
        for fidx in range(warm_from, resume_from):
            while nxt is not None and nxt[0] < fidx:
                nxt = next(rd, None)
            if nxt is not None and nxt[0] == fidx:
                dets = nxt[1]
                nxt = next(rd, None)
            else:
                dets = []
            step(fidx, dets, write=False)

    from backend.services.detector import VehicleDetector
    detector = VehicleDetector(model_path=cfg["yolo_model"],
                               imgsz=cfg["yolo_imgsz"],
                               confidence=cfg["yolo_confidence"],
                               class_scheme=cfg.get("yolo_class_scheme",
                                                    "coco"))
    cap = cv2.VideoCapture(video["path"])
    try:
        decode_from = max(0, resume_from)
        if decode_from:
            cap.set(cv2.CAP_PROP_POS_FRAMES, decode_from)
        done, total = 0, end_frame - resume_from
        for k in range(k0, n_chunks):
            c_lo = start_frame + k * chunk_frames
            c_hi = min(end_frame, c_lo + chunk_frames)
            writer = DetectionCacheWriter(pq_path=part_path(k), metadata={})
            for fidx in range(c_lo, c_hi):
                if should_cancel is not None and should_cancel():
                    # mid-chunk cancel = the crash-resume path: the open part
                    # has no footer, so resume re-enters at this chunk's start
                    raise JobCancelled(
                        f"pass-1 ingest cancelled in chunk {k} (resumable)")
                dets = []
                if fidx >= 0:                      # pre-recording frames (cam3
                    ok, frame = cap.read()         # -20 case) don't exist
                    if ok and fidx % skip == 0:
                        dets = detector.detect(frame)
                        writer.add(fidx, dets)     # cache stays raw, pre-NMS
                step(fidx, dets)
                done += 1
                if progress and done % 200 == 0:
                    progress(done, total, state["w"])
            state["mm"].flush()
            (out / "count.txt").write_text(str(state["w"]))
            writer.close()
    finally:
        cap.release()

    # Merge closed parts -> the variant parquet + provenance sidecar (the
    # same shape the live pipeline's write-through produces, plus windows).
    merged = DetectionCacheWriter(pq_path=pq, metadata={
        "camera_id": int(video["camera_id"]), "content_hash": chash,
        "method": hash_method, "model": cfg["yolo_model"],
        "imgsz": cfg["yolo_imgsz"], "confidence": cfg["yolo_confidence"],
        "detection_skip": skip,
        "windows": [[start_frame, end_frame]]})
    for k in range(n_chunks):
        for fidx, dets in DetectionCacheReader(part_path(k)).iter_frames():
            merged.add(fidx, dets)
    merged.close()
    for k in range(n_chunks):
        p = part_path(k)
        p.unlink(missing_ok=True)
        p.with_suffix(".meta.json").unlink(missing_ok=True)


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
              workdir: str | Path, apply: bool = False,
              should_cancel=None) -> dict:
    """Pass 2 for one camera from its pass-1 dump. Returns stats incl. the
    working DB path; apply=True additionally swaps events+bank into project.db
    (backup first) and rebuilds the intersection's flag queue with S5 rows.

    should_cancel: polled at stage boundaries and inside the replay frame
    loop (JobCancelled). The corpus-bank build is not interruptible (scripts
    function), and _finish_apply never is — apply stays atomic."""
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

    # --- 0. reuse: a prior compute of THIS dump is still valid ----------------
    # (apply=True used to recompute the whole pass-2 — 2x wall time for
    # nothing when the working DB was just measured. The stats sidecar records
    # the dump meta AND the calibration fingerprint; matching both = identical
    # inputs = reuse. The fingerprint closes the stage-3.3 known limitation:
    # an operator calibration/bank/channel edit now invalidates the sidecar.
    # Legacy sidecars lack the key -> recompute once, then carry it.)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    fingerprint = calib_fingerprint(project_id, camera_id)
    schema_fp = schema_fingerprint(project_id)
    out_db = workdir / f"twopass_cam{camera_id}_{variant}.db"
    stats_p = workdir / f"twopass_cam{camera_id}_{variant}.stats.json"
    if out_db.exists() and stats_p.exists():
        prior = json.loads(stats_p.read_text())
        if sidecar_reusable(prior, meta, fingerprint, schema_fp):
            logger.info("two-pass cam%s %s: reusing computed working DB", camera_id, variant)
            result = prior["result"]
            result["reused"] = True
            if not apply:
                return result
            return _finish_apply(project_id, camera_id, intersection_id,
                                 out_db, f_lo, f_hi, fps, result)

    # --- 1. corpus bank: discovery over the dump's own tracks ---------------
    if should_cancel is not None and should_cancel():
        raise JobCancelled(f"pass-2 cancelled before corpus bank (cam {camera_id})")
    from datetime import timedelta
    rec_start = datetime.fromisoformat(video["recording_start_datetime"])
    start_hms = (rec_start + timedelta(seconds=f_lo / fps)).strftime("%H:%M:%S")
    bank_res = build_bank(
        camera=camera_id, project=project_id,
        out=str(workdir / f"twopass_bank_cam{camera_id}_{variant}.json"),
        start_hms=start_hms, minutes=window_seconds / 60.0,
        tracks=_dump_tracks_pointlists(rows))
    # Scale-1 merge expecteds. Posterior half ON: per-cell observed n from
    # GATE EVIDENCE over the dump (census_expecteds — the bank builder's own
    # shape assignment is flip-prone and starved stolen cells; measured 17/14
    # genuine box-full EB-lefts merge-rejected per held-out window). Flag
    # OFF: the legacy corpus-QA derivation, byte-identical (any admission
    # status — a rejected path's traffic still counts toward the gate's
    # expectation — falling back to admitted-path supports; the A4a recipe).
    expected: dict[tuple, float] = {}
    if ORIGIN_POSTERIOR_ENABLED:
        expected = census_expecteds(project_id, camera_id, rows, fps)
    if not expected:
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
    if should_cancel is not None and should_cancel():
        raise JobCancelled(f"pass-2 cancelled after corpus bank (cam {camera_id})")
    # Evidence-gate activation precondition (plan_evidence_activation
    # PHASE-1 VERDICT): PROBE replay first — evidence counted, zero
    # attribution effect, so this replay IS the legacy result — then only a
    # camera whose own blind coverage clears the bar re-replays with the
    # proven pair (gate + posterior, replay-level only). Flag OFF: plain
    # legacy replay, byte-identical.
    activation = None
    if EVIDENCE_ACTIVATION_ENABLED:
        stats = replay_camera(project_id, camera_id, variant=variant,
                              out_db=out_db, should_cancel=should_cancel,
                              evidence_mode="probe")
        n_tracks = int(stats.get("tracks") or 0)
        coverage = (stats.get("origin_evidenced", 0) / n_tracks
                    if n_tracks else 0.0)
        activation = {"coverage": round(coverage, 3),
                      "threshold": EVIDENCE_ACTIVATION_COVERAGE,
                      "activated": coverage >= EVIDENCE_ACTIVATION_COVERAGE}
        logger.info("two-pass cam%s %s: evidence coverage %.3f -> %s",
                    camera_id, variant, coverage,
                    "ACTIVATE" if activation["activated"] else "stand down")
        if activation["activated"]:
            stats = replay_camera(project_id, camera_id, variant=variant,
                                  out_db=out_db, should_cancel=should_cancel,
                                  evidence_mode="on")
    else:
        stats = replay_camera(project_id, camera_id, variant=variant,
                              out_db=out_db, should_cancel=should_cancel)
    # V2 census-ratio demotion (config flag, default OFF): measure per-cell
    # DIRECT-attributed mass from the first replay against the gate-evidence
    # census; flooded cells re-replay with their direct claims demoted to
    # the branch1 posterior. GT-free throughout (census = gate evidence).
    demotion = None
    from backend import config as _cfg
    if getattr(_cfg, "V2_DEMOTION_ENABLED", False) and expected:
        _c = sqlite3.connect(out_db)
        direct = {(int(o), int(d)): int(n) for o, d, n in _c.execute(
            "SELECT origin_leg_id, destination_leg_id, COUNT(*) "
            "FROM vehicle_events WHERE camera_id=? AND "
            "COALESCE(rejected,0)=0 AND posterior_source IS NULL "
            "AND origin_leg_id IS NOT NULL AND destination_leg_id IS NOT NULL "
            "GROUP BY 1,2", (camera_id,))}
        _c.close()
        ratio = getattr(_cfg, "V2_DEMOTION_RATIO", 2.0)
        # Census from the UNEXTENDED base dump when replaying a derived
        # variant (stack verdict 2026-08-05: extension COMPLETES the
        # flood's false-origin tracks into legitimate-looking fulls and
        # poisons the flooded cell's census -> dose under-fires; the base
        # dump is extension-proof; r_clean absorbs extension's global
        # direct-count inflation on the clean cells).
        census_rows = rows
        base_variant = variant
        for _pref in ("v2c_", "v2a_", "v2b_", "v2d_"):
            if variant.startswith(_pref):
                base_variant = variant[len(_pref):]
                break
        if base_variant != variant:
            _btdir = tracks_dir(parquet_path(project_id, camera_id, chash,
                                             base_variant))
            if (_btdir / "count.txt").exists():
                census_rows = load_dump(_btdir)
        strict, confusion, _full_map = strict_full_census(
            project_id, camera_id, census_rows, fps)
        # ENTANGLEMENT CONDITION (day-6b selector fix): only origins whose
        # own genuine fulls MAJORITY-read as a rival's lanes are demotable —
        # a ratio flag on a clean-geometry origin is recall STARVATION, and
        # demoting starved cells smears real events (SB-right -34 lesson).
        # CONTRAST GUARD (cam1 transfer verdict 2026-08-05): the confusion
        # measure SATURATES on oblique geometry (cam1: 3 of 4 origins read
        # 0.73-1.0 — that is the measure's ceiling, not selectivity; cam2's
        # true signature is ONE origin 0.98 vs median 0.08). Demotion needs
        # an entangled origin against OTHERWISE-CLEAN geometry; saturated
        # cameras stand down entirely.
        conf_vals = sorted(confusion.values())
        others_med = (conf_vals[len(conf_vals) // 2 - 1]
                      if len(conf_vals) >= 2 else 1.0)
        contrast_ok = others_med < 0.25
        flooded = {cell for cell, nd in direct.items()
                   if contrast_ok and confusion.get(cell[0], 0.0) > 0.5
                   and nd > ratio * max(float(strict.get(cell, 0)), 1.0)}
        # DOSE (held-out verdict 2026-08-05: binary demotion overshoots
        # small-excess windows — PM EB-right +85 -> -177): the CLEAN
        # origins' own direct/strict ratio is the window's recall-inflation
        # factor; a flooded cell keeps that many directs per strict full
        # and demotes only the EXCESS, sampled deterministically per track.
        clean_ratios = [nd / max(float(strict.get(c, 0)), 1.0)
                        for c, nd in direct.items()
                        if confusion.get(c[0], 0.0) <= 0.5
                        and strict.get(c, 0) >= 20 and nd >= 20]
        import statistics as _st
        r_clean = (_st.median(clean_ratios) if clean_ratios else 1.0)
        demote_frac = {
            cell: max(0.0, 1.0 - (r_clean * max(float(strict.get(cell, 0)), 1.0)
                                  / direct[cell]))
            for cell in flooded}
        if flooded:
            # TIME-LOCAL allocation mix (block-2 item 4): per-15-min-segment
            # origin proportions from the BASE dump's strict-census fulls
            # (scale-1 per segment by construction; add-one smoothed;
            # sampler falls back to window-global bank supports when a
            # segment is thin). Bins-only change by design.
            seg_frames = 900.0 * fps
            seg_supports: dict = {}
            for _tid, g in _full_map.items():
                if g[2] is None:
                    continue
                seg = int((g[2] - f_lo) / seg_frames)
                key = (int(g[1]), seg)
                seg_supports.setdefault(key, {})
                seg_supports[key][int(g[0])] = \
                    seg_supports[key].get(int(g[0]), 0) + 1
            timelocal = ({"f_lo": float(f_lo), "seg_frames": seg_frames,
                          "supports": seg_supports}
                         if getattr(_cfg, "V2_TIMELOCAL", False) else None)
            ev_final = ("on" if (activation and activation.get("activated"))
                        else ("probe" if activation is not None else None))
            logger.info("two-pass cam%s %s: demotion re-replay, cells=%s",
                        camera_id, variant, sorted(flooded))
            stats = replay_camera(project_id, camera_id, variant=variant,
                                  out_db=out_db, should_cancel=should_cancel,
                                  evidence_mode=ev_final,
                                  demoted_cells=demote_frac,
                                  demotion_timelocal=timelocal)
        demotion = {"cells": sorted(list(c) for c in flooded),
                    "dose": {f"{k[0]}->{k[1]}": round(v, 3)
                             for k, v in sorted(demote_frac.items())},
                    "r_clean": round(r_clean, 3),
                    "direct": {f"{k[0]}->{k[1]}": v for k, v in
                               sorted(direct.items())},
                    "census_strict": {f"{k[0]}->{k[1]}": v for k, v in
                                      sorted(strict.items())},
                    "confusion": {str(k): round(v, 3)
                                  for k, v in sorted(confusion.items())},
                    "ratio": ratio}
    # Conservation pass (posterior half iteration 3): at most one counted
    # event per fragment chain, additive loses to legacy — BEFORE the merge
    # so the volume gate polices turns over de-duplicated counts.
    if ORIGIN_POSTERIOR_ENABLED:
        conserve = conserve_pass(project_id, camera_id, rows, fps, out_db)
        stats["conservation"] = conserve
        logger.info("two-pass cam%s %s: conservation %s", camera_id, variant,
                    conserve)
    merge = merge_replay_turns(out_db, camera_id, window_seconds=window_seconds,
                               expected_by_cell=expected)
    # V2 MERGE RESCUE (block-2 item 1, diagnosis 2026-08-06): a merged-away
    # turn whose track is a GATE-VERIFIED FULL JOURNEY in a DIFFERENT cell
    # was a misclassified real vehicle (35 gate-verified SB-thrus deleted as
    # SB-right excess on the extended dev dump) — reclassify to the gate
    # cell instead of deleting. Same-cell rejects stay rejected (the volume
    # gate's genuine-excess semantics intact). Gate evidence outranks the
    # volume prior. Census from the REPLAYED variant's own rows here (the
    # journeys being rescued are this dump's).
    from backend import config as _cfg
    if getattr(_cfg, "V2_MERGE_RESCUE", False):
        _strict2, _conf2, full_map2 = strict_full_census(
            project_id, camera_id, rows, fps)
        conn_r = sqlite3.connect(out_db)
        conn_r.row_factory = sqlite3.Row
        legs_r = {r["leg_id"]: dict(r) for r in conn_r.execute(
            "SELECT * FROM legs WHERE camera_id=?", (camera_id,))}
        all_legs_r = list(legs_r.values())
        from backend.services.trajectory_classifier import derive_movement
        rescued = 0
        with conn_r:
            for ev in conn_r.execute(
                    "SELECT event_id, vehicle_track_id, origin_leg_id, "
                    "destination_leg_id FROM vehicle_events "
                    "WHERE camera_id=? AND COALESCE(rejected,0)=1",
                    (camera_id,)).fetchall():
                g = full_map2.get(int(ev["vehicle_track_id"]))
                if not g or g[:2] == (ev["origin_leg_id"],
                                      ev["destination_leg_id"]):
                    continue
                o_g, d_g = g[0], g[1]
                if o_g not in legs_r or d_g not in legs_r:
                    continue
                mv = derive_movement(legs_r[o_g], legs_r[d_g], all_legs_r)
                conn_r.execute(
                    "UPDATE vehicle_events SET rejected=0, origin_leg_id=?, "
                    "destination_leg_id=?, movement=? WHERE event_id=?",
                    (o_g, d_g, mv, ev["event_id"]))
                rescued += 1
        conn_r.close()
        merge["rescued_cross_cell"] = rescued
        logger.info("two-pass cam%s %s: merge-rescue reclassified %s "
                    "gate-verified cross-cell rejects", camera_id, variant,
                    rescued)

    result = {
        "camera_id": camera_id, "intersection_id": intersection_id,
        "variant": variant, "window_seconds": window_seconds,
        "corpus_bank_paths": len(bank_res["paths"]),
        "missing_movements": bank_res.get("missing_movements"),
        "replay": stats, "merge": {k: v for k, v in merge.items()
                                   if k != "borderline"},
        "borderline": merge["borderline"], "out_db": str(out_db),
        "applied": False,
        # Evidence-activation decision (None when the flag is off) — the
        # operator-visible record of the blind coverage census + outcome.
        "evidence_activation": activation,
        # Census-ratio demotion record (None when V2_DEMOTION off).
        "demotion": demotion,
    }
    stats_p.write_text(json.dumps({"dump_meta": meta,
                                   "calib_fingerprint": fingerprint,
                                   "schema_fingerprint": schema_fp,
                                   "result": result},
                                  default=str, indent=1))
    if not apply:
        return result
    return _finish_apply(project_id, camera_id, intersection_id,
                         out_db, f_lo, f_hi, fps, result)


def rebuild_s5_union(project_id: str, intersection_id: int,
                     results: list[dict]) -> dict:
    """One flag-queue rebuild carrying the UNION of S5 merge-borderline rows
    across every window a process run applied. A per-window _finish_apply
    rebuild only carries its own window's rows, so a multi-window apply used
    to leave the LAST window's S5 flags only (stage-3.4 dry-run finding).
    Dedup by (camera, cell) keeping the max-|raw−expected| instance; cells
    round-trip through JSON sidecars as lists, so normalize to tuples."""
    best: dict[tuple, dict] = {}
    for res in results:
        cam = res["camera_id"]
        for b in res.get("borderline") or []:
            b = dict(b, cell=tuple(b["cell"]))
            key = (cam, b["cell"])
            if (key not in best or abs(b["raw"] - b["expected"])
                    > abs(best[key]["raw"] - best[key]["expected"])):
                best[key] = b
    by_cam: dict[int, list[dict]] = {}
    for (cam, _), b in best.items():
        by_cam.setdefault(cam, []).append(b)
    extras: list[dict] = []
    conn = get_connection(project_id)
    try:
        for cam, borderline in by_cam.items():
            card = {lid: cd for lid, cd in conn.execute(
                "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id = ?",
                (cam,))}
            extras.extend(s5_flags(cam, borderline, card, bound_approach))
    finally:
        conn.close()
    return rebuild_flags(project_id, intersection_id, extra_flags=extras)


BACKUP_KEEP = 12   # pre-apply project.db copies kept per project (~380 MB
                   # each on the corridor — a full-corridor re-apply is
                   # 9 windows, so 12 keeps a whole campaign + margin while
                   # bounding the directory at ~5 GB; C-stage residual,
                   # closed 2026-07-28)


def _rotate_backups(bdir: Path, keep: int = BACKUP_KEEP) -> None:
    """Delete the oldest pre-apply backups beyond `keep`. Name-sorted =
    time-sorted (timestamp prefix). Deletion failures are non-fatal — a
    locked file just survives one more rotation."""
    try:
        backups = sorted(bdir.glob("*_pre_twopass_cam*.db"))
    except OSError:
        return
    for old in backups[:-keep] if keep > 0 else []:
        try:
            old.unlink()
            logger.info("backup rotation: removed %s", old.name)
        except OSError:
            pass


def _finish_apply(project_id: str, camera_id: int, intersection_id: int,
                  out_db: Path, f_lo: int, f_hi: int, fps: float,
                  result: dict) -> dict:
    """The apply half of pass 2: swap this WINDOW's events into project.db
    (the applied bank stays — it is the operator's attribution authority;
    other windows' events stay), then rebuild the queue with the S5 rows."""
    proj_db = get_db_path(project_id)
    backup = proj_db.parent / "backups" / (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_pre_twopass_cam{camera_id}.db")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(proj_db, backup)
    _rotate_backups(backup.parent)
    _apply_window_events(proj_db, out_db, camera_id, f_lo / fps, f_hi / fps)
    c = sqlite3.connect(proj_db)
    card = {lid: cd for lid, cd in c.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id = ?",
        (camera_id,))}
    c.close()

    # borderline cells round-trip through the stats sidecar as lists
    borderline = [dict(b, cell=tuple(b["cell"])) for b in result["borderline"]]
    extra = s5_flags(camera_id, borderline, card, bound_approach)
    flag_summary = rebuild_flags(project_id, intersection_id, extra_flags=extra)
    result = dict(result)
    result.update({"applied": True, "backup": str(backup), "flags": flag_summary})
    logger.info("two-pass apply cam%s: %s events (applied bank kept), backup %s",
                camera_id, result["replay"]["events"], backup)
    return result
