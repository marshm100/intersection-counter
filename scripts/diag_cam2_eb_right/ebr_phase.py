"""EB-right Mio vs ours split by EB phase of the minute: 'red' = minute with EB thru+left (Mio) <= R, else 'green'.
The phase proxy uses only the EB thru/left counts, which match Miovision. Read-only."""
import sys
from datetime import time as dtime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S
site=S.SITES[S.CORRIDOR]; ld=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
R=int(sys.argv[1]) if len(sys.argv)>1 else 2
for W in ('study_0700','study_1100','study_1600'):
    db=f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{W}.db'
    pm=S.per_min_from_events(S.events_from_db(db,2,site),ld); lo,hi=site['windows'][W]
    for half in ((lo,hi),) if W!='study_0700' else ((7,8),(8,9)):
        acc={'red':[0,0,0],'green':[0,0,0]}
        for h in range(*half):
            for i in range(60):
                m=dtime(h,i)
                if m not in mio: continue
                tl=mio[m].get(('EB','thru'),0)+mio[m].get(('EB','left'),0)
                k='red' if tl<=R else 'green'
                a=acc[k]; a[0]+=1; a[1]+=mio[m].get(('EB','right'),0); a[2]+=pm.get(m,{}).get(('EB','right'),0)
        print(W, f'{half[0]:02}-{half[1]:02}', '  '.join(f'{k}: {v[0]} min, Mio {v[1]} ours {v[2]} ({v[2]-v[1]:+d})' for k,v in acc.items()))
