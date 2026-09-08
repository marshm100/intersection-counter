"""Test the operator's pertinent-shape ruling (2026-09-08).

His words on the invented-origin clips: "the detector box is looking
at the bottom of the screen and there is right turn motion as
detection is picked up by a vehicle but that happens BEFORE the
mouth and then it is THROUGH for the rest of the movement."

i.e. the movement is being read from the WHOLE track, including the
pre-mouth approach curve, when only the part from the mouth onward
is pertinent (his pertinence law, applied to trajectory shape).

This measures, for every counted event whose ground-witnessed entry
contradicts its assigned origin: the shape over the FULL track vs
the shape over the POST-ENTRY segment only. Read-only.

Usage:  py -X utf8 scripts/test_pertinent_shape.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates, classify  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402
from backend.services.trajectory_classifier import (  # noqa: E402
    compute_net_heading_change, compute_path_straightness)

PROJ = "97a7849a"
CAM, VARIANT = 5, "l1_study_1100"


def ground_entry(trk, gates, fps):
    """(entry leg or None, frame of the entry crossing or None)."""
    outs = []
    for sign in (-1.0, 1.0):
        pts = sorted((float(r[1]),
                      float(r[2]) + sign * float(r[4]) / 2.0,
                      float(r[3]) + float(r[5]) / 2.0) for r in trk)
        o, _d, fo, *_rest = classify(pts, gates, fps)
        outs.append((o, fo))
    if outs[0][0] is not None and outs[0][0] == outs[1][0]:
        f = max(x for x in (outs[0][1], outs[1][1]) if x is not None)
        return outs[0][0], f
    return None, None


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    chash, fps = con.execute(
        "SELECT content_hash, fps FROM videos WHERE camera_id=?",
        (CAM,)).fetchone()
    legrows = {r[0]: {"cardinal_direction": r[1], "reference_heading": r[2]}
               for r in con.execute(
                   "SELECT leg_id, cardinal_direction, reference_heading "
                   "FROM legs WHERE camera_id=?", (CAM,))}
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
        "SELECT vehicle_track_id, origin_leg_id, movement FROM "
        "vehicle_events WHERE camera_id=? AND rejected=0", (CAM,)))
    s.close()

    print(f"{'tid':>8} {'booked':>12} {'entered':>8} "
        f"{'FULL nhc':>9} {'FULL str':>9} {'POST nhc':>9} {'POST str':>9}")
    flips = Counter()
    n_ex = 0
    for tid, o, mv in ev:
        trk = rows[rows[:, 0] == float(tid)]
        if len(trk) < 10:
            continue
        ge, gf = ground_entry(trk, gates, fps)
        if ge is None or ge == o:
            continue
        ref = legrows[ge]["reference_heading"]
        full = [(float(r[2]), float(r[3])) for r in trk]
        post = [(float(r[2]), float(r[3])) for r in trk if r[1] >= gf]
        if len(post) < 5:
            continue
        f_nhc = compute_net_heading_change(full, ref)
        p_nhc = compute_net_heading_change(post, ref)
        f_str = compute_path_straightness(full)
        p_str = compute_path_straightness(post)
        flips[(abs(f_nhc) > 25, abs(p_nhc) > 25)] += 1
        if n_ex < 12:
            print(f"{tid:>8} {legrows[o]['cardinal_direction'] + ' ' + mv:>12}"
                  f" {legrows[ge]['cardinal_direction']:>8}"
                  f" {f_nhc:>9.1f} {f_str:>9.3f} {p_nhc:>9.1f}"
                  f" {p_str:>9.3f}")
            n_ex += 1
    print("\nshape verdict (|net heading change| > 25 deg = a TURN):")
    print(f"   turn on the FULL track, THROUGH after the mouth: "
          f"{flips[(True, False)]}")
    print(f"   turn on both                                   : "
          f"{flips[(True, True)]}")
    print(f"   through on both                                : "
          f"{flips[(False, False)]}")
    print(f"   through on full, turn after the mouth          : "
          f"{flips[(False, True)]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
