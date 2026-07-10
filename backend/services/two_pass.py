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

from backend.database import get_connection
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
        out=str(workdir / f"twopass_bank_cam{camera_id}.json"),
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
    out_db = workdir / f"twopass_cam{camera_id}.db"
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

    # --- 4. apply: swap EVENTS into project.db (the applied bank stays — it
    # is the operator's attribution authority), rebuild the queue with S5 ----
    proj_db = Path(f"data/projects/{project_id}/project.db")
    backup = proj_db.parent / "backups" / (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_pre_twopass_cam{camera_id}.db")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(proj_db, backup)
    c = sqlite3.connect(proj_db)
    cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)")
            if r[1] != "event_id"]
    collist = ",".join(cols)
    with c:
        c.execute("ATTACH DATABASE ? AS w", (str(out_db),))
        c.execute("DELETE FROM vehicle_events WHERE camera_id = ?", (camera_id,))
        c.execute(f"INSERT INTO vehicle_events ({collist}) "
                  f"SELECT {collist} FROM w.vehicle_events WHERE camera_id = ?",
                  (camera_id,))
    c.execute("DETACH DATABASE w")
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
