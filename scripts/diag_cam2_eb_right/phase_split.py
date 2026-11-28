"""Generalised ebr_phase.py: APPROACH's movements Mio vs ours split by that approach's phase of the minute
('red' = Mio APPROACH thru+left <= R, else 'green'). usage: phase_split.py APPROACH [R=2]. Read-only."""
import sys
from datetime import time as dtime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S
site=S.SITES[S.CORRIDOR]; ld=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
A=sys.argv[1]; R=int(sys.argv[2]) if len(sys.argv)>2 else 2
for W in ('study_0700','study_1100','study_1600'):
    db=f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{W}.db'
    pm=S.per_min_from_events(S.events_from_db(db,2,site),ld); lo,hi=site['windows'][W]
    for half in ((lo,hi),) if W!='study_0700' else ((7,8),(8,9)):
        acc={(k,mv):[0,0,0] for k in ('red','green') for mv in ('right','thru','left')}
        for h in range(*half):
            for i in range(60):
                m=dtime(h,i)
                if m not in mio: continue
                k='red' if mio[m].get((A,'thru'),0)+mio[m].get((A,'left'),0)<=R else 'green'
                for mv in ('right','thru','left'):
                    a=acc[(k,mv)]; a[0]+=1; a[1]+=mio[m].get((A,mv),0); a[2]+=pm.get(m,{}).get((A,mv),0)
        print(W, f'{half[0]:02}-{half[1]:02}', ' | '.join(f'{k} {mv} {v[0]}m {v[1]}/{v[2]} ({v[2]-v[1]:+d})' for (k,mv),v in acc.items()))
