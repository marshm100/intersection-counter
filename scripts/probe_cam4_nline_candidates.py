"""Candidate N lines for cam4 (2026-09-12): the drawn N line sits at the far
mouth where boxes die; the near pieces of the bottom-edge NB vehicles die
at x 520-600 while still 100 px wide. Classify every production dump track
with the gate machinery under (a) the drawn gates and (b) the N gate moved
to a vertical line at x = X spanning the road, and count the journey tags.
Nothing is drawn or written. Usage:
  .venv/Scripts/python.exe -X utf8 scripts/probe_cam4_nline_candidates.py VARIANT [X ...]
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

PROJ, CAM = "97a7849a", 4
variant = sys.argv[1]
XS = [float(x) for x in sys.argv[2:]] or [500.0, 550.0]
con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (CAM,)).fetchone()
legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (CAM,)))
N = next(l for l, c in legs.items() if c == "N"); S = next(l for l, c in legs.items() if c == "S")
geom = leg_geometry_for_camera(PROJ, CAM)
paths = list_paths_for_camera(PROJ, CAM)
rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, CAM, chash, variant)))); rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
_u, st = np.unique(rows[:, 0], return_index=True); en = np.append(st[1:], len(rows))
f0 = int(rows[:, 1].min())
ev = set(int(t) for (t,) in con.execute("SELECT vehicle_track_id FROM vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0 AND start_frame BETWEEN ? AND ?", (CAM, f0 - 3000, int(rows[:, 1].max()) + 3000)))

def gates_for(n_line):
    mouths = {l: g["mouth"] for l, g in geom.items() if g.get("mouth")}
    lg = {l: g["gate"] for l, g in geom.items() if g.get("gate")}
    if n_line is not None:
        lg[N] = n_line
        mouths[N] = ((n_line[0][0] + n_line[1][0]) / 2, (n_line[0][1] + n_line[1][1]) / 2)
    return build_gates(mouths, paths, {l: g.get("heading") for l, g in geom.items()}, leg_gates=lg)

variants = [("drawn", None)] + [(f"N at x={int(x)}", [[x, 288.0], [x + 40.0, 478.0]]) for x in XS]
print(f"cam4 {variant}: {len(_u)} tracks; drawn N line {geom[N]['gate']}")
for name, nl in variants:
    gates = gates_for(nl)
    tags = Counter(); uncounted_full_sn = 0
    for t, a, b in zip(_u, st, en):
        trk = rows[a:b]
        if len(trk) < 2: continue
        L = [(float(r[1]), float(r[2]) - float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
        R = [(float(r[1]), float(r[2]) + float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
        o, d, *_r, tag = classify_pair(L, R, gates, fps)
        key = f"{legs.get(o, '-')}->{legs.get(d, '-')} {tag}"
        tags[key] += 1
        if o == S and d == N and int(t) not in ev: uncounted_full_sn += 1
    full_sn = sum(n for k, n in tags.items() if k.startswith("S->N full"))
    exit_n = sum(n for k, n in tags.items() if k.endswith("->N exit_only"))
    full_ns = sum(n for k, n in tags.items() if k.startswith("N->S full"))
    entry_n = sum(n for k, n in tags.items() if k.startswith("N->- entry_only"))
    print(f"  [{name:12}] S->N full {full_sn:5}  (of which no counted event today {uncounted_full_sn:4})   -->N exit_only {exit_n:4}   "
          f"N->S full {full_ns:5}   N entry_only {entry_n:4}   S entry_only {tags.get('S->- entry_only', 0):4}   no_crossing {sum(n for k, n in tags.items() if 'no_crossing' in k):5}")
