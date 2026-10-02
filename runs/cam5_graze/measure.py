"""cam5 east-line graze: post-exit geometry of counted 39->36 vs 39->37 tracks (nc2 dumps)."""
import sys, sqlite3, json, math, numpy as np
sys.argv=["x"]; sys.path.insert(0,"scripts"); sys.path.insert(0,".")
import eval_journeys as e
from backend.services.entry_gates import all_crossings
con=sqlite3.connect("data/projects/97a7849a/project.db")
seg={r[0]:json.loads(r[1]) for r in con.execute("select leg_id,gate_segment from legs where camera_id=5")}
chash="2076a59b59f93fbd898f690e7aa055d5a35cc923f626489772900ffef2acd49e"
cx=np.mean([p[0] for s in seg.values() for p in s]); cy=np.mean([p[1] for s in seg.values() for p in s])
gates={}
for lg,(p1,p2) in seg.items():
    mx,my=(p1[0]+p2[0])/2,(p1[1]+p2[1])/2
    nx,ny=-(p2[1]-p1[1]),(p2[0]-p1[0]); L=math.hypot(nx,ny); nx/=L; ny/=L
    if (cx-mx)*nx+(cy-my)*ny<0: nx,ny=-nx,-ny
    gates[lg]=(tuple(p1),tuple(p2),(nx,ny))
def post(pts, f, lg):
    p1,p2,(nx,ny)=gates[lg]; ux,uy=p2[0]-p1[0],p2[1]-p1[1]; L=math.hypot(ux,uy); ux/=L; uy/=L
    after=[(x,y) for fr,x,y in pts if fr>=f]
    if not after: return None
    x0,y0=after[0]; x1,y1=after[-1]
    out=-((x1-x0)*nx+(y1-y0)*ny); along=abs((x1-x0)*ux+(y1-y0)*uy)
    return round(out), round(along), len(after)
W=sys.argv[1] if len(sys.argv)>1 else "study_0700"
for w in ["study_0700","study_1100","study_1600"]:
    db,rows=e.locate("nc2",{},5,w,chash)
    d=sqlite3.connect(str(db))
    fate={r[0]:r[1:] for r in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id,gate_tag,last_x,last_y from track_fates where camera_id=5 and disposition='counted'")}
    tr={}
    for r in rows:
        tr.setdefault(int(r[0]),[]).append((float(r[1]),float(r[2]),float(r[3])))
    print("==",w, "dump cols", rows.shape)
    stats={36:[],37:[]}
    for tid,(o,dd,tag,lx,ly) in fate.items():
        if o!=39 or dd not in (36,37) or tag!="full" or tid not in tr: continue
        pts=sorted(tr[tid]); cr=all_crossings(pts,gates,10)
        ex=[c for c in cr if not c[2] and c[1]==dd]
        if not ex: continue
        m=post(pts,ex[-1][0],dd)
        if m: stats[dd].append((tid,)+m+(round(lx),round(ly),[c[1] for c in cr]))
    for dd in (36,37):
        s=stats[dd]
        if dd==37:
            o=sorted(x[1] for x in s); a=sorted(x[2] for x in s)
            q=lambda v:[v[int(len(v)*p)] for p in (.05,.25,.5,.75,.95)]
            print(" thru 39->37 n",len(s)," out",q(o)," along",q(a))
        else:
            for x in sorted(s,key=lambda x:x[4]): print("  right",x)
