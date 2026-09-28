"""Dry-run price of arm cg1 (config.CHAIN_GUARD_ALL_PARTIALS, keep-one per chain) on the 12 gx2
windows: removes the events the guard would reject, AFTER the merge (so the arm is the honest price).
Usage: .venv\Scripts\python.exe -X utf8 scripts/research_chain_partials.py
"""
import sqlite3, sys
import numpy as np
from collections import defaultdict
from datetime import time as dtime
sys.path.insert(0,"scripts"); sys.path.insert(0,".")
import v2_score_dev as V
from backend.services.rule595 import score_cells
from backend.services.detection_cache import parquet_path
from backend.services.pass2_replay import load_dump, tracks_dir
from backend.services.two_pass import _pinned_gates
import backend.config as _cfg
_cfg.CHAIN_GUARD_ALL_PARTIALS = True
from backend.services.turn_merge import bound_chain_pairs
PROJ="97a7849a"; B="data/projects/97a7849a/_replay_scratch/fleet_20260908/"
W=[(1,"study_0700"),(1,"study_1600"),(2,"study_0700"),(2,"study_1100"),(2,"study_1600"),(3,"study_0600"),(4,"study_0700"),(4,"study_1100"),(4,"study_1600"),(5,"study_0700"),(5,"study_1100"),(5,"study_1600")]
site=V.SITES[V.CORRIDOR]; con=sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",uri=True)
def appr(pm):
    o=defaultdict(lambda: defaultdict(int))
    for m,c in pm.items():
        for k,v in c.items(): o[m][k[0]]+=v
    return o
pct=lambda r:100*sum(x["ok"] for x in r)/len(r)
T=defaultdict(float); C=defaultdict(lambda: defaultdict(float))
for cam,w in W:
    chash,fps=con.execute("SELECT content_hash,fps FROM videos WHERE camera_id=?",(cam,)).fetchone()
    rows=np.asarray(load_dump(tracks_dir(parquet_path(PROJ,cam,chash,w)))); gates,_=_pinned_gates(PROJ,cam,rows)
    tag=f"vl3_{w}" if cam>3 else w; db=f"{B}gx2_cam{cam}_{tag}.db"
    d=sqlite3.connect(f"file:{db}?mode=ro",uri=True)
    ftag={(v,t):g for v,t,g in d.execute("SELECT video_id,vehicle_track_id,gate_tag FROM track_fates")}
    ev=d.execute("SELECT event_id,video_id,vehicle_track_id,COALESCE(posterior_source,'') FROM vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0 AND vehicle_track_id>=0",(cam,)).fetchall()
    evs=[(e[0],e[2],e[3]) for e in ev]
    _cm,drop=bound_chain_pairs(evs,rows,float(fps),gates)
    lo,hi=site["windows"][w]; mio=V.load_miovision(cam,site); mm=[m for m in (dtime(h,x) for h in range(lo,hi) for x in range(60)) if m in mio]
    ld=V.leg_dir_for(V.CORRIDOR,cam,site)
    base=[]; kept=[]
    for eid,o,mv,ts in d.execute("SELECT event_id,origin_leg_id,movement,timestamp_real FROM vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0",(cam,)):
        if ts is None: continue
        e={"origin_leg":o,"movement":mv,"wallclock":ts}; base.append(e)
        if eid not in drop: kept.append(e)
    r={}
    for k,evl in (("base",base),("rule",kept)):
        pm=V.per_min_from_events(evl,ld); r[k]=(pct(score_cells(pm,mio,mm)),pct(score_cells(appr(pm),appr(mio),mm)))
        T[k+"m"]+=r[k][0]; T[k+"a"]+=r[k][1]; C[cam][k+"m"]+=r[k][0]; C[cam][k+"a"]+=r[k][1]
    C[cam]["n"]+=1
    print(f"cam{cam} {w}: drop {len(drop)} | movement {r['base'][0]:.1f} -> {r['rule'][0]:.1f}  approach {r['base'][1]:.1f} -> {r['rule'][1]:.1f}",flush=True)
print(f"\nFLEET movement {T['basem']/12:.2f} -> {T['rulem']/12:.2f} ({(T['rulem']-T['basem'])/12:+.2f})  approach {T['basea']/12:.2f} -> {T['rulea']/12:.2f} ({(T['rulea']-T['basea'])/12:+.2f})")
for c,v in sorted(C.items()): print(f"  cam{c}: movement {(v['rulem']-v['basem'])/v['n']:+.2f}  approach {(v['rulea']-v['basea'])/v['n']:+.2f}")
