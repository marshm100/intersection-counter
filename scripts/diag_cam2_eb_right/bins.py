import sys, sqlite3
from datetime import time as dtime
from collections import defaultdict
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S
from backend.services.rule595 import score_cells
site=S.SITES[S.CORRIDOR]; leg_dir=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
def ap(pm):
    o=defaultdict(lambda: defaultdict(int))
    for m,c in pm.items():
        for k,v in c.items(): o[m][k[0]]+=v
    return o
for win in ('study_0700','study_1100','study_1600'):
    db=f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{win}.db'
    lo,hi=site['windows'][win]; mm=[m for m in (dtime(h,x) for h in range(lo,hi) for x in range(60)) if m in mio]
    pm=S.per_min_from_events(S.events_from_db(db,2,site),leg_dir)
    rows=score_cells(ap(pm),ap(mio),mm)
    print(f'\n{win} approach bins  (ours-ref, * = fail)')
    by=defaultdict(dict)
    for r in rows: by[r['cell']][r['bin']]=r
    for c in sorted(by):
        print(f'  {c:3}', '  '.join(f"{b[-5:]} {r['ref']:3}{r['ours']-r['ref']:+4}{'*' if not r['ok'] else ' '}" for b,r in sorted(by[c].items())))
