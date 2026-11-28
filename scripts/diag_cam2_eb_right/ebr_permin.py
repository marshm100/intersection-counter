"""Per-minute EB-right Mio/ours for a window (default 1600). Read-only."""
import sys
from datetime import time as dtime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S
site=S.SITES[S.CORRIDOR]; ld=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
W=sys.argv[1] if len(sys.argv)>1 else 'study_1600'; K=('EB','right')
db=f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{W}.db'
pm=S.per_min_from_events(S.events_from_db(db,2,site),ld); lo,hi=site['windows'][W]
for h in range(lo,hi):
    for q in range(0,60,15):
        print(f'{h:02}:{q:02}', ' '.join(f"{mio.get(dtime(h,q+i),{}).get(K,0):2}/{pm.get(dtime(h,q+i),{}).get(K,0):<2}" for i in range(15)))
