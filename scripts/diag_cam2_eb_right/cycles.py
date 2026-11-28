"""EB (or any approach) ours vs Miovision per signal cycle. A cycle = an EB-green minute (Mio thru+left>0) and the
red minutes after it, so the per-minute split of Miovision cannot move a car between groups. Read-only.
usage: cycles.py WINDOW APPROACH"""
import sys, sqlite3
from collections import Counter
from datetime import datetime
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
import v2_score_dev as S
W,A=sys.argv[1],sys.argv[2]
site=S.SITES[S.CORRIDOR]; ld=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
d=sqlite3.connect(f'file:data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{W}.db?mode=ro',uri=True)
ours=Counter(); mv=Counter()
for o,de,ts in d.execute("select origin_leg_id,destination_leg_id,timestamp_real from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
    if ld[o]!=A: continue
    m=datetime.fromisoformat(ts).time().replace(second=0,microsecond=0); ours[m]+=1
mins=sorted(m for m in mio if ours and min(ours)<=m<=max(ours))
groups=[]; cur=None
for m in mins:
    g=sum(v for k,v in mio[m].items() if k[0]==A and k[1] in ('thru','left'))
    if g>0 and (cur is None or cur[-1][1]==0 or True) and (cur is None or sum(v for k,v in mio[cur[-1][0]].items() if k[0]==A and k[1] in('thru','left'))==0):
        cur=[]; groups.append(cur)
    if cur is None: cur=[]; groups.append(cur)
    cur.append((m,g))
diffs=[]
for gr in groups:
    ms=[m for m,_ in gr]; r=sum(sum(v for k,v in mio[m].items() if k[0]==A) for m in ms); o=sum(ours[m] for m in ms)
    diffs.append((o-r,ms[0].strftime('%H:%M'),len(ms),r,o))
ds=sorted(x[0] for x in diffs)
print(W,A,'cycles',len(diffs),'total',sum(ds),'median',ds[len(ds)//2],'cycles>=+5:',sum(1 for x in ds if x>=5),'carry',sum(x for x in ds if x>=5))
print('  hist',sorted(Counter(ds).items()))
print('  worst',sorted(diffs,reverse=True)[:8])
