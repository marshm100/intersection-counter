"""What-if: re-time each counted event at its track's LAST crossing of its origin gate line (the stop-line departure,
what a TMC counts) instead of timestamp_real (= the frame the origin was ASSIGNED, usually first sighting + a few
frames - pipeline.py:1223/1530/2152). Events with no origin-line crossing in the dump keep their time.
Rescores cam2 movement + approach 5/95 both ways. Read-only.  usage: retime.py [CAM=2] [STEM=sf0] [PREFIX=sf0_]"""
import sys, json, sqlite3, cv2, numpy as np
from collections import Counter
from datetime import datetime, timedelta, time as dtime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S, eval_journeys as EJ
from collections import defaultdict
CAM=int(sys.argv[1]) if len(sys.argv)>1 else 2; STEM=sys.argv[2] if len(sys.argv)>2 else 'sf0'; PRE=sys.argv[3] if len(sys.argv)>3 else 'sf0_'
site=S.SITES[S.CORRIDOR]; ld=S.leg_dir_for(S.CORRIDOR,CAM,site); mio=S.load_miovision(CAM,site)
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
vid,path,chash,st=con.execute('select video_id,path,content_hash,recording_start_datetime from videos where camera_id=?',(CAM,)).fetchone()
start=datetime.fromisoformat(st); fps=cv2.VideoCapture(path).get(cv2.CAP_PROP_FPS)
gates={lid:np.array(json.loads(g),float) for lid,g in con.execute('select leg_id,gate_segment from legs where camera_id=?',(CAM,))}
def approach(pm):
    out=defaultdict(lambda: defaultdict(int))
    for m,c in pm.items():
        for k,v in c.items(): out[m][k[0]]+=v
    return out
for W in ('study_0700','study_1100','study_1600'):
    db,rows=EJ.locate(STEM,{CAM:PRE},CAM,W,chash)
    order=np.lexsort((rows[:,1],rows[:,0])); rows=rows[order]
    tids,first=np.unique(rows[:,0],return_index=True); bounds=dict(zip(tids.astype(int),zip(first,list(first[1:])+[len(rows)])))
    d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    ev=d.execute("select vehicle_track_id,origin_leg_id,movement,timestamp_real from vehicle_events where camera_id=? and coalesce(rejected,0)=0",(CAM,)).fetchall()
    old,new=[],[]; shift=[]; moved=0; nocross=0
    for tid,o,mv,ts in ev:
        if ts is None: continue
        t0=datetime.fromisoformat(ts); t1=t0
        if tid in bounds and o in gates:
            i,j=bounds[tid]; r=rows[i:j]; p=np.c_[r[:,2],r[:,3]+r[:,5]/2]; a,b=gates[o]
            s=np.sign((b[0]-a[0])*(p[:,1]-a[1])-(b[1]-a[1])*(p[:,0]-a[0])); k=np.where(s[:-1]*s[1:]<0)[0]
            q=(p[k]+p[k+1])/2; u=((q-a)@(b-a))/np.dot(b-a,b-a); k=k[(u>=-0.15)&(u<=1.15)]
            if len(k): t1=start+timedelta(seconds=r[k[-1]+1,1]/fps)
            else: nocross+=1
        else: nocross+=1
        shift.append((t1-t0).total_seconds())
        if t0.replace(minute=t0.minute//15*15,second=0,microsecond=0)!=t1.replace(minute=t1.minute//15*15,second=0,microsecond=0): moved+=1
        old.append({'origin_leg':o,'movement':mv,'wallclock':t0.isoformat()}); new.append({'origin_leg':o,'movement':mv,'wallclock':t1.isoformat()})
    lo,hi=site['windows'][W]; mins=[m for m in (dtime(h,x) for h in range(lo,hi) for x in range(60)) if m in mio]
    res=[]
    for evs in (old,new):
        pm=S.per_min_from_events(evs,ld)
        res.append((S.compliance(S.score_cells(pm,mio,mins))['pct'], S.compliance(S.score_cells(approach(pm),approach(mio),mins))['pct']))
    sh=np.array(shift)
    print(f'cam{CAM} {W}: events {len(ev)}  shift s median {np.median(sh):.1f} p90 {np.percentile(sh,90):.1f} max {sh.max():.0f}  '
          f'no origin-line crossing {nocross}  change 15-min bin {moved}')
    print(f'    movement / approach 5/95: as stamped {res[0][0]} / {res[0][1]}   re-timed {res[1][0]} / {res[1][1]}')
    # phase split (phase_split.py logic) on both timings, for env PHASE=WB|EB
    import os
    A=os.environ.get('PHASE')
    if A:
        for name,evs in (('stamped',old),('re-timed',new)):
            pm=S.per_min_from_events(evs,ld); acc=defaultdict(lambda:[0,0])
            for m in mins:
                k='red' if mio[m].get((A,'thru'),0)+mio[m].get((A,'left'),0)<=2 else 'green'
                for mv in ('right','thru','left'): acc[(k,mv)][0]+=mio[m].get((A,mv),0); acc[(k,mv)][1]+=pm.get(m,{}).get((A,mv),0)
            print(f'    {A} {name:8}', ' | '.join(f'{k} {mv} {v[0]}/{v[1]} ({v[1]-v[0]:+d})' for (k,mv),v in sorted(acc.items())))
