"""Diagnose WHERE turn attribution breaks (origin vs destination vs label).

Retracks the recal'd calibration into a temp DB (same as test_recal_effect),
then for every regenerated event computes the GEOMETRIC movement from entry vs
exit heading and cross-tabs it against the pipeline's ASSIGNED (origin_leg,
movement). The confusion tells us if turners get the wrong origin leg, the wrong
destination/label, or aren't recognised as turns at all. Real DB untouched.

Usage:
  py scripts/diag_turn_attribution.py --suggestion evaluations/recal_cam1_30min.json \
      --start-hms 07:00:00 --minutes 30
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import get_processing_mode_config
from backend.database import get_calibration_params, list_trims
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path,
)
from backend.services.pipeline import ProcessingPipeline
from backend.services.trajectory_classifier import _exit_velocity
from reprocess_camera import _load_camera_context
from test_recal_effect import list_paths_for_camera_tmp

# Image-frame cardinal directions for this camera (arterial E/W from the recal
# axis ~83/262; cross-street N/S perpendicular). Sectors are nearest-of-four.
DIRS = {"E": 83.0, "W": 262.0, "N": 353.0, "S": 173.0}
LEG_NAME = {22: "SB(L22)", 23: "NB(L23)", 24: "WBdrv(L24)", 25: "EBnw(L25)"}


def _heading(p, q):
    return math.degrees(math.atan2(q[0] - p[0], -(q[1] - p[1]))) % 360


def _entry_heading(traj, min_dist=30.0):
    p0 = traj[0]
    for q in traj[1:]:
        if math.hypot(q[0] - p0[0], q[1] - p0[1]) >= min_dist:
            return _heading(p0, q)
    return _heading(traj[0], traj[-1])


def _sector(deg):
    return min(DIRS, key=lambda k: abs((deg - DIRS[k] + 180) % 360 - 180))


def _retrack_recal(args) -> Path:
    db_path = Path("data/projects") / args.project / "project.db"
    conn = sqlite3.connect(str(db_path)); ctx = _load_camera_context(conn, args.camera); conn.close()
    video, fps = ctx["video"], float(ctx["video"]["fps"])
    calib = get_calibration_params(args.project, ctx["intersection_id"])
    mode_cfg = get_processing_mode_config(args.mode)
    sug = json.loads(Path(args.suggestion).read_text())
    rec_start = datetime.fromisoformat(video["recording_start_datetime"])
    t0 = datetime.fromisoformat(f"{rec_start.date().isoformat()}T{args.start_hms}")
    s = int((t0 - rec_start).total_seconds() * fps); e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"),
                                          total_frames=video["total_frames"])
    pq = parquet_path(args.project, args.camera, chash, DEFAULT_VARIANT)

    tdb = Path(tempfile.mkdtemp(prefix="diag_turn_")) / "recal.db"
    shutil.copy2(db_path, tdb)
    c = sqlite3.connect(str(tdb))
    with c:
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
    rctx = _load_camera_context(c, args.camera); c.close()
    paths = list_paths_for_camera_tmp(tdb, args.camera)
    pipe = ProcessingPipeline(
        project_id=args.project, db_path=str(tdb), video_path=video["path"], legs=rctx["legs"],
        fps=fps, video_start_time=video["recording_start_datetime"], video_id=video["video_id"],
        yolo_model=mode_cfg["yolo_model"], yolo_imgsz=mode_cfg["yolo_imgsz"],
        yolo_confidence=mode_cfg["yolo_confidence"], detection_skip=mode_cfg["detection_skip"],
        tracker_match_threshold=mode_cfg.get("tracker_match_threshold"),
        tracker_activation_threshold=args.activation, calibration_params=calib, paths=paths)
    pipe._v3_camera_id = args.camera
    pipe._v3_trim_id = (list_trims(args.project, ctx["intersection_id"]) or [{"trim_id": None}])[0]["trim_id"]
    pipe.process_cached(DetectionCacheReader(pq), s, e, detection_skip=mode_cfg["detection_skip"])
    return tdb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--mode", default="balanced")
    ap.add_argument("--suggestion", default="evaluations/recal_cam1_30min.json")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--activation", type=float, default=0.25)
    args = ap.parse_args()

    tdb = _retrack_recal(args)
    try:
        c = sqlite3.connect(str(tdb))
        rows = c.execute(
            "SELECT origin_leg_id, destination_leg_id, movement, trajectory_data "
            "FROM vehicle_events WHERE camera_id=?", (args.camera,)).fetchall()
        c.close()
        events = []
        for olid, dlid, mv, tj in rows:
            traj = json.loads(tj) if isinstance(tj, str) else tj
            if not traj or len(traj) < 4:
                continue
            eh = _entry_heading(traj); xh = _heading_of_exit(traj)
            events.append({"o": olid, "d": dlid, "mv": mv,
                           "entry": _sector(eh), "exit": _sector(xh),
                           "net": (xh - eh + 180) % 360 - 180})
        print(f"recal'd events: {len(events)}\n")

        # 1) Geometric movement (entry sector -> exit sector) distribution
        print("=== GEOMETRIC entry->exit (from trajectory shape) ===")
        geo = Counter((ev["entry"], ev["exit"]) for ev in events)
        for (en, ex), n in geo.most_common(10):
            kind = "THROUGH" if en == ex else "turn"
            print(f"  {en}->{ex:<2} n={n:<4} {kind}")

        # 2) Assigned (origin leg, movement) distribution
        print("\n=== ASSIGNED (origin_leg, movement) ===")
        asg = Counter((ev["o"], ev["mv"]) for ev in events)
        for (o, mv), n in asg.most_common(12):
            print(f"  {LEG_NAME.get(o, o):<10} {mv:<6} n={n}")

        # 3) Confusion: for each geometric turn class, what label did it get?
        print("\n=== CONFUSION: geometric turners (entry!=exit) -> assigned (origin, movement) ===")
        turners = [ev for ev in events if ev["entry"] != ev["exit"]]
        print(f"  geometric turners: {len(turners)}")
        conf = Counter((f"{ev['entry']}->{ev['exit']}", LEG_NAME.get(ev["o"], ev["o"]), ev["mv"]) for ev in turners)
        for (geom, o, mv), n in conf.most_common(15):
            print(f"  geom {geom:<6} -> {o:<10} {mv:<6}  n={n}")

        # 4) Where did NB(E)->N (NB-left) vehicles go?
        print("\n=== NB-left candidates (entry E, exit N) — assigned breakdown ===")
        nbl = [ev for ev in events if ev["entry"] == "E" and ev["exit"] == "N"]
        print(f"  count: {len(nbl)}")
        for (o, mv), n in Counter((LEG_NAME.get(ev["o"], ev["o"]), ev["mv"]) for ev in nbl).most_common():
            print(f"    {o:<10} {mv:<6} n={n}")
    finally:
        shutil.rmtree(tdb.parent, ignore_errors=True)
    return 0


def _heading_of_exit(traj):
    vx, vy = _exit_velocity(traj)
    return math.degrees(math.atan2(vx, -vy)) % 360


if __name__ == "__main__":
    sys.exit(main())
