"""d16 pre-declaration census (2026-09-11): how long do the short tracks live?

d15 showed a 100 px floor removes far-field phantoms on cam5 and real
short journeys on cam1/cam2. Before declaring a TIME floor, measure:
for every track in a dump with >= 5 points, its path distance (px,
centre-to-centre) and its duration (s). Print duration quantiles for
the 50-100 px band (what d15 removed) and the >= 100 px band (what a
time floor must not touch), per camera.
Usage: .venv\Scripts\python.exe -X utf8 scripts/census_short_tracks.py
"""
from __future__ import annotations
import sqlite3, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import parquet_path
from backend.services.pass2_replay import load_dump, tracks_dir

PROJ = "97a7849a"
WINDOWS = [(1, "study_1600"), (2, "study_1600"), (3, "l1_study_0600"), (4, "l1_study_1100"), (5, "l1_study_1600")]
con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
for cam, variant in WINDOWS:
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    tid = rows[:, 0]
    _t, starts = np.unique(tid, return_index=True)
    ends = np.append(starts[1:], len(rows))
    dist, dur, npts = [], [], []
    for a, b in zip(starts, ends):
        if b - a < 5:
            continue
        xy = rows[a:b, 2:4]
        dist.append(float(np.hypot(*np.diff(xy, axis=0).T).sum()))
        dur.append(float(rows[b - 1, 1] - rows[a, 1] + 1) / float(fps))
        npts.append(b - a)
    dist, dur = np.array(dist), np.array(dur)
    print(f"\ncam{cam} {variant} fps {fps:.1f}: tracks>=5pts {len(dist)}")
    for name, m in (("50-100 px", (dist >= 50) & (dist < 100)), (">=100 px", dist >= 100), ("<50 px", dist < 50)):
        d = dur[m]
        if not len(d):
            continue
        q = np.percentile(d, [10, 25, 50, 75, 90])
        print(f"  {name:>10}: n={len(d):5d}  dur s p10 {q[0]:.2f} p25 {q[1]:.2f} p50 {q[2]:.2f} p75 {q[3]:.2f} p90 {q[4]:.2f}"
              f"   <1s {np.mean(d<1):.0%} <2s {np.mean(d<2):.0%} <3s {np.mean(d<3):.0%}")
