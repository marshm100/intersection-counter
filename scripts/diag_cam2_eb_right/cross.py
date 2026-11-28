"""Counted tracks of one approach in a minute range: where/when each first crosses its entry line (box bottom-centre),
or 'no-cross' with its first point. Read-only. usage: cross.py WINDOW ENTRY_LEG HH:MM-HH:MM"""
import sys, sqlite3, json, numpy as np
from datetime import datetime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
W,LEG,RNG=sys.argv[1],int(sys.argv[2]),sys.argv[3]; a,b=RNG.split('-')
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
chash=con.execute('select content_hash from videos where video_id=2').fetchone()[0]
g=np.array(json.loads(con.execute('select gate_segment from legs where leg_id=?',(LEG,)).fetchone()[0]))
db,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
ev=[(int(t),o,de,ts,s) for t,o,de,ts,s in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id,timestamp_real,coalesce(posterior_source,'-') from vehicle_events where camera_id=2 and coalesce(rejected,0)=0 and origin_leg_id=?",(LEG,))]
ev=[e for e in ev if a<=datetime.fromisoformat(e[3]).strftime('%H:%M')<=b]
p0,p1=g; n=np.array([-(p1-p0)[1],(p1-p0)[0]]); L=np.linalg.norm(p1-p0)
out=[]
for t,o,de,ts,s in ev:
    r=rows[rows[:,0]==t]; r=r[np.argsort(r[:,1])]
    pt=np.c_[r[:,2],r[:,3]+r[:,5]/2]; sd=(pt-p0)@n
    k=np.where(np.sign(sd[:-1])!=np.sign(sd[1:]))[0]
    if len(k): i=k[0]+1; u=((pt[i]-p0)@(p1-p0))/L**2; tag='X'
    else: i=0; u=((pt[0]-p0)@(p1-p0))/L**2; tag='-'
    out.append((int(r[i,1]),t,f'{o}>{de}',s,tag,u,r[i,4],int(r[0,1]),int(r[-1,1])))
out.sort()
prev=None
for f,t,m,s,tag,u,w,f0,f1 in out:
    dt='' if prev is None else f'+{(f-prev)/25:.1f}s'; prev=f
    print(f'f{f} {dt:>7} {t:6d} {m} {s:15s} {tag} u={u:.2f} w{w:.0f} life {(f0-f)/25:+.0f}s..{(f1-f)/25:+.0f}s')
print(len(out),'events')
