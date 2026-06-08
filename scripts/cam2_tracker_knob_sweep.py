"""Sweep cam2 ByteTrack association knobs to cut the through-DUPLICATION without
regressing the recovered turns — the remaining cam2 lever after NMS@0.85.

cam2's residual error is multi-mechanism through-duplication (one vehicle counted
twice). NMS@0.85 collapses the cross-class DOUBLE-BOX half; the other half is
ID-SWITCH duplication on the dense 25fps queues (a track is lost mid-frame then
re-acquired under a fresh ID). The tracker knobs that govern that are track_buffer
(how long a lost track survives before it's dropped) and match_thresh (how
readily a detection re-associates to an existing track). This sweep retracks the
cam2 detection cache (NO YOLO) per knob combo, ON TOP of the now-persisted
NMS@0.85, and reports net error + the cells that matter.

The knobs are injected through calibration_params (the per-camera path wired in
2026-06-08) — no project.db mutation, no backend_kwargs collision.

WATCH cells (cam2 leg map {26:WB, 27:SB, 28:EB, 29:NB}):
  L29thr=NB-thru, L27thr=SB-thru   -> the duplicated throughs (must fall)
  L28thr=EB-thru, L26lef=WB-left   -> build_bank-recovered movements (must hold)

Usage:  py scripts/cam2_tracker_knob_sweep.py --minutes 30
        py scripts/cam2_tracker_knob_sweep.py --minutes 2   # quick smoke
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import get_processing_mode_config
from backend.database import get_camera_calibration_params, list_trims
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path,
)
from backend.services.pipeline import ProcessingPipeline
from reprocess_camera import _load_camera_context
from test_recal_effect import list_paths_for_camera_tmp

PROJECT = "97a7849a"
CAMERA = 2
PY = sys.executable
# Through movements the knobs target (cam2 25fps duplication). Scored by the
# camera-correct od_accuracy (manual NB-thru=626, SB-thru=310 over 30min@07:00).
WATCH_THRU = ["SB thru", "NB thru"]

# (label, track_buffer, match_thresh). Baseline is the ByteTrack default
# (buf=150, match=0.8). To cut ID-switch duplication: sustain tracks through gaps
# (higher buffer) and/or re-associate more readily (lower match_thresh). The
# sweep turns that hypothesis into numbers — measurement picks the winner.
# 2-min probe showed loosening match HURTS (over-merges distinct vehicles) and
# higher buffer alone does nothing — so bracket the baseline cleanly on both
# knobs over the full 30-min window to map the response surface / confirm best.
CONFIGS = [
    ("baseline buf150 m0.80", 150, 0.80),
    ("buf90 m0.80",            90, 0.80),
    ("buf300 m0.80",          300, 0.80),
    ("buf150 m0.90",          150, 0.90),
    ("buf150 m0.70",          150, 0.70),
]


_NET_RE = re.compile(r"net agg_err\s*=\s*([\d.]+)%")


def _score(tdb, start_hms, minutes):
    """Score a retracked temp DB with the camera-correct measurement. Returns
    (net_pct, {cell: (manual, ours)}) parsed from od_accuracy --camera 2."""
    out = subprocess.run(
        [PY, "scripts/od_accuracy.py", "--camera", str(CAMERA), "--db", str(tdb),
         "--start-hms", start_hms, "--minutes", str(minutes)],
        capture_output=True, text=True).stdout
    m = _NET_RE.search(out)
    net = float(m.group(1)) if m else float("nan")
    cells = {}
    for name in WATCH_THRU:
        cm = re.search(rf"^\s*{re.escape(name)}\s+(\d+)\s+(\d+)", out, re.M)
        if cm:
            cells[name] = (int(cm.group(1)), int(cm.group(2)))
    return net, cells


def measure(db_path, video, legs_ctx, base_calib, mode_cfg, sug, s, e, pq,
            buf, match, start_hms, minutes):
    tmpdir = Path(tempfile.mkdtemp(prefix="cam2sweep_"))
    try:
        tdb = tmpdir / "recal.db"
        shutil.copy2(db_path, tdb)
        c = sqlite3.connect(str(tdb))
        with c:
            for ul in sug.get("updated_legs", []):
                c.execute("UPDATE legs SET reference_heading=? WHERE leg_id=? AND camera_id=?",
                          (ul["reference_heading"], ul["leg_id"], CAMERA))
            c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (CAMERA,))
            now = datetime.now().isoformat()
            for p in sug.get("paths", []):
                if p.get("destination_leg_id") is None:
                    continue
                c.execute("INSERT INTO intersection_paths (camera_id, origin_leg_id, destination_leg_id, polyline, movement_label, supporting_count, source, created_at) "
                          "VALUES (?,?,?,?,?,?, 'data-driven', ?)",
                          (CAMERA, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                           p["movement_label"], p.get("supporting_count", 0), now))
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (CAMERA,))
        c.close()
        c = sqlite3.connect(str(tdb)); rctx = _load_camera_context(c, CAMERA); c.close()
        paths = list_paths_for_camera_tmp(tdb, CAMERA)
        # Inject the swept knobs through calibration_params (keeps NMS@0.85 from
        # base_calib). Explicit match/activation left None so calib drives them.
        calib = {**base_calib, "tracker_lost_buffer": buf, "tracker_match_threshold": match}
        pipe = ProcessingPipeline(
            project_id=PROJECT, db_path=str(tdb), video_path=video["path"],
            legs=rctx["legs"], fps=float(video["fps"]), video_start_time=video["recording_start_datetime"],
            video_id=video["video_id"], yolo_model=mode_cfg["yolo_model"],
            yolo_imgsz=mode_cfg["yolo_imgsz"], yolo_confidence=mode_cfg["yolo_confidence"],
            detection_skip=mode_cfg["detection_skip"],
            calibration_params=calib, paths=paths, tracker_backend="bytetrack")
        pipe._v3_camera_id = CAMERA
        pipe._v3_trim_id = (list_trims(PROJECT, legs_ctx["intersection_id"]) or [{"trim_id": None}])[0]["trim_id"]
        pipe.process_cached(DetectionCacheReader(pq), s, e, detection_skip=mode_cfg["detection_skip"])
        return _score(tdb, start_hms, minutes)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--suggestion", default="evaluations/recal_cam2_30min.json")
    args = ap.parse_args()
    db_path = Path(f"data/projects/{PROJECT}/project.db")
    conn = sqlite3.connect(str(db_path)); ctx = _load_camera_context(conn, CAMERA); conn.close()
    video = ctx["video"]; fps = float(video["fps"])
    base_calib = get_camera_calibration_params(PROJECT, CAMERA)
    mode_cfg = get_processing_mode_config("balanced")
    sug = json.loads(Path(args.suggestion).read_text())
    rec_start = datetime.fromisoformat(video["recording_start_datetime"])
    t0 = datetime.fromisoformat(f"{rec_start.date().isoformat()}T{args.start_hms}")
    s = int((t0 - rec_start).total_seconds() * fps); e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"),
                                          total_frames=video["total_frames"])
    pq = parquet_path(PROJECT, CAMERA, chash, DEFAULT_VARIANT)

    print(f"cam2 ByteTrack knob sweep  window {args.start_hms}+{args.minutes}min  "
          f"NMS={base_calib['pre_track_nms_iou']}  cache={pq.name}")
    print("(scored by od_accuracy --camera 2; SB/NB-thru 'ours' should approach manual)\n")
    hdr = f"{'config':<24} {'net':>7}  " + "  ".join(f"{n:>9}" for n in WATCH_THRU)
    print(hdr); print("-" * len(hdr))
    cells_last = {}
    for label, buf, match in CONFIGS:
        net, cells = measure(db_path, video, ctx, base_calib, mode_cfg, sug, s, e, pq,
                             buf, match, args.start_hms, args.minutes)
        cells_last = cells
        cellvals = "  ".join(f"{cells.get(n, ('-', '-'))[1]:>9}" for n in WATCH_THRU)
        print(f"{label:<24} {net:>6.1f}%  {cellvals}")
    man = "  ".join(f"{cells_last.get(n, ('-', '-'))[0]:>9}" for n in WATCH_THRU)
    print(f"{'(manual)':<24} {'':>7}  {man}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
