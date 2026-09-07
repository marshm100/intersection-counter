"""G-C45-1 B1 — re-detect cam4 + cam5's six windows at counted_path.

Fresh variants l1_study_HHMM: no cache exists, so run_pass1
detect-at-ingest runs the production mode (yolo26l@1280) with each
camera's OWN calibrated recipe (bytetrack — no ReID stage needed).
Armed verification per window: the parquet meta must say
yolo26l/1280.

Usage:  py -X utf8 scripts/c45_redetect.py
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
WINDOWS = [(4, "07:00:00"), (4, "11:00:00"), (4, "16:00:00"),
           (5, "07:00:00"), (5, "11:00:00"), (5, "16:00:00")]


def main() -> int:
    from backend.services.detection_cache import parquet_path
    from backend.services.two_pass import run_pass1

    conn = sqlite3.connect(f"data/projects/{PROJ}/project.db")
    vids = {int(r[0]): (r[1], float(r[2]), r[3]) for r in conn.execute(
        "SELECT camera_id, content_hash, fps, recording_start_datetime "
        "FROM videos WHERE camera_id IN (4, 5)")}
    conn.close()

    for cam, hms in WINDOWS:
        chash, fps, rec = vids[cam]
        variant = f"l1_study_{hms[:2]}{hms[3:5]}"
        rec_dt = datetime.fromisoformat(rec)
        t0 = datetime.fromisoformat(f"{rec_dt.date().isoformat()}T{hms}")
        f_lo = int((t0 - rec_dt).total_seconds() * fps)
        f_hi = f_lo + int(120 * 60 * fps)
        t = time.time()
        res = run_pass1(PROJ, cam, variant=variant,
                        start_frame=f_lo, end_frame=f_hi)
        meta = json.loads(parquet_path(PROJ, cam, chash, variant)
                          .with_suffix(".meta.json").read_text())
        print(f"cam{cam} {variant}: rows={res['rows']} "
              f"recipe={res['recipe']} meta="
              f"{{'model': {meta.get('model')!r}, "
              f"'imgsz': {meta.get('imgsz')}}} "
              f"({(time.time()-t)/60:.0f} min)", flush=True)
        assert meta.get("model") == "yolo26l.pt" and \
            meta.get("imgsz") == 1280, "ARMED VERIFICATION FAILED"
    print("ALL SIX DUMPS BUILT AND VERIFIED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
