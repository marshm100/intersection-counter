import sys, sqlite3, json, math, numpy as np
sys.argv=["x"]; sys.path.insert(0,"scripts"); sys.path.insert(0,".")
exec(open("runs/cam5_graze/measure.py").read().split("W=sys.argv")[0])
import backend.config as cfg
from backend.services.entry_gates import classify_pair, rides_line_after, pair_crossings
db,rows=e.locate("nc2",{},5,"study_0700",chash)
print(rows[:2])
tr={}
for r in rows: tr.setdefault(int(r[0]),[]).append(r)
for tid in (8104,5116,1501,772,408,4250,6768):
    a=np.array(sorted(tr[tid],key=lambda r:r[1]))
    f,x,y,w,h=a[:,1],a[:,2],a[:,3],a[:,4],a[:,5]
    L=[(f[i],x[i]-w[i]/2,y[i]+h[i]/2) for i in range(len(f))]
    R=[(f[i],x[i]+w[i]/2,y[i]+h[i]/2) for i in range(len(f))]
    cfg.EXIT_GRAZE_SKIP=False; off=classify_pair(L,R,gates,10)
    cfg.EXIT_GRAZE_SKIP=True; on=classify_pair(L,R,gates,10)
    v=pair_crossings(L,R,gates,10)
    mid=[(f[i],x[i],y[i]+h[i]/2) for i in range(len(f))]
    print(tid,"off",off[:2],off[6],"on",on[:2],on[6],"cross",[(round(c[0]),c[1],c[2]) for c in v],
          [rides_line_after(mid,c,gates) for c in v if not c[2]])
