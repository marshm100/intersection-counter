import sys, sqlite3
from collections import Counter, defaultdict
from datetime import datetime, time as dtime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S
mio=S.load_miovision(2,S.SITES[S.CORRIDOR])
D={26:'WB',27:'SB',28:'EB',29:'NB'}
win=sys.argv[1]; lo,hi=S.SITES[S.CORRIDOR]['windows'][win]
db=f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{win}.db'
c=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
ours=defaultdict(Counter)
for o,mv,ts in c.execute("select origin_leg_id,movement,timestamp_real from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
    if ts is None: continue
    t=datetime.fromisoformat(ts).time()
    if lo<=t.hour<hi: ours[dtime(t.hour,t.minute)][(D.get(o),S.NORM.get(mv,mv))]+=1
cell=tuple(sys.argv[2].split(':'))
diffs=[]
for h in range(lo,hi):
    for m in range(60):
        k=dtime(h,m)
        if k not in mio: continue
        diffs.append((k,mio[k].get(cell,0),ours[k][cell]))
import numpy as np
d=np.array([o-r for _,r,o in diffs])
print(f'{win} {cell}: minutes {len(d)} total diff {d.sum():+d}; minutes over by >=3: {(d>=3).sum()} carrying {d[d>=3].sum():+d}; minutes with diff in [-2,2]: {((d>=-2)&(d<=2)).sum()}; sum of positive {d[d>0].sum()}, negative {d[d<0].sum()}')
print('  histogram', dict(sorted(Counter(d.tolist()).items())))
print('  worst minutes', [(k.strftime('%H:%M'),r,o) for k,r,o in sorted(diffs,key=lambda x:-(x[2]-x[1]))[:12]])
