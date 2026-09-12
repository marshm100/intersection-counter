"""G-LT-1 stage 1 — build the eg_ dumps (emergence guard ON).

Runs pass-1 with EMERGENCE_GUARD=1 for the botsort-recipe cameras
(1, 2, 3 — bytetrack cams 4/5 have no mount point, chartered) over
the CACHED detections: the study parquet is hardlinked to the eg_
variant name first, so no GPU runs. The guard flag is set in the
environment BEFORE backend.config imports.

Usage:  py -X utf8 scripts/ltg_build_dumps.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ["EMERGENCE_GUARD"] = "1"          # before backend.config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJ = "97a7849a"
WINDOWS = [(1, "study_0700", "07:00:00", 120),
           (1, "study_1600", "16:00:00", 120),
           (2, "study_0700", "07:00:00", 120),
           (2, "study_1100", "11:00:00", 120),
           (2, "study_1600", "16:00:00", 120),
           (3, "study_0600", "06:00:00", 840)]


def main() -> int:
    from backend.config import EMERGENCE_GUARD
    assert EMERGENCE_GUARD, "flag failed to arm"
    from backend.services.detection_cache import parquet_path
    from backend.services.two_pass import run_pass1

    conn = sqlite3.connect(f"data/projects/{PROJ}/project.db")
    vids = {int(r[0]): (r[1], float(r[2]), r[3]) for r in conn.execute(
        "SELECT camera_id, content_hash, fps, recording_start_datetime "
        "FROM videos")}
    conn.close()

    for cam, variant, hms, minutes in WINDOWS:
        chash, fps, rec = vids[cam]
        src_pq = parquet_path(PROJ, cam, chash, variant)
        dst_pq = parquet_path(PROJ, cam, chash, f"eg_{variant}")
        if not dst_pq.exists():
            os.link(src_pq, dst_pq)
        for ext in (".meta.json", ".reid", ".reid.npz"):
            side_s = src_pq.with_name(src_pq.stem + ext)
            side_d = dst_pq.with_name(dst_pq.stem + ext)
            if side_s.exists() and not side_d.exists():
                try:
                    os.link(side_s, side_d)
                except OSError:
                    try:
                        import shutil
                        shutil.copy2(side_s, side_d)
                    except OSError as e:
                        print(f"  (sidecar {side_s.name} skipped: {e})",
                              flush=True)
        rec_dt = datetime.fromisoformat(rec)
        t0 = datetime.fromisoformat(f"{rec_dt.date().isoformat()}T{hms}")
        f_lo = int((t0 - rec_dt).total_seconds() * fps)
        f_hi = f_lo + int(minutes * 60 * fps)
        t = time.time()
        res = run_pass1(PROJ, cam, variant=f"eg_{variant}",
                        start_frame=f_lo, end_frame=f_hi)
        print(f"cam{cam} eg_{variant}: rows={res['rows']} "
              f"recipe={res['recipe']} ({time.time()-t:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
