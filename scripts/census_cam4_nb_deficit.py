"""Where are cam4's missing northbound vehicles? (2026-09-12)

Under d16 (large basis + fracture rule) cam4 1600 counts 2109 S->N
throughs against Miovision's 2439. Every dump track is classified
under the pinned gates; tracks that ENTERED over S (entry_only or
full from S) are real S-origin vehicles the tracker saw at the line.
For each: does it carry a counted event, a rejected event (which
pass rejected it), or no event at all (dropped before counting), and
what movement did its event get? Usage: python census_cam4_nb_deficit.py DB VARIANT
"""
from __future__ import annotations
import sqlite3, sys
from collections import Counter
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.database import leg_geometry_for_camera, list_paths_for_camera
from backend.services.detection_cache import parquet_path
from backend.services.entry_gates import build_gates, classify_pair
from backend.services.pass2_replay import load_dump, tracks_dir
PROJ, cam = "97a7849a", 4
db_path, variant = sys.argv[1], sys.argv[2]
con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (cam,)))
geom = leg_geometry_for_camera(PROJ, cam)
gates = build_gates({l: g["mouth"] for l, g in geom.items() if g.get("mouth")}, list_paths_for_camera(PROJ, cam),
                    {l: g.get("heading") for l, g in geom.items()}, leg_gates={l: g["gate"] for l, g in geom.items() if g.get("gate")})
rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant)))); rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
_u, st = np.unique(rows[:, 0], return_index=True); en = np.append(st[1:], len(rows))
db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
ev = {}
for tid, o, d, mv, rej, src in db.execute("SELECT vehicle_track_id, origin_leg_id, destination_leg_id, movement, COALESCE(rejected,0), posterior_source FROM vehicle_events WHERE camera_id=?", (cam,)):
    ev.setdefault(tid, []).append((legs.get(o), legs.get(d), mv, rej, src))
S = [l for l, c in legs.items() if c == "S"][0]; N = [l for l, c in legs.items() if c == "N"][0]
tally = Counter(); ex = Counter(); npts_hist = Counter()
for t, a, b in zip(_u, st, en):
    trk = rows[a:b]
    if len(trk) < 2: continue
    L = [(float(r[1]), float(r[2]) - float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
    R = [(float(r[1]), float(r[2]) + float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
    o, d, *_r, tag = classify_pair(L, R, gates, fps)
    if o != S: continue
    evs = ev.get(int(t), [])
    counted = [e for e in evs if e[3] == 0]; rejected = [e for e in evs if e[3] == 1]
    if counted: state = "counted " + "/".join(f"{e[0]}->{e[1]}" for e in counted)
    elif rejected: state = "rejected " + "/".join(f"{e[0]}->{e[1]}" for e in rejected)
    else: state = "NO EVENT"; npts_hist[min(len(trk) // 5 * 5, 60)] += 1
    tally[(tag, state)] += 1
print(f"cam4 {variant} {Path(db_path).name}: tracks that ENTERED over S by machine tag and fate")
for (tag, state), n in sorted(tally.items(), key=lambda kv: -kv[1])[:24]:
    print(f"  {n:5}  {tag:11} {state}")
tot = sum(tally.values()); cnt = sum(n for (tg, s), n in tally.items() if s.startswith("counted"))
print(f"total S-entered tracks {tot}; with a counted event {cnt}; Miovision NB total (thru+left+right) see score json")
print("NO EVENT tracks by row count bucket:", sorted(npts_hist.items()))
