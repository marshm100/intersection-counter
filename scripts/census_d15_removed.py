"""What did the 100 px floor (arm d15) remove, per camera? (2026-09-11)

Set difference of vehicle_events between the current-default arm DB
and the d15 DB for one camera: the removed events. For each: movement,
path distance, duration, bbox length, centre-y, posterior source, and
whether a SURVIVING event of the same (origin, dest) overlaps it in
time with trajectories within 2 bbox lengths (a duplicate partner:
the removed track was a second fragment of a counted vehicle) or not
(a singleton: the removed track was the only record of its vehicle).
Usage: .venv\Scripts\python.exe -X utf8 scripts/census_d15_removed.py
"""
from __future__ import annotations
import json, sqlite3, sys
from collections import Counter
from pathlib import Path
import numpy as np

FACTOR = float(__import__("os").environ.get("DUP_FACTOR", "2.0"))
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
PAIRS = [(1, "d7_cam1_study_1600.db", "d15_cam1_study_1600.db", 10.0),
         (5, "d14_cam5_l1_study_1600.db", "d15_cam5_l1_study_1600.db", 10.0)]
COLS = ("vehicle_track_id", "start_frame", "frame_number", "origin_leg_id", "destination_leg_id",
        "movement", "classifier_path_distance", "classifier_num_points", "bbox_length",
        "bbox_center_y", "posterior_source", "trajectory_data")


def load(db, cam):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(f"SELECT {','.join(COLS)} FROM vehicle_events WHERE camera_id=? AND rejected=0", (cam,)).fetchall()
    con.close()
    return {(r[0], r[1]): dict(zip(COLS, r)) for r in rows}


def interp(ev, frames):
    tr = np.asarray(json.loads(ev["trajectory_data"]), float)
    f0, f1 = ev["start_frame"], ev["frame_number"]
    t = np.linspace(f0, f1, len(tr)) if len(tr) > 1 else np.array([f0], float)
    return np.stack([np.interp(frames, t, tr[:, 0]), np.interp(frames, t, tr[:, 1])], 1)


for cam, cur_db, d15_db, fps in PAIRS:
    cur, new = load(BASE / cur_db, cam), load(BASE / d15_db, cam)
    removed = [v for k, v in cur.items() if k not in new]
    added = [v for k, v in new.items() if k not in cur]
    print(f"\n=== cam{cam}: current {len(cur)} events, d15 {len(new)}; removed {len(removed)}, added {len(added)}")
    print("  removed by movement:", Counter(v["movement"] for v in removed).most_common(8))
    print("  removed by source  :", Counter(v["posterior_source"] for v in removed).most_common(6))
    pd_ = np.array([v["classifier_path_distance"] or 0 for v in removed])
    bl = np.array([v["bbox_length"] or 0 for v in removed]); cy = np.array([v["bbox_center_y"] or 0 for v in removed])
    du = np.array([(v["frame_number"] - v["start_frame"]) / fps for v in removed])
    def q(a): return " ".join(f"{x:.0f}" for x in np.percentile(a, [10, 50, 90]))
    print(f"  path px p10/50/90 {q(pd_)} | bbox len {q(bl)} | centre-y {q(cy)} | dur s {' '.join(f'{x:.1f}' for x in np.percentile(du, [10,50,90]))}")
    # duplicate partner among SURVIVORS (same origin+dest, time overlap >= 0.5 s, within 2 bbox lengths)
    by_od = {}
    for v in new.values():
        by_od.setdefault((v["origin_leg_id"], v["destination_leg_id"]), []).append(v)
    dup = 0; dup_mv = Counter()
    for r in removed:
        found = False
        for s in by_od.get((r["origin_leg_id"], r["destination_leg_id"]), []):
            lo, hi = max(r["start_frame"], s["start_frame"]), min(r["frame_number"], s["frame_number"])
            if hi - lo < 0.5 * fps:
                continue
            fr = np.linspace(lo, hi, 8)
            d = np.hypot(*(interp(r, fr) - interp(s, fr)).T).min()
            if d <= FACTOR * max(r["bbox_length"] or 20, s["bbox_length"] or 20):
                found = True; break
        if found:
            dup += 1; dup_mv[r["movement"]] += 1
    print(f"  duplicate partner among survivors: {dup}/{len(removed)} ({dup/len(removed):.0%})  by movement {dup_mv.most_common(5)}")
    print(f"  singletons (only record of their vehicle): {len(removed)-dup}")
