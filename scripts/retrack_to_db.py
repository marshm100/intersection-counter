"""Retrack a window from the detection cache into the REAL project DB with a
chosen tracker backend (no YOLO re-run). Used to regenerate vehicle_events with
OC-SORT so downstream calibration sees the recovered turn trajectories.

DESTRUCTIVE: deletes the camera's events first (back up the DB beforehand).

Usage:
  py scripts/retrack_to_db.py --backend ocsort --start-hms 07:00:00 --minutes 30 --yes
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import get_processing_mode_config
from backend.database import (get_camera_calibration_params,
                              list_paths_for_camera, list_trims)
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path,
)
from backend.services.pipeline import ProcessingPipeline
from reprocess_camera import _load_camera_context


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--mode", default="balanced")
    ap.add_argument("--backend", default="ocsort")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--activation", type=float, default=0.25)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    db = Path("data/projects") / args.project / "project.db"
    conn = sqlite3.connect(str(db))
    ctx = _load_camera_context(conn, args.camera)
    n0 = conn.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (args.camera,)).fetchone()[0]
    conn.close()
    video = ctx["video"]; fps = float(video["fps"]); mode_cfg = get_processing_mode_config(args.mode)
    rec_start = datetime.fromisoformat(video["recording_start_datetime"])
    t0 = datetime.fromisoformat(f"{rec_start.date().isoformat()}T{args.start_hms}")
    s = int((t0 - rec_start).total_seconds() * fps); e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"),
                                          total_frames=video["total_frames"])
    pq = parquet_path(args.project, args.camera, chash, DEFAULT_VARIANT)
    print(f"backend={args.backend} window frames [{s},{e}) cache={pq.name} existing_events={n0}")
    if not args.yes:
        print("DRY RUN — pass --yes to delete events and retrack."); return 0

    conn = sqlite3.connect(str(db)); conn.execute("DELETE FROM vehicle_events WHERE camera_id=?", (args.camera,)); conn.commit(); conn.close()
    pipe = ProcessingPipeline(
        project_id=args.project, db_path=str(db), video_path=video["path"], legs=ctx["legs"],
        fps=fps, video_start_time=video["recording_start_datetime"], video_id=video["video_id"],
        yolo_model=mode_cfg["yolo_model"], yolo_imgsz=mode_cfg["yolo_imgsz"],
        yolo_confidence=mode_cfg["yolo_confidence"], detection_skip=mode_cfg["detection_skip"],
        tracker_match_threshold=mode_cfg.get("tracker_match_threshold"),
        tracker_activation_threshold=args.activation,
        calibration_params=get_camera_calibration_params(args.project, args.camera),
        paths=list_paths_for_camera(args.project, args.camera), tracker_backend=args.backend)
    pipe._v3_camera_id = args.camera
    pipe._v3_trim_id = (list_trims(args.project, ctx["intersection_id"]) or [{"trim_id": None}])[0]["trim_id"]
    pipe.process_cached(DetectionCacheReader(pq), s, e, detection_skip=mode_cfg["detection_skip"])
    conn = sqlite3.connect(str(db)); n1 = conn.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (args.camera,)).fetchone()[0]; conn.close()
    print(f"retracked: {n0} -> {n1} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
