"""Decisive test: does the data-driven recal fix ATTRIBUTION on the fresh
(truncated) cached data — without touching the real DB?

The recal only changes legs.reference_heading + the path bank; its effect on
movement attribution materialises only when events are RE-ATTRIBUTED. So we:
  1. copy the project DB to a temp,
  2. apply the recal suggestion to the temp (heading-only legs + replace paths),
  3. RETRACK from the detection cache into the temp (re-attributes via the new
     calibration — polyline-first origin, tail-derived heading),
  4. compute the per-movement aggregate error on the temp,
and print BEFORE (current real DB) vs AFTER (recal'd temp).

This isolates the recal's attribution win from the (separate, recall-bound)
trajectory-truncation issue. Real DB untouched.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import groundtruth
from backend.config import get_processing_mode_config
from backend.database import get_calibration_params, list_paths_for_camera, list_trims
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path,
)
from backend.services.pipeline import ProcessingPipeline
from reprocess_camera import _load_camera_context
import per_movement_accuracy as pma


def _agg_err(db_path: Path, report: bool = False) -> tuple[float, int, int]:
    orig = groundtruth.PROJECT_DB
    groundtruth.PROJECT_DB = db_path
    pma.db_processed_window = groundtruth.db_processed_window
    pma.fetch_our_counts = groundtruth.fetch_our_counts
    try:
        manual = groundtruth.parse_manual_csv()
        processed = groundtruth.db_processed_window()
        agg = pma.aggregate_full_sweep(manual, processed)
        cells = pma.build_cells(agg)
        metric = pma.compute_metric(cells)
        if report:
            for c in sorted(cells, key=lambda c: -c["abs_delta"])[:6]:
                print(f"    L{c['leg_id']} {c['approach'][:18]:<18} {c['movement']:<6} "
                      f"manual={c['manual']:>6.1f} ours={c['ours']:>4} |D|={c['abs_delta']:>5.1f}")
        return metric["agg_err_pct"], metric["total_manual"], metric["total_ours"]
    finally:
        groundtruth.PROJECT_DB = orig


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--mode", default="balanced")
    ap.add_argument("--suggestion", default="evaluations/recal_cam1.json")
    ap.add_argument("--start-hms", default="07:00:05")
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument("--activation", type=float, default=0.25)
    ap.add_argument("--tracker-backend", default="bytetrack", help="bytetrack | ocsort")
    args = ap.parse_args()

    db_path = Path("data/projects") / args.project / "project.db"
    before_err, tm, to = _agg_err(db_path)
    print(f"BEFORE (current DB, old calibration): agg_err={before_err:.1f}%  "
          f"manual={tm:.0f} ours={to}")

    conn = sqlite3.connect(str(db_path))
    ctx = _load_camera_context(conn, args.camera)
    conn.close()
    video, legs = ctx["video"], ctx["legs"]
    fps = float(video["fps"])
    calib = get_calibration_params(args.project, ctx["intersection_id"])
    mode_cfg = get_processing_mode_config(args.mode)
    sug = json.loads(Path(args.suggestion).read_text())

    rec_start = datetime.fromisoformat(video["recording_start_datetime"])
    date = rec_start.date().isoformat()
    t0 = datetime.fromisoformat(f"{date}T{args.start_hms}")
    s = int((t0 - rec_start).total_seconds() * fps)
    e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))

    chash, _ = compute_video_content_hash(
        video["path"], file_size_bytes=video.get("file_size_bytes"),
        total_frames=video["total_frames"])
    pq = parquet_path(args.project, args.camera, chash, DEFAULT_VARIANT)
    if not pq.exists():
        raise SystemExit(f"No cache at {pq}; run reprocess_camera.py first.")

    tmpdir = Path(tempfile.mkdtemp(prefix="recal_effect_"))
    try:
        tdb = tmpdir / "recal.db"
        shutil.copy2(db_path, tdb)
        c = sqlite3.connect(str(tdb))
        with c:
            # apply recal: heading-only legs (keep origins) + replace path bank
            for ul in sug.get("updated_legs", []):
                if "origin_point" in ul:
                    c.execute("UPDATE legs SET origin_zone=?, reference_heading=? WHERE leg_id=? AND camera_id=?",
                              (json.dumps([list(ul["origin_point"])]), ul["reference_heading"], ul["leg_id"], args.camera))
                else:
                    c.execute("UPDATE legs SET reference_heading=? WHERE leg_id=? AND camera_id=?",
                              (ul["reference_heading"], ul["leg_id"], args.camera))
            c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (args.camera,))
            now = datetime.now().isoformat()
            for p in sug.get("paths", []):
                if p.get("destination_leg_id") is None:
                    continue
                c.execute("INSERT INTO intersection_paths (camera_id, origin_leg_id, destination_leg_id, polyline, movement_label, supporting_count, source, created_at) "
                          "VALUES (?,?,?,?,?,?, 'data-driven', ?)",
                          (args.camera, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]), p["movement_label"], p.get("supporting_count", 0), now))
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (args.camera,))
        c.close()

        # reload recal'd legs/paths and retrack from cache into temp
        c = sqlite3.connect(str(tdb))
        rctx = _load_camera_context(c, args.camera)
        c.close()
        paths = list_paths_for_camera_tmp(tdb, args.camera)
        pipe = ProcessingPipeline(
            project_id=args.project, db_path=str(tdb), video_path=video["path"],
            legs=rctx["legs"], fps=fps, video_start_time=video["recording_start_datetime"],
            video_id=video["video_id"], yolo_model=mode_cfg["yolo_model"],
            yolo_imgsz=mode_cfg["yolo_imgsz"], yolo_confidence=mode_cfg["yolo_confidence"],
            detection_skip=mode_cfg["detection_skip"],
            tracker_match_threshold=mode_cfg.get("tracker_match_threshold"),
            tracker_activation_threshold=args.activation, calibration_params=calib, paths=paths,
            tracker_backend=args.tracker_backend)
        pipe._v3_camera_id = args.camera
        pipe._v3_trim_id = (list_trims(args.project, ctx["intersection_id"]) or [{"trim_id": None}])[0]["trim_id"]
        reader = DetectionCacheReader(pq)
        pipe.process_cached(reader, s, e, detection_skip=mode_cfg["detection_skip"])

        print("AFTER  (recal heading+paths, retracked) — top residual cells:")
        after_err, tm2, to2 = _agg_err(tdb, report=True)
        print(f"  agg_err={after_err:.1f}%  manual={tm2:.0f} ours={to2}")
        print(f"\nagg_err {before_err:.1f}% -> {after_err:.1f}%  "
              f"({'IMPROVED' if after_err < before_err else 'no improvement'})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


def list_paths_for_camera_tmp(db_path: Path, camera_id: int) -> list[dict]:
    c = sqlite3.connect(str(db_path)); c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM intersection_paths WHERE camera_id=?", (camera_id,)).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        d["polyline"] = json.loads(d["polyline"]) if isinstance(d["polyline"], str) else d["polyline"]
        out.append(d)
    return out


if __name__ == "__main__":
    sys.exit(main())
