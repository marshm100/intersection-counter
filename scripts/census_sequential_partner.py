"""Are the floor-removed events SEQUENTIAL fragments of a counted vehicle? (2026-09-11)

For each event the 100 px floor removed (current-arm DB minus d15 DB),
find the nearest surviving event in TIME SEQUENCE: a survivor born
within STITCH_STAT_GAP_S after the removed track's death whose birth
point is near the removed track's death point, or the mirror (the
removed born after a survivor died). Distances reported in px AND in
box lengths (the pair's mean of max(bw, bh)). Prints distributions and
catches by threshold, per camera, by movement.
Usage: .venv\Scripts\python.exe -X utf8 scripts/census_sequential_partner.py
"""
from __future__ import annotations
import sqlite3, sys
from collections import Counter
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import parquet_path
from backend.services.pass2_replay import load_dump, tracks_dir

BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
PROJ = "97a7849a"
PAIRS = [(1, "study_1600", "d7_cam1_study_1600.db", "d15_cam1_study_1600.db"),
         (5, "l1_study_1600", "d14_cam5_l1_study_1600.db", "d15_cam5_l1_study_1600.db")]
GAP_S = 50.0


def load(db, cam):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    r = con.execute("SELECT vehicle_track_id, start_frame, movement, origin_leg_id, destination_leg_id FROM vehicle_events "
                    "WHERE camera_id=? AND rejected=0 AND vehicle_track_id IS NOT NULL", (cam,)).fetchall()
    con.close()
    return {(a, b): (m, o, d) for a, b, m, o, d in r}


con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
for cam, variant, cur_db, new_db in PAIRS:
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    _u, st = np.unique(rows[:, 0], return_index=True); en = np.append(st[1:], len(rows))
    seg = {int(t): (a, b) for t, a, b in zip(_u, st, en)}
    def ends(t):
        a, b = seg[t]; r0, r1 = rows[a], rows[b - 1]
        box = float(np.median(np.maximum(rows[a:b, 4], rows[a:b, 5])))
        return r0[1], r1[1], (r0[2], r0[3]), (r1[2], r1[3]), box
    cur, new = load(BASE / cur_db, cam), load(BASE / new_db, cam)
    removed = {k: v for k, v in cur.items() if k not in new and k[0] in seg}
    surv = [(t, v, ends(t)) for (t, _sf), v in new.items() if t in seg]
    s_birth = np.array([s[2][0] for s in surv]); s_death = np.array([s[2][1] for s in surv])
    out = []
    for (tid, _sf), (mv, o, d) in removed.items():
        f0, f1, p0, p1, box = ends(tid)
        best = None
        # forward: survivor born after our death, near our death point
        for i in np.nonzero((s_birth >= f1) & (s_birth <= f1 + GAP_S * fps))[0]:
            t2, v2, (g0, g1, q0, q1, box2) = surv[i]
            if t2 == tid: continue
            dist = float(np.hypot(q0[0] - p1[0], q0[1] - p1[1])); rel = dist / max(1.0, (box + box2) / 2)
            if best is None or rel < best[0]: best = (rel, dist, (g0 - f1) / fps, "fwd", v2[0], (v2[1], v2[2]) == (o, d))
        # backward: we were born after a survivor's death, near its death point
        for i in np.nonzero((s_death <= f0) & (s_death >= f0 - GAP_S * fps))[0]:
            t2, v2, (g0, g1, q0, q1, box2) = surv[i]
            if t2 == tid: continue
            dist = float(np.hypot(q1[0] - p0[0], q1[1] - p0[1])); rel = dist / max(1.0, (box + box2) / 2)
            if best is None or rel < best[0]: best = (rel, dist, (f0 - g1) / fps, "bwd", v2[0], (v2[1], v2[2]) == (o, d))
        out.append((mv, best))
    n = len(out); have = [b for _m, b in out if b]
    A = np.array([[b[0], b[1], b[2]] for b in have])
    def q(a): return "/".join(f"{x:.2f}" for x in np.percentile(a, [10, 25, 50, 75, 90]))
    print(f"\n=== cam{cam} {variant}: removed {n}; nearest sequential survivor within {GAP_S:.0f} s: {len(have)}")
    print(f"  dist/boxlen p10/25/50/75/90 {q(A[:,0])}   dist px {q(A[:,1])}   gap s {q(A[:,2])}")
    print(f"  same origin+dest: {sum(1 for b in have if b[5])}/{len(have)}   fwd {sum(1 for b in have if b[3]=='fwd')} bwd {sum(1 for b in have if b[3]=='bwd')}")
    for rel_max, gap_max in ((0.5, 50), (1.0, 50), (1.5, 50), (2.0, 50), (1.0, 10), (1.5, 10)):
        hit = [m for m, b in out if b and b[0] <= rel_max and b[2] <= gap_max]
        same = sum(1 for m, b in out if b and b[0] <= rel_max and b[2] <= gap_max and b[5])
        print(f"  dist/box<={rel_max} gap<={gap_max:2}s: catches {len(hit):4}/{n} (same o+d {same:3})  {Counter(hit).most_common(4)}")
    print(f"  PX for reference: dist<=35px gap<=50s: {sum(1 for m,b in out if b and b[1]<=35 and b[2]<=50)}")
