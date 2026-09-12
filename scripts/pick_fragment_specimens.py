"""Pick reel specimens: floor-removed cam5 throughs + nearest sequential same-cell survivor (2026-09-11)."""
from __future__ import annotations
import sqlite3, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import parquet_path
from backend.services.pass2_replay import load_dump, tracks_dir
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908"); PROJ = "97a7849a"
cam, variant, cur_db, new_db = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
want_mv = sys.argv[5] if len(sys.argv) > 5 else "through"
def load(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    r = con.execute("SELECT vehicle_track_id, start_frame, movement, origin_leg_id, destination_leg_id FROM vehicle_events "
                    "WHERE camera_id=? AND rejected=0 AND vehicle_track_id IS NOT NULL", (cam,)).fetchall(); con.close()
    return {(a, b): (m, o, d) for a, b, m, o, d in r}
con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (cam,)))
rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant)))); rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
_u, st = np.unique(rows[:, 0], return_index=True); en = np.append(st[1:], len(rows)); seg = {int(t): (a, b) for t, a, b in zip(_u, st, en)}
def ends(t):
    a, b = seg[t]; return rows[a, 1], rows[b - 1, 1], rows[a, 2:4], rows[b - 1, 2:4], float(np.median(np.maximum(rows[a:b, 4], rows[a:b, 5])))
cur, new = load(BASE / cur_db), load(BASE / new_db)
removed = {k: v for k, v in cur.items() if k not in new and k[0] in seg and v[0] == want_mv}
surv = [(t, v, ends(t)) for (t, _s), v in new.items() if t in seg]
out = []
for (tid, _sf), (mv, o, d) in removed.items():
    f0, f1, p0, p1, box = ends(tid); best = None
    for t2, v2, (g0, g1, q0, q1, box2) in surv:
        if t2 == tid or (v2[1], v2[2]) != (o, d): continue
        if g0 >= f1 and g0 <= f1 + 50 * fps: rel = np.hypot(*(q0 - p1)) / ((box + box2) / 2); gap = (g0 - f1) / fps; kind = "fwd"
        elif g1 <= f0 and g1 >= f0 - 50 * fps: rel = np.hypot(*(q1 - p0)) / ((box + box2) / 2); gap = (f0 - g1) / fps; kind = "bwd"
        else: continue
        if best is None or rel < best[0]: best = (rel, gap, kind, t2, g0, g1)
    if best: out.append((best[1], tid, f0, f1, box, o, d, *best))
out.sort()
print(f"{len(out)} removed {want_mv} with same-cell sequential survivor")
# five across the gap range: quantile picks
idx = [int(q * (len(out) - 1)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
for i in idx:
    gap, tid, f0, f1, box, o, d, rel, _g, kind, t2, g0, g1 = out[i]
    print(f"  removed tid {tid} f{int(f0)}-{int(f1)} ({(f1-f0)/fps:.1f}s, box {box:.0f}px) {legs.get(o)}->{legs.get(d)}   survivor tid {t2} f{int(g0)}-{int(g1)} {kind} gap {gap:.1f}s dist/box {rel:.2f}")
