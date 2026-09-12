"""What pairs does THE FRACTURE RULE make on a window? (2026-09-11)

Runs turn_merge.fracture_pairs over a window's dump against the events
of a pre-rule arm DB and tabulates: victim movement, partner movement,
same-cell or not, whether the bearing test was waived (a bearing
missing), gap and dist/box. cam4 1600 under d16 lost 330 NB throughs.
Usage: .venv\\Scripts\\python.exe -X utf8 scripts/diag_fracture_pairs.py CAM VARIANT PRE_DB
"""
from __future__ import annotations
import sqlite3, sys
from collections import Counter
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.database import leg_geometry_for_camera, list_paths_for_camera
from backend.services.detection_cache import parquet_path
from backend.services.entry_gates import build_gates
from backend.services.pass2_replay import load_dump, tracks_dir
from backend.services.turn_merge import fracture_pairs
from backend.services.two_pass import _tracks_from_rows, gate_axes_for

PROJ = "97a7849a"
cam, variant, pre_db = int(sys.argv[1]), sys.argv[2], sys.argv[3]
con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (cam,)))
rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
geom = leg_geometry_for_camera(PROJ, cam)
mouths = {l: g["mouth"] for l, g in geom.items()}
tracks = _tracks_from_rows(rows)
gates = build_gates(mouths, list_paths_for_camera(PROJ, cam), {l: g["heading"] for l, g in geom.items()},
                    leg_axes=gate_axes_for(mouths, tracks.values()),
                    leg_gates={l: g["gate"] for l, g in geom.items() if g["gate"]} or None)
db = sqlite3.connect(f"file:{pre_db}?mode=ro", uri=True)
ev_rows = db.execute("SELECT event_id, vehicle_track_id, origin_leg_id, destination_leg_id, movement, start_frame FROM vehicle_events "
                     "WHERE camera_id=? AND COALESCE(rejected,0)=0 AND vehicle_track_id IS NOT NULL AND vehicle_track_id>=0", (cam,)).fetchall()
info = {e[0]: e for e in ev_rows}
recs, pairs = fracture_pairs([(e[0], e[1]) for e in ev_rows], rows, float(fps), gates)
cell = lambda e: f"{legs.get(e[2])}->{legs.get(e[3])} {e[4]}"
print(f"cam{cam} {variant}: events {len(ev_rows)}, recs {len(recs)}, pairs {len(pairs)}")
victims = Counter(cell(info[v["eid"]]) for _a, _b, v, _g, _r in pairs)
print("victims by cell:", victims.most_common(8))
same = sum(1 for a, b, v, g, r in pairs if (info[a["eid"]][2], info[a["eid"]][3]) == (info[b["eid"]][2], info[b["eid"]][3]))
opp = sum(1 for a, b, v, g, r in pairs if (info[a["eid"]][2], info[a["eid"]][3]) == (info[b["eid"]][3], info[b["eid"]][2]))
print(f"same cell {same}/{len(pairs)}   opposite direction {opp}/{len(pairs)}")
waived = sum(1 for a, b, v, g, r in pairs if a.get("b_end") is None or b.get("b_start") is None)
print(f"bearing test waived (a bearing missing): {waived}/{len(pairs)}  (A end missing {sum(1 for a,b,v,g,r in pairs if a.get('b_end') is None)}, B start missing {sum(1 for a,b,v,g,r in pairs if b.get('b_start') is None)})")
tags = Counter((a["tag"], b["tag"]) for a, b, v, g, r in pairs)
print("tags (A, B):", tags.most_common(6))
gaps = np.array([g for a, b, v, g, r in pairs]); rels = np.array([r for a, b, v, g, r in pairs])
if len(pairs):
    print(f"gap s p10/50/90 {np.percentile(gaps,[10,50,90]).round(2)}   dist/box p10/50/90 {np.percentile(rels,[10,50,90]).round(2)}")
    spans = np.array([[a["span"], b["span"]] for a, b, v, g, r in pairs]) / float(fps)
    print(f"A span s p50 {np.median(spans[:,0]):.1f}  B span s p50 {np.median(spans[:,1]):.1f}   victim is A {sum(1 for a,b,v,g,r in pairs if v is a)}/{len(pairs)}")
    boxes = np.array([(a["box"] + b["box"]) / 2 for a, b, v, g, r in pairs]); ys = np.array([a["death"][2] for a, b, v, g, r in pairs])
    print(f"pair box px p10/50/90 {np.percentile(boxes,[10,50,90]).round(0)}   death y p10/50/90 {np.percentile(ys,[10,50,90]).round(0)}")
    print("first 8 pairs (A cell | B cell | gap | dist/box | bearings A_end,B_start | victim):")
    for a, b, v, g, r in pairs[:8]:
        print(f"  {cell(info[a['eid']]):22} | {cell(info[b['eid']]):22} | {g:.1f}s | {r:.2f} | {a.get('b_end')},{b.get('b_start')} | {'A' if v is a else 'B'}")
