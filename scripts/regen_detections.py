"""Phase 4a: regenerate detection caches under a NEW variant with the detector-head
settings the environment sets (e.g. DETECT_DEDUP_HEAD=1 DETECT_HALF=1), then
track them with THE DEFAULT (new-site) tracker, per-camera knobs blanked
(2026-09-30, docs/research_tracking_2026-09-29.md).

A window's variant PREFIX_study_HHMM gets its own parquet cache and dump
(detect-at-ingest in two_pass.run_pass1), so production caches are untouched.
Window frames come from each base window's cache meta.

Usage: DETECT_DEDUP_HEAD=1 DETECT_HALF=1 .venv/Scripts/python.exe -X utf8 scripts/regen_detections.py PREFIX [CAM:WINDOW ...]
REGEN_MODEL / REGEN_IMGSZ (2026-10-01, item 4): override the processing mode's detector
model and image size for this run only (project.db is never written), e.g.
REGEN_MODEL=yolo26s.pt REGEN_IMGSZ=960 for one default model on every camera.
Default windows: the 12 corridor windows.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.database as _db  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402

PROJ = "97a7849a"
WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"), (2, "study_1100"),
           (2, "study_1600"), (3, "study_0600"), (4, "study_0700"), (4, "study_1100"),
           (4, "study_1600"), (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]
KNOBS = ("pre_track_nms_iou", "tracker_lost_buffer", "tracker_match_threshold",
         "tracker_activation_threshold", "bbox_buffer_scale", "new_track_thresh",
         "pass1_backend")


def main() -> int:
    prefix = sys.argv[1]
    wins = ([(int(a.split(":")[0]), a.split(":")[1]) for a in sys.argv[2:]] or WINDOWS)
    real = _db.get_camera_calibration_params

    def blank_site(project_id, camera_id):
        p = real(project_id, camera_id)
        for k in KNOBS:
            p[k] = None
        return p

    _db.get_camera_calibration_params = blank_site
    import os
    if os.environ.get("REGEN_MODEL") or os.environ.get("REGEN_IMGSZ"):
        import backend.config as _cfg
        real_mode = _cfg.get_processing_mode_config

        def mode(name):
            c = dict(real_mode(name))
            if os.environ.get("REGEN_MODEL"):
                c["yolo_model"] = os.environ["REGEN_MODEL"]
                c["yolo_class_scheme"] = "coco"
            if os.environ.get("REGEN_IMGSZ"):
                c["yolo_imgsz"] = int(os.environ["REGEN_IMGSZ"])
            return c
        _cfg.get_processing_mode_config = mode
    from backend.services.two_pass import run_pass1
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    for cam, window in wins:
        chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?",
                             (cam,)).fetchone()
        meta = json.loads(parquet_path(PROJ, cam, chash, window)
                          .with_suffix(".meta.json").read_text())
        f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
        t = time.time()
        res = run_pass1(PROJ, cam, variant=f"{prefix}_{window}", start_frame=f0,
                        end_frame=f1, backend="bytetrack", resume=True)
        print(f"cam{cam} {prefix}_{window}: {res.get('rows')} rows in "
              f"{time.time() - t:.0f}s (recipe {res.get('recipe')})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
