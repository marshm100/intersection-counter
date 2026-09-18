"""Instrument run: re-track one cam4 window from its EXISTING detection cache
under a different default bbox buffer (buffered IoU), then measure the
northbound fragmentation the census found (2026-09-12).

Nothing touches production: the parquet is aliased to a scratch variant
name (bbNN_<variant>), the calibration read is monkeypatched to inject the
buffer (the camera row is not written), the dump lands next to the alias.
Prints the tracker-level metrics only (distinct rightward tracks per
cross-section, bottom-edge births, emergence coverage). Scoring is a
separate, declared step.
Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/arm_cam4_bbuf_retrack.py BUF VARIANT
        e.g. ... 1.3 study_1600
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend.database as DB  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

PROJ, CAM = "97a7849a", 4
BUF = float(sys.argv[1]); VARIANT = sys.argv[2]
NEW = f"bb{int(round(BUF * 10)):02d}_{VARIANT}"
XS = [200, 250, 300, 350, 400, 450, 500, 550]

_orig_calib = DB.get_camera_calibration_params


def _calib(project_id, camera_id):
    p = dict(_orig_calib(project_id, camera_id))
    if project_id == PROJ and camera_id == CAM:
        p["bbox_buffer_scale"] = BUF
    return p


DB.get_camera_calibration_params = _calib


def metrics(variant: str) -> None:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (CAM,)).fetchone()
    rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, CAM, chash, variant))))
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    tids, st = np.unique(rows[:, 0], return_index=True); en = np.append(st[1:], len(rows))
    cross = {X: 0 for X in XS}; nb = 0; edge_births = 0; edge_pts = []; edge_disp = []
    for a, b in zip(st, en):
        t = rows[a:b]
        if len(t) < 2:
            continue
        xs = t[:, 2].astype(float)
        for X in XS:
            if ((xs[:-1] < X) & (xs[1:] >= X)).any():
                cross[X] += 1
        if xs[-1] - xs[0] >= 40:
            nb += 1
            if t[0, 3] + t[0, 5] / 2 >= 440 and t[0, 4] >= 120:
                edge_births += 1; edge_pts.append(len(t)); edge_disp.append(xs[-1] - xs[0])
    print(f"\n[{variant}] tracks {len(tids)}; NB-bearing (>=40 px rightward) {nb}")
    print("  distinct tracks crossing X rightward: " + "  ".join(f"{X}:{cross[X]}" for X in XS))
    if edge_pts:
        print(f"  bottom-edge NB births (box bottom >= 440, w >= 120): {edge_births}; "
              f"points median {np.median(edge_pts):.0f} (p25 {np.percentile(edge_pts, 25):.0f}); "
              f"rightward travel median {np.median(edge_disp):.0f} px")


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (CAM,)).fetchone()
    src = parquet_path(PROJ, CAM, chash, VARIANT)
    dst = parquet_path(PROJ, CAM, chash, NEW)
    meta = json.load(open(src.with_suffix(".meta.json")))
    f0, f1 = meta["windows"][0]
    if not dst.exists():
        shutil.copy2(src, dst)
        meta["derived_from"] = f"alias of {VARIANT} for the bbox-buffer {BUF} re-track (arm instrument, 2026-09-12)"
        dst.with_suffix(".meta.json").write_text(json.dumps(meta))
    from backend.services.two_pass import run_pass1
    t = time.time()
    res = run_pass1(PROJ, CAM, variant=NEW, start_frame=f0, end_frame=f1, resume=False)
    tm = json.load(open(tracks_dir(dst) / "meta.json"))
    print(f"pass-1 {NEW}: {res.get('rows') or res.get('tracks') or res} in {time.time() - t:.0f}s; dump meta bbox_buffer={tm.get('bbox_buffer')}")
    metrics(VARIANT)
    metrics(NEW)
    from probe_cam4_nb_emergence import coverage
    coverage(NEW)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
