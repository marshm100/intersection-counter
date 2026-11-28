"""Car-by-car view of a hand-count session: for each press and each of our EB-right events, which tracks are at the
EB gate line (leg 28) at that moment, and when each of our tracks crosses it. Read-only.
usage: hc_cars.py SESSION [WINDOW=study_0700] [TIDS]"""
import sys, json, sqlite3, cv2, numpy as np
from datetime import datetime, timedelta
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
sess=sys.argv[1]; W=sys.argv[2] if len(sys.argv)>2 else 'study_0700'
doc=json.load(open(f'data/projects/97a7849a/hand_counts/{sess}.json'))
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
path,chash,st=con.execute('select path,content_hash,recording_start_datetime from videos where video_id=2').fetchone()
start=datetime.fromisoformat(st); fps=cv2.VideoCapture(path).get(cv2.CAP_PROP_FPS)
gates={lid:np.array(json.loads(g),float) for lid,g in con.execute('select leg_id,gate_segment from legs where camera_id=2')}
db,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
ev={int(t):(o,de,ts,src) for t,o,de,ts,src in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id,timestamp_real,posterior_source from vehicle_events where camera_id=2 and coalesce(rejected,0)=0")}
def side(p,g): a,b=g; return np.sign((b[0]-a[0])*(p[:,1]-a[1])-(b[1]-a[1])*(p[:,0]-a[0]))
def crossings(t):
    r=rows[rows[:,0]==t]; r=r[np.argsort(r[:,1])]; p=np.c_[r[:,2],r[:,3]+r[:,5]/2]; out=[]
    for lid,g in gates.items():
        s=side(p,g); idx=np.where(s[:-1]*s[1:]<0)[0]
        for i in idx:
            # within segment extent (loose)
            q=(p[i]+p[i+1])/2; a,b=g; u=np.dot(q-a,b-a)/np.dot(b-a,b-a)
            if -0.15<=u<=1.15: out.append((r[i+1,1]/fps,lid))
    return r,sorted(out)
def wall(s): return (start+timedelta(seconds=s)).strftime('%H:%M:%S.%f')[:-4]
g28=gates[28]
def near_gate(tsec,rad=2.0,dist=40):
    f0,f1=(tsec-rad)*fps,(tsec+rad)*fps; sel=rows[(rows[:,1]>=f0)&(rows[:,1]<=f1)]
    out={}
    for t in np.unique(sel[:,0]).astype(int):
        r=sel[sel[:,0]==t]; p=np.c_[r[:,2],r[:,3]+r[:,5]/2]; a,b=g28
        u=np.clip(((p-a)@(b-a))/np.dot(b-a,b-a),0,1); dd=np.linalg.norm(p-(a+np.outer(u,b-a)),axis=1)
        if dd.min()<dist: out[t]=round(float(dd.min()),1)
    return out
print('gate 28',g28.tolist(),'fps',fps)
print('\nPRESSES')
for tp in doc['taps']:
    print(f"  {wall(tp['t'])} {tp['kind']:5} near EB line (+-2s, <40px):",
          {t:(dd, ('EV %s->%s %s'%(ev[t][0],ev[t][1],ev[t][3])) if t in ev else 'not counted') for t,dd in near_gate(tp['t']).items()})
tids=[int(x) for x in sys.argv[3].split(',')] if len(sys.argv)>3 else []
print('\nOUR TRACKS')
for t in tids:
    r,cr=crossings(t)
    print(f"  {t}: life {wall(r[0,1]/fps)} -> {wall(r[-1,1]/fps)}  n={len(r)}  start({r[0,2]:.0f},{r[0,3]+r[0,5]/2:.0f}) end({r[-1,2]:.0f},{r[-1,3]+r[-1,5]/2:.0f})"
          f"  event={ev.get(t)}  crossings={[(wall(s),l) for s,l in cr]}")
