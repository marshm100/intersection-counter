"""Fast per-approach baseline for all 5 corridor cameras from STORED events
(= deployed live-bank attribution; no pipeline). Aggregates per (leg, movement,
minute) IN SQL (GROUP BY) to avoid the OneDrive Python-row-loop antipattern, and
flushes per camera so progress streams. ASCII prints."""
from __future__ import annotations
import sqlite3, sys
from collections import defaultdict
from datetime import time
from pathlib import Path
sys.path.insert(0, str(Path("scripts").resolve()))
sys.path.insert(0, str(Path(".").resolve()))
import triangulate_manual as T
import interval_metric as IM

PROJECT = "97a7849a"
NORM = {"through": "thru", "u_turn": "uturn", "left": "left", "right": "right"}
db = f"data/projects/{PROJECT}/project.db"


def per_min_from_stored(conn, cam):
    leg_dir = {lid: T._CARD_TO_DIR.get((cd or "").strip().upper())
               for lid, cd in conn.execute(
                   "SELECT leg_id,cardinal_direction FROM legs WHERE camera_id=?", (cam,))}
    pm = defaultdict(lambda: defaultdict(int))
    # SQL GROUP BY: HH:MM via substr of the ISO timestamp_real ('...T HH:MM:...').
    rows = conn.execute(
        "SELECT origin_leg_id, movement, substr(timestamp_real,12,5) AS hhmm, COUNT(*) "
        "FROM vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0 "
        "AND timestamp_real IS NOT NULL "
        "GROUP BY origin_leg_id, movement, hhmm", (cam,)).fetchall()
    for olid, mv, hhmm, n in rows:
        d = leg_dir.get(olid)
        if not d or not hhmm or len(hhmm) != 5:
            continue
        pm[time(int(hhmm[:2]), int(hhmm[3:5]))][(d, NORM.get(mv, mv))] += n
    return pm


conn = sqlite3.connect(db)
for cam in (1, 2, 3, 4, 5):
    try:
        mio = T.load_miovision(cam)
    except Exception as e:
        print(f"\ncam{cam}: no Miovision ({e})", flush=True); continue
    pm = per_min_from_stored(conn, cam)
    res = IM.per_interval(pm, mio, by_approach=True)
    print(f"\n=== cam{cam}  TOTAL AVG|err| {res.get('avg_abs_err_pct'):.1f}% "
          f"[{res['verdict']}] ===", flush=True)
    for d, r in sorted(res["per_approach"].items(),
                       key=lambda kv: -(kv[1]["avg_abs_err_pct"] or 0)):
        if r["n_bins"]:
            print(f"    {d:<3} {r['avg_abs_err_pct']:5.1f}%  [{r['verdict']:<4}] "
                  f"max {r['max_abs_err_pct']:.0f}%@{r['worst_interval']}", flush=True)
    legs = {lid: (cd or "").upper() for lid, cd in conn.execute(
        "SELECT leg_id,cardinal_direction FROM legs WHERE camera_id=?", (cam,))}
    paths = {(o, dd) for o, dd in conn.execute(
        "SELECT origin_leg_id,destination_leg_id FROM intersection_paths WHERE camera_id=?", (cam,))}
    miss = [f"L{o}({legs[o]})->L{dd}({legs[dd]})" for o in legs for dd in legs
            if o != dd and (o, dd) not in paths]
    print(f"    bank: {len(paths)} paths; MISSING cells: {', '.join(miss) if miss else 'none'}",
          flush=True)
conn.close()
