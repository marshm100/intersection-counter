"""Re-track one window with THE DEFAULT TRACKER a new site gets (2026-09-27).

cams 1-3 run one-off per-camera tracker recipes (cam2: BoT-SORT with
calib_tracker_match_threshold 0.9). A blank site runs the recovery tracker
(bytetrack backend + the TRACKER_* defaults) with every per-camera tracker knob
unset. This re-tracks a window exactly that way, from its EXISTING detection
cache aliased to <prefix>_<variant> (arm_retrack_alias.py's pattern), so the
window becomes a new-site basis. project.db is never written: the per-camera
tracker knobs are blanked in memory for this run only.

Usage: .venv/Scripts/python.exe -X utf8 scripts/retrack_default_tracker.py PROJ CAM VARIANT PREFIX
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.database as _db  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

TRACKER_KNOBS = ("pre_track_nms_iou", "tracker_lost_buffer", "tracker_match_threshold",
                 "tracker_activation_threshold", "bbox_buffer_scale", "new_track_thresh",
                 "pass1_backend")


def main() -> int:
    proj, cam, variant, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    new = f"{prefix}_{variant}"
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
    con.close()
    src = parquet_path(proj, cam, chash, variant)
    dst = parquet_path(proj, cam, chash, new)
    meta = json.load(open(src.with_suffix(".meta.json")))
    f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
    if not dst.exists():
        shutil.copy2(src, dst)
        meta["derived_from"] = (f"alias of {variant}: re-track with the DEFAULT (new-site) "
                                f"tracker, per-camera knobs blanked ({prefix}, 2026-09-27)")
        dst.with_suffix(".meta.json").write_text(json.dumps(meta))

    real = _db.get_camera_calibration_params

    def blank_site(project_id, camera_id):
        p = real(project_id, camera_id)
        for k in TRACKER_KNOBS:
            p[k] = None
        return p

    _db.get_camera_calibration_params = blank_site
    from backend.services.two_pass import run_pass1
    t = time.time()
    done = [0]

    def progress(n, total, points):
        if n - done[0] >= 18000:
            done[0] = n
            print(f"  {n}/{total} frames ({points} points, {time.time() - t:.0f}s)", flush=True)

    run_pass1(proj, cam, variant=new, start_frame=f0, end_frame=f1, backend="bytetrack",
              resume=False, progress=progress)
    tm = json.load(open(tracks_dir(dst) / "meta.json"))
    rows = int((tracks_dir(dst) / "count.txt").read_text())
    print(f"pass-1 cam{cam} {new}: {rows} rows in {time.time() - t:.0f}s; recipe "
          + ", ".join(f"{k}={tm.get(k)}" for k in ("backend", "match", "activation", "bbox_buffer",
                                                    "position_recovery", "fuse_score")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
