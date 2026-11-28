"""Sequential doubles: counted track B born within GAP s after counted track A died, B's first point within
D box-widths of A's last point extrapolated by A's end velocity over the gap. Per window: count, by A's approach,
by (A movement, B movement). Read-only. usage: seqdbl.py [GAP] [D] [--dump]"""
import sys, sqlite3, numpy as np
from collections import Counter
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ, v2_score_dev as S
GAP=float(sys.argv[1]) if len(sys.argv)>1 else 3.0; D=float(sys.argv[2]) if len(sys.argv)>2 else 1.5
site=S.SITES[S.CORRIDOR]; ld=S.leg_dir_for(S.CORRIDOR,2,site)
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
chash=con.execute('select content_hash from videos where video_id=2').fetchone()[0]
for W in ('study_0700','study_1100','study_1600'):
    db,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
    d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    ev={int(t):(o,de,s) for t,o,de,s in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id,coalesce(posterior_source,'-') from vehicle_events where camera_id=2 and coalesce(rejected,0)=0")}
    r=rows[np.isin(rows[:,0],list(ev))]; r=r[np.lexsort((r[:,1],r[:,0]))]
    ids,st=np.unique(r[:,0],return_index=True); en=np.r_[st[1:],len(r)]
    T={}
    for t,a,b in zip(ids.astype(int),st,en):
        q=r[a:b]; k=max(0,len(q)-10); df=q[-1,1]-q[k,1]
        v=(q[-1,2:4]-q[k,2:4])/df if df>0 else np.zeros(2)
        k2=min(len(q)-1,9); d2=q[k2,1]-q[0,1]; v0=(q[k2,2:4]-q[0,2:4])/d2 if d2>0 else np.zeros(2)
        T[t]=(q[0,1],q[-1,1],q[0,2:4],q[-1,2:4],v,np.median(q[-10:,4]),np.median(q[:10,4]),v0)
    starts=sorted((T[t][0],t) for t in T); sf=np.array([s for s,_ in starts])
    hits=[]
    for a,(f0,f1,p0,p1,v,wa,_,_v0) in T.items():
        i=np.searchsorted(sf,f1+1); j=np.searchsorted(sf,f1+GAP*25,side='right')
        best=None
        for _,b in starts[i:j]:
            g=T[b][0]-f1; pred=p1+v*g; dist=np.hypot(*(T[b][2]-pred))/max(wa,T[b][6])
            vb=T[b][7]; na,nb=np.hypot(*v),np.hypot(*vb)
            if na<0.05*wa or nb<0.05*T[b][6] or (v@vb)/(na*nb)<0.7: continue
            if dist<=D and (best is None or dist<best[0]): best=(dist,b)
        if best: hits.append((a,best[1]))
    used=set(); hh=[]
    for a,b in sorted(hits,key=lambda x:T[x[0]][1]):
        if b in used: continue
        used.add(b); hh.append((a,b))
    print(W,'seq pairs',len(hh),' by A approach',dict(Counter(ld[ev[a][0]] for a,b in hh)),' by B approach',dict(Counter(ld[ev[b][0]] for a,b in hh)))
    print('   top kinds',Counter((f'{ev[a][0]}>{ev[a][1]}',f'{ev[b][0]}>{ev[b][1]}') for a,b in hh).most_common(8))
    if '--dump' in sys.argv: print('  ',[(a,b,int(T[a][1])) for a,b in hh if ld[ev[a][0]]=='EB' or ld[ev[b][0]]=='EB'][:60])
