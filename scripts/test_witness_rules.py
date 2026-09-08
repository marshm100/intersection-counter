"""Witness census, GROUND-ANCHORED (operator bug report 2026-09-08).

CORRECTION: the first version of this script fed BOX CENTRES to the
crossing test — the exact error the operator's threshold law exists
to eliminate. Clip 1 (tid 116990) proved it: by centre it crosses no
gate; by bottom edge it crosses the S gate. Every never-witnessed
number from the centre version was wrong.

This version applies the shipped rule verbatim: the crossing test
point is the bottom edge, and BOTH bottom corners must agree (the
operator's refinement, pipeline._gate_evidence under
GATE_GROUND_ANCHOR). Read-only.

Usage:  py -X utf8 scripts/test_witness_rules.py
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

PROJ = "97a7849a"
CAM, VARIANT = 5, "l1_study_1100"
MIO = {("S", "through"): 1362, ("S", "left"): 185, ("S", "right"): 26,
       ("N", "through"): 1496, ("N", "left"): 27, ("N", "right"): 88,
       ("W", "through"): 12, ("W", "left"): 87, ("W", "right"): 162,
       ("E", "through"): 24, ("E", "left"): 17, ("E", "right"): 21}
BOUND = {"S": "NB", "N": "SB", "E": "WB", "W": "EB"}


def tag_of(trk, gates, fps):
    """The shipped ground-anchored rule: classify both bottom corners;
    evidence survives only where they agree."""
    out = []
    for sign in (-1.0, 1.0):
        pts = sorted((float(r[1]),
                      float(r[2]) + sign * float(r[4]) / 2.0,
                      float(r[3]) + float(r[5]) / 2.0) for r in trk)
        o, d, *_rest, tag = classify(pts, gates, fps)
        out.append((o, d))
    (oL, dL), (oR, dR) = out
    o = oL if oL == oR else None
    d = dL if dL == dR else None
    if o is not None and d is not None:
        return o, d, "full"
    if o is not None:
        return o, d, "entry_only"
    if d is not None:
        return o, d, "exit_only"
    return None, None, "no_crossing"


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    chash, fps = con.execute(
        "SELECT content_hash, fps FROM videos WHERE camera_id=?",
        (CAM,)).fetchone()
    legs = dict(con.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
        (CAM,)))
    con.close()
    fps = float(fps)

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
    need = {int(t) for t, *_ in ev}

    ctr_tag, gnd_tag, gnd_cell = {}, {}, {}
    for tid in np.unique(rows[:, 0]):
        tid = int(tid)
        if tid not in need:
            continue
        trk = rows[rows[:, 0] == float(tid)]
        if len(trk) < 5:
            continue
        pts = sorted((float(r[1]), float(r[2]), float(r[3])) for r in trk)
        ctr_tag[tid] = classify(pts, gates, fps)[-1]
        o, d, t = tag_of(trk, gates, fps)
        gnd_tag[tid] = t
        gnd_cell[tid] = (o, d)

    print(f"counted events: {len(ev)}\n")
    print(f"{'evidence tag':18}{'by CENTRE (wrong)':>20}"
          f"{'by GROUND (correct)':>22}")
    c, g = Counter(ctr_tag.values()), Counter(gnd_tag.values())
    for k in ("full", "entry_only", "exit_only", "no_crossing"):
        print(f"  {k:16}{c[k]:>20}{g[k]:>22}")
    tot = max(1, sum(c.values()))
    print(f"\nnever-witnessed: centre {100*c['no_crossing']/tot:.0f}%"
          f"  ->  ground {100*g['no_crossing']/tot:.0f}%")

    now, vetoed, turnveto = (defaultdict(int), defaultdict(int),
                             defaultdict(int))
    n_dis = 0
    for tid, o, d, mv in ev:
        tid = int(tid)
        key = (legs.get(o), mv)
        now[key] += 1
        t = gnd_tag.get(tid, "(short)")
        if t != "no_crossing":
            vetoed[key] += 1
        # a never-witnessed fragment may not INVENT A TURN. Turns are
        # what fragmentation invents; throughs are what it breaks.
        if not (t == "no_crossing" and mv in ("left", "right", "u_turn")):
            turnveto[key] += 1
        go, _gd = gnd_cell.get(tid, (None, None))
        if t in ("full", "entry_only") and go is not None and go != o:
            n_dis += 1
    print(f"\nevents whose ORIGIN the ground evidence contradicts: {n_dis}")
    print(f"\n{'cell':12}{'Mio':>7}{'now':>7}{'veto ALL':>13}{'veto TURNS':>17}")
    e_now = e_vet = e_turn = 0
    for key in sorted(MIO, key=lambda k: -MIO[k]):
        m = MIO[key]
        lab = f"{BOUND[key[0]]}_{key[1][:5]}"
        print(f"{lab:12}{m:>7}{now[key]:>7}{vetoed[key]:>13}"
              f"{turnveto[key]:>17}")
        e_now += abs(m - now[key])
        e_vet += abs(m - vetoed[key])
        e_turn += abs(m - turnveto[key])
    print(f"\n  abs error vs Miovision, as counted      : {e_now}")
    print(f"  abs error vs Miovision, veto ALL         : {e_vet}")
    print(f"  abs error vs Miovision, veto TURNS only  : {e_turn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
