"""Why did the twin dedup miss the events the 100 px floor removed? (2026-09-11)

For every event the floor removed (current-arm DB minus d15 DB, one
camera), find its best coexisting partner among the SURVIVING events
by the dedup's own three statistics computed on the dump rows:
overlap fraction of the shorter life, median common-frame centre
distance (px) and median common-frame IoU. Print the current
thresholds, the distributions, and how many removed events a relaxed
threshold set would catch, per camera, by movement.
Usage: .venv\Scripts\python.exe -X utf8 scripts/census_twin_stats.py
"""
from __future__ import annotations
import sqlite3, sys
from collections import Counter
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import parquet_path
from backend.services.pass2_replay import load_dump, tracks_dir
from backend.services.track_chains import STITCH_STAT_DIST
from backend.services import turn_merge as tm

BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
PROJ = "97a7849a"
PAIRS = [(1, "study_1600", "d7_cam1_study_1600.db", "d15_cam1_study_1600.db"),
         (5, "l1_study_1600", "d14_cam5_l1_study_1600.db", "d15_cam5_l1_study_1600.db")]
print(f"current thresholds: TWIN_OVERLAP_FRAC {tm.TWIN_OVERLAP_FRAC}  STITCH_STAT_DIST {STITCH_STAT_DIST}  TWIN_IOU_MIN {tm.TWIN_IOU_MIN}")


def load(db, cam):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    r = con.execute("SELECT vehicle_track_id, start_frame, movement, origin_leg_id, destination_leg_id FROM vehicle_events "
                    "WHERE camera_id=? AND rejected=0 AND vehicle_track_id IS NOT NULL", (cam,)).fetchall()
    con.close()
    return {(a, b): (m, o, d) for a, b, m, o, d in r}


def stats(ai, aj):
    i0, i1, j0, j1 = ai[0, 1], ai[-1, 1], aj[0, 1], aj[-1, 1]
    ov = min(i1, j1) - max(i0, j0); short = max(1.0, min(i1 - i0, j1 - j0))
    if ov <= 0:
        return None
    common, ii, jj = np.intersect1d(ai[:, 1], aj[:, 1], return_indices=True)
    if len(common) < 5:
        return None
    pi, pj = ai[ii], aj[jj]
    d = np.median(np.hypot(pi[:, 2] - pj[:, 2], pi[:, 3] - pj[:, 3]))
    x1 = np.maximum(pi[:, 2] - pi[:, 4] / 2, pj[:, 2] - pj[:, 4] / 2); x2 = np.minimum(pi[:, 2] + pi[:, 4] / 2, pj[:, 2] + pj[:, 4] / 2)
    y1 = np.maximum(pi[:, 3] - pi[:, 5] / 2, pj[:, 3] - pj[:, 5] / 2); y2 = np.minimum(pi[:, 3] + pi[:, 5] / 2, pj[:, 3] + pj[:, 5] / 2)
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    iou = np.median(inter / np.maximum(pi[:, 4] * pi[:, 5] + pj[:, 4] * pj[:, 5] - inter, 1e-6))
    # size-relative distance: centre distance over the mean box length of the pair
    rel = d / max(1.0, float(np.median(np.maximum(pi[:, 4], pi[:, 5]) + np.maximum(pj[:, 4], pj[:, 5])) / 2))
    return ov / short, d, iou, rel


con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
for cam, variant, cur_db, new_db in PAIRS:
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    tids = rows[:, 0]; _u, st = np.unique(tids, return_index=True); en = np.append(st[1:], len(rows))
    seg = {int(t): (a, b) for t, a, b in zip(_u, st, en)}
    cur, new = load(BASE / cur_db, cam), load(BASE / new_db, cam)
    removed = {k: v for k, v in cur.items() if k not in new}
    surv = [(k[0], v) for k, v in new.items() if k[0] in seg]
    surv_arr = sorted(((rows[seg[t][0], 1], rows[seg[t][1] - 1, 1], t, v) for t, v in surv))
    s0 = np.array([s[0] for s in surv_arr]); s1 = np.array([s[1] for s in surv_arr])
    best = []
    for (tid, sf), (mv, o, d) in removed.items():
        if tid not in seg:
            continue
        a, b = seg[tid]; ai = rows[a:b]
        i0, i1 = ai[0, 1], ai[-1, 1]
        cand = np.nonzero((s0 <= i1) & (s1 >= i0))[0]
        bb = None
        for c in cand:
            t2 = surv_arr[c][2]
            if t2 == tid:
                continue
            aj = rows[seg[t2][0]:seg[t2][1]]
            r = stats(ai, aj)
            if r and (bb is None or r[2] > bb[2]):
                bb = r + (surv_arr[c][3][0], surv_arr[c][3][1] == o and surv_arr[c][3][2] == d)
        best.append((mv, bb))
    n = len(best); have = [b for _m, b in best if b]
    print(f"\n=== cam{cam} {variant}: removed {n}; with any coexisting partner (>=5 common frames): {len(have)}")
    if not have:
        continue
    A = np.array([[b[0], b[1], b[2], b[3]] for b in have])
    def q(a): return "/".join(f"{x:.2f}" for x in np.percentile(a, [10, 50, 90]))
    print(f"  best partner: overlap frac p10/50/90 {q(A[:,0])}  centre dist px {q(A[:,1])}  IoU {q(A[:,2])}  dist/boxlen {q(A[:,3])}")
    print(f"  same origin+dest as partner: {sum(1 for b in have if b[5])}/{len(have)}")
    cur_pass = sum(1 for b in have if b[0] >= tm.TWIN_OVERLAP_FRAC and b[1] <= STITCH_STAT_DIST and b[2] >= tm.TWIN_IOU_MIN)
    print(f"  pass CURRENT twin test (should be ~0, they survived it): {cur_pass}")
    for name, test in (("ov>=.5 & IoU>=.3", lambda b: b[0] >= .5 and b[2] >= .3),
                       ("ov>=.5 & IoU>=.2", lambda b: b[0] >= .5 and b[2] >= .2),
                       ("ov>=.5 & IoU>=.1", lambda b: b[0] >= .5 and b[2] >= .1),
                       ("ov>=.5 & dist/box<=1.0", lambda b: b[0] >= .5 and b[3] <= 1.0),
                       ("ov>=.5 & dist/box<=0.5", lambda b: b[0] >= .5 and b[3] <= 0.5),
                       ("ov>=.8 & IoU>=.2", lambda b: b[0] >= .8 and b[2] >= .2)):
        hit = [m for m, b in best if b and test(b)]
        print(f"  {name:24}: catches {len(hit):4}/{n}  by movement {Counter(hit).most_common(4)}")
