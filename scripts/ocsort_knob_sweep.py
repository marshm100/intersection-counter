"""Sweep OC-SORT association knobs to fix the SB-through overcount WITHOUT
regressing turn recovery. Retracks the 30-min cache into a temp DB per config
(no YOLO), applies the turn-inclusive bank, and reports agg_err + the cells that
matter: SB-through (must fall toward manual 424), NB-through, and NB-left (the
recovered turn — must stay ~109, else the fix broke turn capture).

Root cause (scripts/diagnose_sb_*.py): OC-SORT produces ~+114 excess SB-through
track-IDs (ID-switches on the dense westbound queue, amplified by use_byte's
low-conf second association). use_byte=False / higher det_thresh / higher inertia
should cut the switches. This sweep turns that hypothesis into numbers.

Usage:  py scripts/ocsort_knob_sweep.py --minutes 30
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
from backend.database import get_calibration_params, list_trims
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path,
)
from backend.services.pipeline import ProcessingPipeline
from reprocess_camera import _load_camera_context
import per_movement_accuracy as pma
from test_recal_effect import list_paths_for_camera_tmp

# (leg_id, movement) cells to surface per run.
WATCH = [(22, "thru"), (23, "thru"), (23, "left"), (22, "left"), (23, "right")]

CONFIGS = [
    ("baseline (use_byte=T,det=.25)", {}),
    ("use_byte=F + det=0.35",        {"use_byte": False, "det_thresh": 0.35}),
    ("use_byte=F + det=0.30",        {"use_byte": False, "det_thresh": 0.30}),
    ("use_byte=F + det=0.40",        {"use_byte": False, "det_thresh": 0.40}),
]


def measure(db_path, video, legs_ctx, calib, mode_cfg, sug, s, e, pq, camera, kwargs):
    tmpdir = Path(tempfile.mkdtemp(prefix="ocsweep_"))
    try:
        tdb = tmpdir / "recal.db"
        shutil.copy2(db_path, tdb)
        c = sqlite3.connect(str(tdb))
        with c:
            for ul in sug.get("updated_legs", []):
                c.execute("UPDATE legs SET reference_heading=? WHERE leg_id=? AND camera_id=?",
                          (ul["reference_heading"], ul["leg_id"], camera))
            c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (camera,))
            now = datetime.now().isoformat()
            for p in sug.get("paths", []):
                if p.get("destination_leg_id") is None:
                    continue
                c.execute("INSERT INTO intersection_paths (camera_id, origin_leg_id, destination_leg_id, polyline, movement_label, supporting_count, source, created_at) "
                          "VALUES (?,?,?,?,?,?, 'data-driven', ?)",
                          (camera, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                           p["movement_label"], p.get("supporting_count", 0), now))
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (camera,))
        c.close()
        c = sqlite3.connect(str(tdb)); rctx = _load_camera_context(c, camera); c.close()
        paths = list_paths_for_camera_tmp(tdb, camera)
        pipe = ProcessingPipeline(
            project_id="97a7849a", db_path=str(tdb), video_path=video["path"],
            legs=rctx["legs"], fps=float(video["fps"]), video_start_time=video["recording_start_datetime"],
            video_id=video["video_id"], yolo_model=mode_cfg["yolo_model"],
            yolo_imgsz=mode_cfg["yolo_imgsz"], yolo_confidence=mode_cfg["yolo_confidence"],
            detection_skip=mode_cfg["detection_skip"],
            tracker_match_threshold=mode_cfg.get("tracker_match_threshold"),
            tracker_activation_threshold=0.25, calibration_params=calib, paths=paths,
            tracker_backend="ocsort", tracker_kwargs=kwargs)
        pipe._v3_camera_id = camera
        pipe._v3_trim_id = (list_trims("97a7849a", legs_ctx["intersection_id"]) or [{"trim_id": None}])[0]["trim_id"]
        pipe.process_cached(DetectionCacheReader(pq), s, e, detection_skip=mode_cfg["detection_skip"])

        orig = groundtruth.PROJECT_DB
        groundtruth.PROJECT_DB = tdb
        pma.db_processed_window = groundtruth.db_processed_window
        pma.fetch_our_counts = groundtruth.fetch_our_counts
        try:
            manual = groundtruth.parse_manual_csv()
            agg = pma.aggregate_full_sweep(manual, groundtruth.db_processed_window())
            cells = pma.build_cells(agg)
            metric = pma.compute_metric(cells)
            cellmap = {(c["leg_id"], c["movement"]): c for c in cells}
            return metric["agg_err_pct"], metric["total_ours"], cellmap
        finally:
            groundtruth.PROJECT_DB = orig
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--suggestion", default="evaluations/recal_cam1_nbleftonly.json")
    args = ap.parse_args()
    camera = 1
    db_path = Path("data/projects/97a7849a/project.db")
    conn = sqlite3.connect(str(db_path)); ctx = _load_camera_context(conn, camera); conn.close()
    video = ctx["video"]; fps = float(video["fps"])
    calib = get_calibration_params("97a7849a", ctx["intersection_id"])
    mode_cfg = get_processing_mode_config("balanced")
    sug = json.loads(Path(args.suggestion).read_text())
    rec_start = datetime.fromisoformat(video["recording_start_datetime"])
    t0 = datetime.fromisoformat(f"{rec_start.date().isoformat()}T{args.start_hms}")
    s = int((t0 - rec_start).total_seconds() * fps); e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"),
                                          total_frames=video["total_frames"])
    pq = parquet_path("97a7849a", camera, chash, DEFAULT_VARIANT)

    print(f"window {args.start_hms}+{args.minutes}min  cache={pq.name}\n")
    hdr = f"{'config':<32} {'agg_err':>8} {'total':>6}  " + "  ".join(f"L{l}{m[:3]:<3}" for l, m in WATCH)
    print(hdr); print("-" * len(hdr))
    for label, kw in CONFIGS:
        agg, total, cm = measure(db_path, video, ctx, calib, mode_cfg, sug, s, e, pq, camera, kw)
        cellvals = "  ".join(f"{cm.get(c, {}).get('ours', 0):>6}" for c in WATCH)
        print(f"{label:<32} {agg:>7.1f}% {total:>6}  {cellvals}")
    man = "  ".join(f"{cm.get(c, {}).get('manual', 0):>6.0f}" for c in WATCH)
    print(f"{'(manual)':<32} {'':>8} {1211:>6}  {man}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
