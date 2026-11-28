"""For every counted event of approach A in the given minutes (1600 window), find other COUNTED tracks that
share its car: co-temporal box overlap (double), or a hand-off (one dies, the other is born within 1.5 s
and 1.5 box widths: fragment double). Also flag box-size jumps (hop). Read-only."""
import sys, sqlite3, numpy as np
from datetime import datetime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
W=sys.argv[1] if len(sys.argv)>1 else 'study_1600'
APP=sys.argv[2] if len(sys.argv)>2 else 'EB'
MINS=sys.argv[3].split(',') if len(sys.argv)>3 else ['17:14','16:37']
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
chash=con.execute('select content_hash from videos where video_id=2').fetchone()[0]
db,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
legdir={'26':'WB','27':'NB','28':'EB','29':'SB'}  # by entry leg id (from worst.py output)
ev=d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id,timestamp_real,coalesce(posterior_source,'-') from vehicle_events where camera_id=2 and coalesce(rejected,0)=0").fetchall()
counted={int(t):(o,de,ts,s) for t,o,de,ts,s in ev}
tr={}
order=np.lexsort((rows[:,1],rows[:,0])); rows=rows[order]
ids,starts=np.unique(rows[:,0],return_index=True)
for i,t in enumerate(ids):
    if int(t) in counted:
        e=starts[i+1] if i+1<len(starts) else len(rows); tr[int(t)]=rows[starts[i]:e]
def iou(a,b):
    ax0,ay0,ax1,ay1=a[0]-a[2]/2,a[1]-a[3]/2,a[0]+a[2]/2,a[1]+a[3]/2
    bx0,by0,bx1,by1=b[0]-b[2]/2,b[1]-b[3]/2,b[0]+b[2]/2,b[1]+b[3]/2
    iw=max(0,min(ax1,bx1)-max(ax0,bx0)); ih=max(0,min(ay1,by1)-max(ay0,by0)); I=iw*ih
    return I/(a[2]*a[3]+b[2]*b[3]-I+1e-9)
FPS=float(sys.argv[4]) if len(sys.argv)>4 else 15.0
sel=[t for t,(o,de,ts,s) in counted.items() if legdir.get(str(o))==APP and datetime.fromisoformat(ts).strftime('%H:%M') in MINS]
for t in sorted(sel):
    r=tr[t]; f0,f1=r[0,1],r[-1,1]; o,de,ts,s=counted[t]
    w=r[:,4]; jump=np.max(np.abs(np.diff(np.log(w)))) if len(w)>1 else 0
    span=np.hypot(*(r[:,2:4].max(0)-r[:,2:4].min(0)))/np.median(w)
    notes=[]
    for u,q in tr.items():
        if u==t: continue
        if q[-1,1]<f0-FPS*1.5 or q[0,1]>f1+FPS*1.5: continue
        fa,ia,ib=np.intersect1d(r[:,1],q[:,1],return_indices=True)
        if len(fa):
            ov=np.array([iou(r[i,2:6],q[j,2:6]) for i,j in zip(ia,ib)]); n=(ov>0.3).sum()
            if n>=FPS*0.5: notes.append(f'OVERLAP {u}({counted[u][0]}->{counted[u][1]}) {n}fr max{ov.max():.2f}')
        for a,b,lab in ((r[-1],q[0],'->'),(q[-1],r[0],'<-')):
            if 0<=b[1]-a[1]<=FPS*1.5 and np.hypot(b[2]-a[2],b[3]-a[3])<=1.5*max(a[4],b[4]):
                notes.append(f'HANDOFF{lab}{u}({counted[u][0]}->{counted[u][1]}) gap{int(b[1]-a[1])}')
    print(f'{t} {o}->{de} {s:15s} {datetime.fromisoformat(ts).strftime("%H:%M:%S")} f{int(f0)}-{int(f1)} ({(f1-f0)/FPS:.0f}s) w{np.median(w):.0f} span{span:.1f}w maxlogjump{jump:.2f}', '; '.join(notes))
