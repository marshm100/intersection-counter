import sys, sqlite3
from collections import Counter
from datetime import datetime, timedelta, time as dtime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S
from backend.services.journey_labels import list_clips, list_labels
mio=S.load_miovision(2,S.SITES[S.CORRIDOR])
D={26:'WB',27:'SB',28:'EB',29:'NB'}
MV={(28,29):'right',(28,26):'thru',(28,27):'left',(27,29):'thru',(27,28):'right',(27,26):'left',(29,27):'thru',(29,26):'right',(29,28):'left',(26,28):'thru',(26,27):'right',(26,29):'left'}
start=datetime(2026,5,12,0,0,2); fps=25
for clip in list_clips('97a7849a'):
    if clip['camera_id']!=2: continue
    labs=[l for l in list_labels('97a7849a',clip['clip_id']) if l.get('entry_frame') is not None and l.get('exit_frame') is not None]
    t0=start+timedelta(seconds=clip['start_frame']/fps); t1=start+timedelta(seconds=clip['end_frame']/fps)
    # whole minutes fully inside the clip
    m=(t0+timedelta(seconds=59)).replace(second=0,microsecond=0)
    mins=[]
    while m+timedelta(minutes=1)<=t1: mins.append(m); m+=timedelta(minutes=1)
    print(f"\n{clip['clip_id']}  clip {t0.time()}-{t1.time()}  full minutes {[x.strftime('%H:%M') for x in mins]}")
    lab=Counter(); 
    for l in labs:
        tm=start+timedelta(seconds=l['entry_frame']/fps)
        if any(x<=tm<x+timedelta(minutes=1) for x in mins):
            k=(D[l['entry_leg_id']],MV.get((l['entry_leg_id'],l['exit_leg_id']),'?')); lab[k]+=1
    db=f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_study_1600.db'
    c=sqlite3.connect(f'file:{db}?mode=ro',uri=True); ours=Counter()
    for o,mv,ts in c.execute("select origin_leg_id,movement,timestamp_real from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
        if ts is None: continue
        tm=datetime.fromisoformat(ts)
        if any(x<=tm<x+timedelta(minutes=1) for x in mins): ours[(D.get(o),S.NORM.get(mv,mv))]+=1
    mo=Counter()
    for x in mins:
        for k,v in mio.get(dtime(x.hour,x.minute),{}).items(): mo[k]+=v
    keys=sorted(set(lab)|set(mo)|set(ours), key=lambda k:-mo.get(k,0))
    print(f"   {'cell':10} {'mio':>4} {'labels':>6} {'ours':>5}")
    for k in keys:
        if mo[k] or lab[k] or ours[k]: print(f"   {k[0]+' '+k[1]:10} {mo[k]:4} {lab[k]:6} {ours[k]:5}")
