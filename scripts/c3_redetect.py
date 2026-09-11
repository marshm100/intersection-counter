"""G-DEF-5 d9 — re-detect cam3's study_0600 (14 h) at the large basis.

Fresh variant l1_study_0600: run_pass1 detect-at-ingest at the
production mode (yolo26l@1280) with cam3's OWN calibrated recipe
(botsort). Armed verification: the parquet meta must say yolo26l/1280.
Copied from scripts/c45_redetect.py (09-07) for one camera-window.
Expect ~6 h on this GPU (~50 min per 2 h of video).

Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/c3_redetect.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJ = "97a7849a"
CAM, HMS, MINUTES = 3, "06:00:00", 14 * 60


def main() -> int:
    from backend.services.detection_cache import parquet_path
    from backend.services.two_pass import run_pass1

    conn = sqlite3.connect(f"data/projects/{PROJ}/project.db")
    chash, fps, rec = conn.execute(
        "SELECT content_hash, fps, recording_start_datetime FROM videos "
        "WHERE camera_id = ?", (CAM,)).fetchone()
    conn.close()
    fps = float(fps)
    variant = f"l1_study_{HMS[:2]}{HMS[3:5]}"
    rec_dt = datetime.fromisoformat(rec)
    t0 = datetime.fromisoformat(f"{rec_dt.date().isoformat()}T{HMS}")
    f_lo = int((t0 - rec_dt).total_seconds() * fps)
    f_hi = f_lo + int(MINUTES * 60 * fps)
    print(f"cam{CAM} {variant}: frames {f_lo}-{f_hi} ({MINUTES} min)", flush=True)
    t = time.time()
    res = run_pass1(PROJ, CAM, variant=variant, start_frame=f_lo, end_frame=f_hi)
    meta = json.loads(parquet_path(PROJ, CAM, chash, variant)
                      .with_suffix(".meta.json").read_text())
    print(f"cam{CAM} {variant}: rows={res['rows']} recipe={res['recipe']} "
          f"meta={{'model': {meta.get('model')!r}, 'imgsz': {meta.get('imgsz')}}} "
          f"({(time.time() - t) / 60:.0f} min)", flush=True)
    assert meta.get("model") == "yolo26l.pt" and meta.get("imgsz") == 1280, \
        "ARMED VERIFICATION FAILED"
    print("DUMP BUILT AND VERIFIED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
