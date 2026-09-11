"""G-BLANK-1 B1 — re-detect FM 51 camera 2's two windows at the production mode.

Fresh variants l1_study_0700 / l1_study_1600: run_pass1 detect-at-ingest
(yolo26l@1280, the camera's default tracker recipe — FM51 has no
per-camera calibration). Armed verification: parquet meta says
yolo26l/1280. Copied from scripts/c45_redetect.py for one camera.
Expect ~2 h of GPU.

Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/fm51_redetect.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJ = __import__("os").environ.get("FM51_PROJ", "0acb12c0")
CAM = 2
WINDOWS = [("07:00:00", 120), ("16:00:00", 120)]


def main() -> int:
    from backend.services.detection_cache import parquet_path
    from backend.services.two_pass import run_pass1

    conn = sqlite3.connect(f"data/projects/{PROJ}/project.db")
    chash, fps, rec = conn.execute(
        "SELECT content_hash, fps, recording_start_datetime FROM videos "
        "WHERE camera_id = ?", (CAM,)).fetchone()
    conn.close()
    fps = float(fps)
    rec_dt = datetime.fromisoformat(rec)
    for hms, minutes in WINDOWS:
        variant = f"l1_study_{hms[:2]}{hms[3:5]}"
        t0 = datetime.fromisoformat(f"{rec_dt.date().isoformat()}T{hms}")
        f_lo = int((t0 - rec_dt).total_seconds() * fps)
        f_hi = f_lo + int(minutes * 60 * fps)
        print(f"FM51 cam{CAM} {variant}: frames {f_lo}-{f_hi}", flush=True)
        t = time.time()
        res = run_pass1(PROJ, CAM, variant=variant, start_frame=f_lo, end_frame=f_hi)
        meta = json.loads(parquet_path(PROJ, CAM, chash, variant)
                          .with_suffix(".meta.json").read_text())
        print(f"FM51 cam{CAM} {variant}: rows={res['rows']} recipe={res['recipe']} "
              f"meta={{'model': {meta.get('model')!r}, 'imgsz': {meta.get('imgsz')}}} "
              f"({(time.time() - t) / 60:.0f} min)", flush=True)
        assert meta.get("model") == "yolo26l.pt" and meta.get("imgsz") == 1280, \
            "ARMED VERIFICATION FAILED"
    print("BOTH DUMPS BUILT AND VERIFIED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
