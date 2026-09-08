"""Test 'the witness outranks the guess' (operator rulings 2026-09-08).

Operator ruled clips 1 and 3 of the invented-origin reel are
SOUTHBOUND THROUGHS; the machine booked them as eastbound right
turns. Their entry over the N line is witnessed by BOTH bottom
corners; the assigned origin came from a 0.65-0.71 confidence guess.

This measures the correction: wherever the ground-anchored gate
evidence witnesses an ENTRY that contradicts the assigned origin,
re-derive the movement from the witnessed origin and the existing
destination, and see how the cell table moves against Miovision.
Read-only.

Usage:  py -X utf8 scripts/test_witness_wins.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates, classify  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402
from backend.services.trajectory_classifier import derive_movement  # noqa: E402

PROJ = "97a7849a"
CAM, VARIANT = 5, "l1_study_1100"
MIO = {("S", "through"): 1362, ("S", "left"): 185, ("S", "right"): 26,
       ("N", "through"): 1496, ("N", "left"): 27, ("N", "right"): 88,
       ("W", "through"): 12, ("W", "left"): 87, ("W", "right"): 162,
       ("E", "through"): 24, ("E", "left"): 17, ("E", "right"): 21}
BOUND = {"S": "NB", "N": "SB", "E": "WB", "W": "EB"}


def ground_entry(trk, gates, fps):
    """(witnessed entry leg or None, witnessed anything at all)."""
    o_out, d_out = [], []
    for sign in (-1.0, 1.0):
        pts = sorted((float(r[1]),
                      float(r[2]) + sign * float(r[4]) / 2.0,
                      float(r[3]) + float(r[5]) / 2.0) for r in trk)
        o, d, *_rest = classify(pts, gates, fps)
        o_out.append(o)
        d_out.append(d)
    entry = o_out[0] if o_out[0] == o_out[1] else None
    exit_ = d_out[0] if d_out[0] == d_out[1] else None
    return entry, (entry is not None or exit_ is not None)


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    chash, fps = con.execute(
        "SELECT content_hash, fps FROM videos WHERE camera_id=?",
        (CAM,)).fetchone()
    legrows = [dict(zip(("leg_id", "cardinal_direction",
                         "reference_heading"), r))
               for r in con.execute(
                   "SELECT leg_id, cardinal_direction, reference_heading "
                   "FROM legs WHERE camera_id=?", (CAM,))]
    con.close()
    fps = float(fps)
    legs = {lg["leg_id"]: lg["cardinal_direction"] for lg in legrows}
    byid = {lg["leg_id"]: lg for lg in legrows}

    geom = leg_geometry_for_camera(PROJ, CAM)
    gates = build_gates(
        {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
        list_paths_for_camera(PROJ, CAM),
        {lg: g.get("heading") for lg, g in geom.items()},
        leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})

    td = tracks_dir(parquet_path(PROJ, CAM, chash, VARIANT))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])

    s = sqlite3.connect(
        f"file:data/projects/{PROJ}/_replay_scratch/c45_20260907/"
        f"cx_cam{CAM}_study_1100.db?mode=ro", uri=True)
    ev = list(s.execute(
        "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, movement"
        " FROM vehicle_events WHERE camera_id=? AND rejected=0", (CAM,)))
    s.close()

    now, fixed, combo = (defaultdict(int), defaultdict(int),
                         defaultdict(int))
    moves = Counter()
    n_fix = n_drop = 0
    for tid, o, d, mv in ev:
        now[(legs.get(o), mv)] += 1
        trk = rows[rows[:, 0] == float(tid)]
        ge, witnessed = ((None, False) if len(trk) < 5
                         else ground_entry(trk, gates, fps))
        key = (legs.get(o), mv)
        if ge is not None and ge != o and d is not None and ge in byid:
            nm = derive_movement(byid[ge], byid.get(d), legrows)
            if nm and nm != "insufficient_data":
                key = (legs.get(ge), nm)
                moves[(f"{legs.get(o)} {mv}",
                       f"{legs.get(ge)} {nm}")] += 1
                n_fix += 1
        fixed[key] += 1
        if witnessed or key[1] not in ("left", "right", "u_turn"):
            combo[key] += 1
        else:
            n_drop += 1

    print(f"events re-attributed to their WITNESSED entry: {n_fix}\n")
    print("the moves (from -> to, count):")
    for (a, b), k in moves.most_common(10):
        print(f"   {a:14} -> {b:14} {k:>5}")

    print(f"\n  never-witnessed turns also dropped: {n_drop}")
    print(f"\n{'cell':12}{'Mio':>7}{'now':>7}{'witness':>9}"
          f"{'witness+veto':>14}")
    e_now = e_fix = e_cmb = 0
    for key in sorted(MIO, key=lambda k: -MIO[k]):
        m = MIO[key]
        lab = f"{BOUND[key[0]]}_{key[1][:5]}"
        print(f"{lab:12}{m:>7}{now[key]:>7}{fixed[key]:>9}"
              f"{combo[key]:>14}")
        e_now += abs(m - now[key])
        e_fix += abs(m - fixed[key])
        e_cmb += abs(m - combo[key])
    print(f"\n  abs error vs Mio, as counted         : {e_now}")
    print(f"  abs error vs Mio, witness wins       : {e_fix}")
    print(f"  abs error vs Mio, witness + turn veto: {e_cmb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
