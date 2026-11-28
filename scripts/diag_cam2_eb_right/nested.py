"""Counted-track pairs that sit on one car: for >= MINF co-frames, intersection / smaller box area >= C.
Prints per window: pairs, by approach of the later-born track, and the approach excess vs Miovision. Read-only.
usage: nested.py [C] [MINF]"""
import sys, sqlite3, numpy as np
from collections import Counter, defaultdict
from datetime import datetime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ, v2_score_dev as S
C=float(sys.argv[1]) if len(sys.argv)>1 else 0.7; MINF=int(sys.argv[2]) if len(sys.argv)>2 else 12
MOVE=float(sys.argv[3]) if len(sys.argv)>3 else 1.0; VAR=float(sys.argv[4]) if len(sys.argv)>4 else 0.5
DUMP='--dump' in sys.argv
site=S.SITES[S.CORRIDOR]; ld=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
chash=con.execute('select content_hash from videos where video_id=2').fetchone()[0]
for W in ('study_0700','study_1100','study_1600'):
    db,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
    d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    ev={int(t):(ld[o],ld[de],ts) for t,o,de,ts in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id,timestamp_real from vehicle_events where camera_id=2 and coalesce(rejected,0)=0")}
    r=rows[np.isin(rows[:,0],list(ev))]; r=r[np.argsort(r[:,1],kind='stable')]
    fr=r[:,1].astype(np.int64); cut=np.r_[0,np.where(np.diff(fr))[0]+1,len(r)]
    co=Counter(); pos={}
    for i in range(len(cut)-1):
        g=r[cut[i]:cut[i+1]]
        if len(g)<2: continue
        x0=g[:,2]-g[:,4]/2; x1=g[:,2]+g[:,4]/2; y0=g[:,3]-g[:,5]/2; y1=g[:,3]+g[:,5]/2; A=g[:,4]*g[:,5]
        iw=np.clip(np.minimum(x1[:,None],x1[None])-np.maximum(x0[:,None],x0[None]),0,None)
        ih=np.clip(np.minimum(y1[:,None],y1[None])-np.maximum(y0[:,None],y0[None]),0,None)
        cr=iw*ih/np.minimum(A[:,None],A[None])
        a,b=np.where(np.triu(cr>=C,1))
        for p,q in zip(a,b):
            if g[p,0]>g[q,0]: p,q=q,p
            k=(int(g[p,0]),int(g[q,0])); co[k]+=1
            pos.setdefault(k,[]).append((g[p,2],g[p,3],g[q,2],g[q,3],min(g[p,4],g[q,4])))
    pairs=[]
    for k,v in co.items():
        if v<MINF: continue
        P=np.array(pos[k]); w=np.median(P[:,4])
        move=min(np.hypot(*(P[-1,0:2]-P[0,0:2])),np.hypot(*(P[-1,2:4]-P[0,2:4])))
        off=P[:,0:2]-P[:,2:4]; var=np.hypot(*(off.max(0)-off.min(0)))
        if move>=MOVE*w and var<=VAR*w: pairs.append(k)
    # one extra count per connected group of nested tracks
    adj=defaultdict(set)
    for a,b in pairs: adj[a].add(b); adj[b].add(a)
    seen=set(); extra=Counter(); groups=[]
    for t in adj:
        if t in seen: continue
        st=[t]; comp=[]
        while st:
            u=st.pop()
            if u in seen: continue
            seen.add(u); comp.append(u); st+=list(adj[u])
        groups.append(comp)
        for u in comp[1:]: extra[ev[u][0]]+=1   # crude: approach of all but one member
    if DUMP: print(W,sorted(pairs))
    same=sum(1 for a,b in pairs if ev[a][:2]==ev[b][:2])
    ours=Counter(v[0] for v in ev.values())
    ref=Counter(); 
    for m,c in mio.items():
        pass
    tt=[datetime.fromisoformat(v[2]).time() for v in ev.values()]; lo,hi=min(tt),max(tt)
    for m,c in mio.items():
        if lo<=m<=hi:
            for k,v in c.items(): ref[k[0]]+=v
    print(W,f'pairs {len(pairs)} (same movement {same}) groups {len(groups)} extra-by-approach',dict(extra))
    print('   ours-mio by approach', {a:ours[a]-ref[a] for a in ('NB','SB','EB','WB')})
