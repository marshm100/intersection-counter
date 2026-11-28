"""Score a hand-count session (frontend/handcount.html) against Miovision and ours, per minute, EB-right.
Also matches each press to our counted EB-right events within TOL s. Our time is the track's first crossing of the
exit (NB-out, leg 29) line from the dump, else the event timestamp (which is the track's FIRST SIGHTING, often in the
queue - Step 9.139: matching on it made 3 real cars look unmatched). Presses lead the exit crossing by ~1-2 s. Read-only.
usage: handcount_compare.py SESSION [WINDOW=study_0700] [TOL=4]"""
import sys, json, sqlite3
from datetime import datetime, timedelta, time as dtime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S
sess=sys.argv[1]; W=sys.argv[2] if len(sys.argv)>2 else 'study_0700'; TOL=float(sys.argv[3]) if len(sys.argv)>3 else 4
doc=json.load(open(f'data/projects/97a7849a/hand_counts/{sess}.json'))
site=S.SITES[S.CORRIDOR]; ld=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
start=datetime.fromisoformat(con.execute('select recording_start_datetime from videos where video_id=?',(doc['video_id'],)).fetchone()[0])
wall=lambda t: start+timedelta(seconds=t)
f0=datetime.combine(start.date(),dtime.fromisoformat(doc['from_wall'])); f1=datetime.combine(start.date(),dtime.fromisoformat(doc['to_wall']))
taps=[(wall(t['t']),t['kind']) for t in doc['taps'] if f0<=wall(t['t'])<f1]
db=f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{W}.db'
d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
ours=[(datetime.fromisoformat(ts),int(tid),src or '-') for tid,o,de,ts,src in d.execute(
    "select vehicle_track_id,origin_leg_id,destination_leg_id,timestamp_real,posterior_source from vehicle_events "
    "where camera_id=2 and coalesce(rejected,0)=0") if (o,de)==(28,29)]
ours=[e for e in ours if f0<=e[0]<f1]
import numpy as np, cv2
sys.path.insert(0,'scripts'); import eval_journeys as EJ
path,chash=con.execute('select path,content_hash from videos where video_id=2').fetchone()
fps=cv2.VideoCapture(path).get(cv2.CAP_PROP_FPS); _,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
a,b=np.array(json.loads(con.execute('select gate_segment from legs where leg_id=29').fetchone()[0]),float)
def exit_time(tid,fallback):
    r=rows[rows[:,0]==tid]; r=r[np.argsort(r[:,1])]; p=np.c_[r[:,2],r[:,3]+r[:,5]/2]
    s=np.sign((b[0]-a[0])*(p[:,1]-a[1])-(b[1]-a[1])*(p[:,0]-a[0])); i=np.where(s[:-1]*s[1:]<0)[0]
    return start+timedelta(seconds=r[i[0]+1,1]/fps) if len(i) else fallback
ours=[(exit_time(tid,t),tid,src+('' if exit_time(tid,None) else ' [no exit crossing: first-sighting time]')) for t,tid,src in ours]
print(f'{sess}  {doc["from_wall"]}-{doc["to_wall"]}  presses in window {len(taps)}')
print('minute   Mio  ours | hand: red green other  (red+green)')
m=f0
while m<f1:
    n=m+timedelta(minutes=1); c=lambda k: sum(1 for t,kk in taps if kk==k and m<=t<n)
    print(f'{m:%H:%M}   {mio.get(m.time(),{}).get(("EB","right"),0):3}  {sum(1 for e in ours if m<=e[0]<n):4} | '
          f'{c("red"):9} {c("green"):5} {c("other"):5}  ({c("red")+c("green")})')
    m=n
# one-to-one greedy match by time
used=set(); pairs=[]
for t,k in sorted(taps):
    best=min((abs((e[0]-t).total_seconds()),i) for i,e in enumerate(ours) if i not in used) if len(used)<len(ours) else None
    if best and best[0]<=TOL: used.add(best[1]); pairs.append((t,k,ours[best[1]]))
    else: pairs.append((t,k,None))
print('\npress -> our track (|dt| <= %gs)'%TOL)
for t,k,e in pairs: print(f'  {t:%H:%M:%S} {k:5} -> ' + (f'track {e[1]} at {e[0]:%H:%M:%S} ({e[2]})' if e else 'none (we missed it)'))
print('ours with no press:', [(f'{e[0]:%H:%M:%S}',e[1],e[2]) for i,e in enumerate(ours) if i not in used])
