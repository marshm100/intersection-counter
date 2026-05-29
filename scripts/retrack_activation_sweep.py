"""A/B the ByteTrack activation_threshold by retracking from the detection cache.

The detection cache stores the raw YOLO boxes (conf floor only); track birth is
gated by ByteTrack's track_thresh (= tracker_activation_threshold). So we can
sweep activation values WITHOUT re-running YOLO: retrack the same cache at each
threshold and measure whether entry-side detections now get captured (median
start_x moves toward the entry edge) and whether the overcount/fragmentation
drops. See docs/recalibration_plan_2026-05-27.md + the detection-birth-gate
diagnosis (2026-05-28).

Each variant retracks into a THROWAWAY copy of the project DB, so the real DB is
never churned. Window must match the cache's reprocess window.

Usage:
  py scripts/retrack_activation_sweep.py --start-hms 07:00:05 --minutes 3 \
      --activations 0.25,0.20,0.18,0.15
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import get_processing_mode_config
from backend.database import get_calibration_params, list_paths_for_camera, list_trims
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path,
)
from backend.services.pipeline import ProcessingPipeline
from reprocess_camera import _load_camera_context
from replay_attribution_changes import load_events
from groundtruth import parse_manual_csv  # noqa: F401  (kept for parity)


def _metrics(db_path: Path, camera_id: int) -> dict:
    conn = sqlite3.connect(str(db_path))
    ev = load_events(conn)
    conn.close()
    trajs = [e["trajectory"] for e in ev if e["trajectory"] and len(e["trajectory"]) >= 4]
    n = len(trajs)
    if n == 0:
        return {"n": 0}
    sx = np.array([t[0][0] for t in trajs]); ex = np.array([t[-1][0] for t in trajs])
    npts = np.array([len(t) for t in trajs])
    eb = (ex - sx) > 100   # eastbound through (enters LEFT, x~0)
    wb = (sx - ex) > 100   # westbound through (enters RIGHT, x~640)
    out = {"n": n, "short_pct": round(float(np.mean(npts < 15)) * 100, 0)}
    if eb.any():
        out["EB_n"] = int(eb.sum())
        out["EB_start_med"] = round(float(np.median(sx[eb])), 0)
        out["EB_edge_pct"] = round(float(np.mean(sx[eb] < 60)) * 100, 0)
    if wb.any():
        out["WB_n"] = int(wb.sum())
        out["WB_start_med"] = round(float(np.median(sx[wb])), 0)
        out["WB_edge_pct"] = round(float(np.mean(sx[wb] > 580)) * 100, 0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--mode", default="balanced")
    ap.add_argument("--start-hms", default="07:00:05")
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument("--activations", default="0.25,0.20,0.18,0.15")
    args = ap.parse_args()

    acts = [float(x) for x in args.activations.split(",")]
    db_path = Path("data/projects") / args.project / "project.db"
    conn = sqlite3.connect(str(db_path))
    ctx = _load_camera_context(conn, args.camera)
    conn.close()
    video, legs = ctx["video"], ctx["legs"]
    fps = float(video["fps"])
    paths = list_paths_for_camera(args.project, args.camera)
    calib = get_calibration_params(args.project, ctx["intersection_id"])
    mode_cfg = get_processing_mode_config(args.mode)

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
        raise SystemExit(f"No detection cache at {pq}. Run reprocess_camera.py first.")
    print(f"cache: {pq}  frames [{s}, {e})  mode={args.mode} "
          f"(model={mode_cfg['yolo_model']} imgsz={mode_cfg['yolo_imgsz']} conf={mode_cfg['yolo_confidence']})")
    print(f"sweeping activation_threshold: {acts}\n")
    print(f"{'act':>5} {'n':>4} {'short%':>6}  {'EB_n':>4} {'EB_start':>8} {'EB_edge%':>8}  "
          f"{'WB_n':>4} {'WB_start':>8} {'WB_edge%':>8}")

    tmpdir = Path(tempfile.mkdtemp(prefix="retrack_sweep_"))
    try:
        for act in acts:
            tdb = tmpdir / f"act_{act}.db"
            shutil.copy2(db_path, tdb)
            c = sqlite3.connect(str(tdb))
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (args.camera,))
            c.commit(); c.close()
            pipe = ProcessingPipeline(
                project_id=args.project, db_path=str(tdb), video_path=video["path"],
                legs=legs, fps=fps, video_start_time=video["recording_start_datetime"],
                video_id=video["video_id"], yolo_model=mode_cfg["yolo_model"],
                yolo_imgsz=mode_cfg["yolo_imgsz"], yolo_confidence=mode_cfg["yolo_confidence"],
                detection_skip=mode_cfg["detection_skip"],
                tracker_match_threshold=mode_cfg.get("tracker_match_threshold"),
                tracker_activation_threshold=act, calibration_params=calib, paths=paths)
            pipe._v3_camera_id = args.camera
            pipe._v3_trim_id = (list_trims(args.project, ctx["intersection_id"]) or [{"trim_id": None}])[0]["trim_id"]
            reader = DetectionCacheReader(pq)
            pipe.process_cached(reader, s, e, detection_skip=mode_cfg["detection_skip"])
            m = _metrics(tdb, args.camera)
            print(f"{act:>5} {m.get('n',0):>4} {m.get('short_pct',0):>6}  "
                  f"{m.get('EB_n',0):>4} {m.get('EB_start_med','-'):>8} {m.get('EB_edge_pct','-'):>8}  "
                  f"{m.get('WB_n',0):>4} {m.get('WB_start_med','-'):>8} {m.get('WB_edge_pct','-'):>8}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    print("\nGoal: lower activation should pull EB_start toward ~0 and EB_edge% up "
          "(entries captured), ideally without inflating n (fragmentation).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
