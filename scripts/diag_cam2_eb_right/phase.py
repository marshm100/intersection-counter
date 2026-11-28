import sys, sqlite3
from collections import Counter, defaultdict
from datetime import datetime, time as dtime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S
mio=S.load_miovision(2,S.SITES[S.CORRIDOR])
D={26:'WB',27:'SB',28:'EB',29:'NB'}
for win in ('study_0700','study_1100','study_1600'):
    lo,hi=S.SITES[S.CORRIDOR]['windows'][win]
    c=sqlite3.connect(f'file:data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{win}.db?mode=ro',uri=True)
    ours=defaultdict(Counter)
    for o,mv,ts in c.execute("select origin_leg_id,movement,timestamp_real from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
        if ts is None: continue
        t=datetime.fromisoformat(ts).time()
        if lo<=t.hour<hi: ours[dtime(t.hour,t.minute)][(D.get(o),S.NORM.get(mv,mv))]+=1
    grp=defaultdict(lambda:[0,0,0])
    for h in range(lo,hi):
        for m in range(60):
            k=dtime(h,m)
            if k not in mio: continue
            eb_thru_left=mio[k].get(('EB','thru'),0)+mio[k].get(('EB','left'),0)
            sb=mio[k].get(('SB','thru'),0)
            # EB 'red' minute: Mio saw no EB through/left movement at all
            g='EB red (Mio EB thru+left=0)' if eb_thru_left==0 else 'EB green'
            grp[g][0]+=1; grp[g][1]+=mio[k].get(('EB','right'),0); grp[g][2]+=ours[k][('EB','right')]
    print(win)
    for g,(n,r,o) in grp.items(): print(f'   {g:30} minutes {n:3}  EB right mio {r:4} ours {o:4} diff {o-r:+4}  per-minute excess {(o-r)/n:+.2f}')
