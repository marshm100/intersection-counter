"""G-C1-1 B1 — re-detect cam1 study_0700 under the production mode.

Fresh variant l1_study_0700: no cache exists, so run_pass1
detect-at-ingest runs the project's processing mode (counted_path:
yolo26l@1280 conf 0.10 skip 1) — the same recipe as every promoted
basis. Tracker stays the camera's own (botsort+reid). After the
dump: armed verification prints the parquet meta (the meta must say
yolo26l/1280 before pass-2 is allowed to run).

Usage:  py -X utf8 scripts/c1_morning_redetect.py
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


def main() -> int:
    from backend.services.detection_cache import parquet_path
    from backend.services.two_pass import run_pass1

    conn = sqlite3.connect(f"data/projects/{PROJ}/project.db")
    chash, fps, rec = conn.execute(
        "SELECT content_hash, fps, recording_start_datetime FROM videos "
        "WHERE camera_id = 1").fetchone()
    conn.close()
    rec_dt = datetime.fromisoformat(rec)
    t0 = datetime.fromisoformat(f"{rec_dt.date().isoformat()}T07:00:00")
    f_lo = int((t0 - rec_dt).total_seconds() * float(fps))
    f_hi = f_lo + int(120 * 60 * float(fps))

    # ReID chicken-and-egg (handoff_2026-07-27): the sidecar embeds
    # CACHED detections, so stage 1 detects with a plain-botsort dump
    # (throwaway), stage 2 builds the sidecar, stage 3 re-tracks with
    # the camera's own botsort+reid recipe over the cached detections.
    import shutil
    import subprocess

    from backend.services.pass2_replay import tracks_dir

    t = time.time()
    res = run_pass1(PROJ, 1, variant="l1_study_0700",
                    start_frame=f_lo, end_frame=f_hi, backend="botsort")
    print(f"stage 1 (detect, plain dump): rows={res['rows']} "
          f"({(time.time()-t)/60:.0f} min)", flush=True)

    t = time.time()
    r = subprocess.run([sys.executable, "-X", "utf8",
                        "scripts/build_reid_cache.py", "--camera", "1",
                        "--variant", "l1_study_0700", "--device", "0",
                        "--start-hms", "07:00:00", "--minutes", "120"],
                       capture_output=True, text=True)
    print(f"stage 2 (reid sidecar): rc={r.returncode} "
          f"({(time.time()-t)/60:.0f} min)", flush=True)
    if r.returncode != 0:
        print(r.stdout[-800:], r.stderr[-800:], flush=True)
        return 1

    td = Path(tracks_dir(parquet_path(PROJ, 1, chash, "l1_study_0700")))
    shutil.rmtree(td)                       # recipe changes; no resume mix
    t = time.time()
    res = run_pass1(PROJ, 1, variant="l1_study_0700",
                    start_frame=f_lo, end_frame=f_hi)
    print(f"stage 3 (botsort+reid dump): rows={res['rows']} "
          f"recipe={res['recipe']} ({(time.time()-t)/60:.0f} min)",
          flush=True)

    meta_p = parquet_path(PROJ, 1, chash, "l1_study_0700").with_suffix(
        ".meta.json")
    meta = json.loads(meta_p.read_text())
    print("ARMED VERIFICATION - detection meta:",
          {k: meta.get(k) for k in ("model", "imgsz", "conf")}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
