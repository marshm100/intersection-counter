"""Ceiling: cam2 5/95 if still tracks and/or theft-signature tracks were not counted. Read-only."""
import sys, sqlite3, os, numpy as np
from datetime import datetime, time as dtime
sys.path.insert(0, 'scripts'); sys.path.insert(0, '.'); sys.path.insert(0, 'scripts/diag_cam2_eb_right')
import eval_journeys as EJ, v2_score_dev as S
from backend.services.rule595 import compliance, score_cells
from collections import defaultdict
import importlib.util
spec = importlib.util.spec_from_file_location('inst', 'scripts/diag_cam2_eb_right/instant.py')
src = open('scripts/diag_cam2_eb_right/instant.py').read().split('res={}')[0]
ns = {}; exec(src, ns); instant_start = ns['instant_start']

site = S.SITES[S.CORRIDOR]
con = sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro', uri=True)
chash = con.execute('select content_hash from videos where video_id=2').fetchone()[0]
leg_dir = S.leg_dir_for(S.CORRIDOR, 2, site)
mio = S.load_miovision(2, site)

def approach(pm):
    out = defaultdict(lambda: defaultdict(int))
    for m, cells in pm.items():
        for k, v in cells.items(): out[m][k[0]] += v
    return out

for win in ('study_0700', 'study_1100', 'study_1600'):
    db, rows = EJ.locate('sf0', {2: 'sf0_'}, 2, win, chash)
    print(f'\n{win}  db={db}  mtime={datetime.fromtimestamp(os.path.getmtime(db))}')
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    tids, idx = np.unique(rows[:, 0], return_index=True); idx = list(idx) + [len(rows)]
    T = {int(t): rows[idx[i]:idx[i + 1]] for i, t in enumerate(tids)}
    lo, hi = site['windows'][win]
    minutes = [dtime(h, m) for h in range(lo, hi) for m in range(60)]
    mm = [m for m in minutes if m in mio]
    d = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    evs = []
    for t, o, mv, ts in d.execute("select vehicle_track_id, origin_leg_id, movement, timestamp_real from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
        if ts is None: continue
        r = T.get(int(t)); still = theft = False
        if r is not None:
            span = np.hypot(np.ptp(r[:, 2]), np.ptp(r[:, 3]))
            still = span < 2.0 * np.median(r[:, 4])
            theft = len(r) >= 10 and instant_start(r) is not None
        evs.append(dict(origin_leg=o, movement=mv, wallclock=ts, still=still, theft=theft))
    for name, keep in [('as shipped', lambda e: True), ('- still', lambda e: not e['still']),
                       ('- theft sig', lambda e: not e['theft']), ('- both', lambda e: not (e['still'] or e['theft']))]:
        ev = [e for e in evs if keep(e)]
        pm = S.per_min_from_events(ev, leg_dir)
        mv = compliance(score_cells(pm, mio, mm)); ap = compliance(score_cells(approach(pm), approach(mio), mm))
        print(f'  {name:12} n={len(ev):5}  movement {mv["pct"]:5}%  approach {ap["pct"]:5}%')
