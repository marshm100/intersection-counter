"""Per 15-min bin, Mio vs ours per approach-movement (all 3 windows). Read-only."""
import sys
from datetime import time as dtime
from collections import defaultdict
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S
site=S.SITES[S.CORRIDOR]; leg_dir=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
apps=sys.argv[1:] or ['EB','WB']
for win in ('study_0700','study_1100','study_1600'):
    db=f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{win}.db'
    lo,hi=site['windows'][win]
    pm=S.per_min_from_events(S.events_from_db(db,2,site),leg_dir)
    print(f'\n{win}')
    keys=sorted({k for m in list(mio)+list(pm) for k in list(mio.get(m,{}))+list(pm.get(m,{})) if k[0] in apps})
    for k in keys:
        cells=[]
        for h in range(lo,hi):
            for q in range(0,60,15):
                mm=[dtime(h,q+i) for i in range(15) if dtime(h,q+i) in mio]
                r=sum(mio[m].get(k,0) for m in mm); o=sum(pm.get(m,{}).get(k,0) for m in mm)
                cells.append(f'{h:02}:{q:02} {r:3}/{o:<3}')
        print(f'  {str(k):14}', ' '.join(cells))
