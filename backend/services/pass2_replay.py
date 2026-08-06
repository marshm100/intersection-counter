"""Pass-2 replay: raw-track dump -> vehicle_events through the REAL pipeline
(A stage 2, docs/plan_pass2_replay_A2_2026-07-09.md).

The two-pass architecture's counting step: pass 1 persisted the tracker's raw
output (dump format v2: track_id, frame, cx, cy, bw, bh, conf, class_id); this
service replays those rows through the production classification chain — the
SAME `_process_vehicle` per-frame accumulator (origin-assignment timing, class
at birth, bbox/articulated bookkeeping) and the SAME `_finalize_vehicle_data`
(quality gate, classify, joint scorer, fallbacks, real `_write_vehicle_event`)
— with no detector and no tracker. A camera-window replays in minutes;
calibration edits re-run pass 2 only.

Fidelity contract (the tier-1 parity gate): replay-from-dump must reproduce a
retrack-from-cache with identical inputs to |Δ| ≤ 2 vehicles/cell. Everything
between `tracker.update(...)` and the DB write is either driven directly
(pipeline methods) or replicated verbatim (the grace-window finalize loop
below, mirroring pipeline._process_frame's post-update block). No turn-merge
here — the live tables carry none; the production combine is stage A4.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np

from backend.config import TRACK_FINALIZE_GAP_FRAMES, VEHICLE_CLASSES
from backend.database import (
    get_camera_calibration_params, list_paths_for_camera,
)
from backend.services.detection_cache import (
    compute_video_content_hash, parquet_path,
)
from backend.services.pipeline import ProcessingPipeline


class JobCancelled(Exception):
    """Raised at a cancel checkpoint (plan_C_polish_2026-07-14 §A). Everything
    on disk stays resumable: dumps resume from their high-water/chunk marks,
    working DBs recompute, and applies are never interrupted (the checkpoints
    deliberately exclude _finish_apply)."""


def tracks_dir(pq: Path) -> Path:
    """<variant>.tracks next to the detection parquet (dump_raw_tracks layout)."""
    return pq.with_name(pq.stem + ".tracks")


def load_dump(tdir: Path) -> np.ndarray:
    """Valid dump rows, any format (v1 [N,4] / v2 [N,8]), frame-ordered."""
    n = int((tdir / "count.txt").read_text())
    rows = np.load(tdir / "rows.npy", mmap_mode="r")[:n]
    # dump rows are in tracker-emit order = frame order already; verify cheaply
    frames = rows[:, 1]
    if len(frames) > 1 and not (np.diff(frames) >= 0).all():
        rows = np.asarray(rows)[np.argsort(frames, kind="stable")]
    return rows


def _row_to_tracked(row) -> dict:
    """Rebuild the tracker-output dict `_process_vehicle` consumes from a dump
    row. v1 dumps (4 cols) get neutral bbox/conf/class placeholders — countable
    but not class-faithful; the parity gate runs on v2 dumps only."""
    cx, cy = float(row[2]), float(row[3])
    if len(row) >= 8:
        bw, bh, conf, cid = (float(row[4]), float(row[5]),
                             float(row[6]), int(row[7]))
    else:
        bw, bh, conf, cid = 30.0, 30.0, 0.5, 2
    return {
        "track_id": int(row[0]),
        "bbox": [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2],
        "center": [cx, cy],
        "class_id": cid,
        "class_name": VEHICLE_CLASSES.get(cid, f"class_{cid}"),
        "confidence": conf,
        "is_vehicle": cid in VEHICLE_CLASSES,
        "bbox_width": bw,
        "bbox_height": bh,
        "bbox_area": bw * bh,
    }


def replay_camera(project_id: str, camera_id: int, *, variant: str,
                  out_db: str | Path, start_frame: int | None = None,
                  end_frame: int | None = None, bank: dict | None = None,
                  should_cancel=None, evidence_mode: str | None = None,
                  demoted_cells: set | None = None,
                  demotion_timelocal: dict | None = None) -> dict:
    """Replay a camera's raw-track dump through the production chain into
    `out_db` (a copy of project.db with this camera's events replaced — the
    established retrack working-DB pattern). Returns run stats.

    Uses the camera's LIVE calibration, legs and applied bank as they stand in
    project.db — pass 2 is re-runnable: edit calibration, call again.

    bank: optional {'paths': [...], 'window_seconds': float} (the two-pass
    corpus-built bank). When given, the camera's intersection_paths in OUT_DB
    are replaced with these paths (sample_window_seconds = window_seconds, so
    the turn-merge volume gate is scale-1 by construction) and attribution
    uses them. project.db is never touched."""
    from backend.database import get_db_path
    proj_db = get_db_path(project_id)
    conn = sqlite3.connect(proj_db)
    conn.row_factory = sqlite3.Row
    video = conn.execute(
        "SELECT * FROM videos WHERE camera_id = ? ORDER BY sort_order LIMIT 1",
        (camera_id,)).fetchone()
    legs = [dict(r) for r in conn.execute(
        "SELECT * FROM legs WHERE camera_id = ?", (camera_id,))]
    conn.close()
    if video is None:
        raise ValueError(f"camera {camera_id}: no video row")
    for leg in legs:
        if leg.get("origin_zone"):
            leg["origin_zone"] = json.loads(leg["origin_zone"])

    chash, _ = compute_video_content_hash(
        video["path"], file_size_bytes=video["file_size_bytes"],
        total_frames=video["total_frames"])
    pq = parquet_path(project_id, camera_id, chash, variant)
    tdir = tracks_dir(pq)
    if not tdir.exists():
        raise FileNotFoundError(f"raw-track dump missing: {tdir} — run pass 1 first")
    rows = load_dump(tdir)
    if start_frame is not None or end_frame is not None:
        lo = start_frame if start_frame is not None else -np.inf
        hi = end_frame if end_frame is not None else np.inf
        rows = rows[(rows[:, 1] >= lo) & (rows[:, 1] < hi)]

    out_db = Path(out_db)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(proj_db, out_db)
    c = sqlite3.connect(out_db)
    with c:
        c.execute("DELETE FROM vehicle_events WHERE camera_id = ?", (camera_id,))
        if bank is not None:
            from datetime import datetime
            c.execute("DELETE FROM intersection_paths WHERE camera_id = ?",
                      (camera_id,))
            now = datetime.now().isoformat()
            for p in bank["paths"]:
                if p.get("destination_leg_id") is None:
                    continue
                c.execute(
                    "INSERT INTO intersection_paths (camera_id, origin_leg_id, "
                    "destination_leg_id, polyline, movement_label, supporting_count, "
                    "expected_speed, sample_window_seconds, source, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (camera_id, p["origin_leg_id"], p["destination_leg_id"],
                     json.dumps(p["polyline"]), p["movement_label"],
                     p.get("supporting_count", 0), p.get("expected_speed"),
                     bank.get("window_seconds"), p.get("source", "two-pass-corpus"),
                     now))
    c.close()

    calib = get_camera_calibration_params(project_id, camera_id)
    if bank is not None:
        paths = [p for p in bank["paths"] if p.get("destination_leg_id") is not None]
    else:
        paths = list_paths_for_camera(project_id, camera_id)
    pipe = ProcessingPipeline(
        project_id=project_id, db_path=str(out_db), video_path=video["path"],
        legs=legs, fps=float(video["fps"]),
        video_start_time=video["recording_start_datetime"],
        video_id=video["video_id"], calibration_params=calib, paths=paths,
        # None keeps the legacy module-flag semantics (harness env overrides);
        # the activation precondition passes "probe"/"on" explicitly.
        evidence_mode=evidence_mode)
    pipe._v3_camera_id = camera_id
    pipe._v3_trim_id = None
    if demoted_cells:
        # set -> full demotion (frac 1.0); dict -> per-cell dose fractions
        if isinstance(demoted_cells, dict):
            pipe._demoted_cells = dict(demoted_cells)
        else:
            pipe._demoted_cells = {c: 1.0 for c in demoted_cells}
        if demotion_timelocal:
            pipe._demotion_timelocal = demotion_timelocal
    if bank is not None:
        # Injected candidates must not perturb the origin-evidence gate
        # geometry — gates stay pinned to the camera's DB-applied paths.
        pipe._gate_paths = list_paths_for_camera(project_id, camera_id)

    # --- the post-tracker per-frame loop, replicated verbatim ---------------
    # (pipeline._process_frame after tracker.update: vehicle accumulation +
    # the grace-window finalize. NMS/buffering/stitch are PRE-dump concerns —
    # the dump already IS the tracker output.) The grace clock ticks on EVERY
    # frame of the window, including empty ones — live finalizes a vanished
    # track mid-gap, and a reused track_id must split identically here.
    n_rows = 0
    n = len(rows)
    i = 0
    f_first = int(rows[0, 1]) if n else 0
    f_last = int(rows[n - 1, 1]) if n else -1
    for frame in range(f_first, f_last + 1):
        if should_cancel is not None and should_cancel():
            raise JobCancelled(f"replay cancelled at frame {frame} "
                               f"(cam {camera_id} {variant})")
        seen_ids: set[int] = set()
        while i < n and int(rows[i, 1]) == frame:
            t = _row_to_tracked(rows[i])
            seen_ids.add(t["track_id"])
            if t["is_vehicle"]:
                pipe._process_vehicle(t["track_id"], t, frame)
            i += 1
            n_rows += 1
        for track_id in list(pipe.active_vehicles.keys()):
            if track_id in seen_ids:
                pipe.active_vehicles[track_id]["last_seen_frame"] = frame
                continue
            last = pipe.active_vehicles[track_id].get("last_seen_frame")
            if last is None:
                pipe.active_vehicles[track_id]["last_seen_frame"] = frame
                continue
            if frame - last > TRACK_FINALIZE_GAP_FRAMES:
                pipe._finalize_vehicle(track_id, frame)
    if n:
        pipe._finalize_all_active(f_last + 1)

    c = sqlite3.connect(out_db)
    n_events = c.execute(
        "SELECT COUNT(*) FROM vehicle_events WHERE camera_id = ? AND rejected = 0",
        (camera_id,)).fetchone()[0]
    c.close()
    return {
        "camera_id": camera_id, "variant": variant, "rows": n_rows,
        "tracks": int(pipe.n_tracks_total), "events": int(n_events),
        "insufficient_data": int(pipe.n_insufficient_data),
        "quality_filtered": int(getattr(pipe, "n_quality_filtered", 0)),
        "origin_evidenced": int(getattr(pipe, "n_origin_evidenced", 0)),
        "origin_unevidenced": int(getattr(pipe, "n_origin_unevidenced", 0)),
        "origin_corrected": int(getattr(pipe, "n_origin_corrected", 0)),
        # Claim-time veto (origin-grab phase 1): tracks with >=1 vetoed leg.
        "origin_vetoed": int(getattr(pipe, "n_origin_vetoed", 0)),
        # PHASE 3 (rescue half): origin-less vetoed tracks that claimed the
        # through-road their birth sits on; and joint-scorer origin rewrites
        # blocked from re-stealing to a vetoed leg. Bookkeeping for the re-gate.
        "origin_rescued": int(getattr(pipe, "n_origin_rescued", 0)),
        "origin_rewrite_vetoed": int(getattr(pipe, "n_origin_rewrite_vetoed", 0)),
        # Posterior-half counters (plan_posterior_half_2026-07-15 stage-4
        # instrumentation: branch applications + flag-bound origin near-ties).
        "posterior_origin": int(getattr(pipe, "n_posterior_origin", 0)),
        "posterior_dest": int(getattr(pipe, "n_posterior_dest", 0)),
        "posterior_rescued": int(getattr(pipe, "n_posterior_rescued", 0)),
        "origin_ambiguous": int(getattr(pipe, "n_origin_ambiguous", 0)),
        "posterior_vetoed": int(getattr(pipe, "n_posterior_vetoed", 0)),
        "out_db": str(out_db),
    }
