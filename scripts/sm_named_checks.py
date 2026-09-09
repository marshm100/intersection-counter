"""G-SM-1 named track checks (docs/plan_state_machine_2026-09-09.md).

Runs the journey state machine's crossing law (classify_pair) on the
operator-ruled cam2 tracks, straight from the pass-1 rows, and prints
the valid crossings as three-state transitions. Declared checks:
  17526  W entry, NO W exits, a single S exit (revised iter 3)
  16722  must stay OCCUPYING(W) -> EXITED(S)
Read-only. Exit code 1 if a declared check fails.

Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/sm_named_checks.py [VARIANT]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates  # noqa: E402
from backend.services.entry_gates import classify_pair  # noqa: E402
from backend.services.entry_gates import pair_crossings  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
CAM = 2
CHECKS = {
    # tid: (expected origin cardinal, expected dest cardinal,
    #       cardinals that must carry NO valid crossing)
    # the waiting vehicle ("a real vehicle waiting to turn right"). Under
    # iterations 1-2 it LOST its W entry (exit_only S). Iteration 3's
    # spawn-wobble tolerance gives the entry back: OCCUPYING(W) ->
    # EXITED(S), its true movement. The four false EXITED(W) flips he
    # ruled invalid stay gone. REVISED CHECK (2026-09-09, flagged for
    # his ruling): W entry, NO W EXITS, a single S exit.
    17526: ("W", "S", ()),
    16722: ("W", "S", ()),          # clean right
}
NO_W_CROSSINGS = {17526}


def main() -> int:
    variant = sys.argv[1] if len(sys.argv) > 1 else "study_0700"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    _vpath, chash, fps = con.execute(
        "SELECT path, content_hash, fps FROM videos WHERE camera_id=?",
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
    td = tracks_dir(parquet_path(PROJ, CAM, chash, variant))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])

    ok = True
    for tid, (exp_o, exp_d, _none) in CHECKS.items():
        trk = rows[rows[:, 0] == float(tid)]
        if not len(trk):
            print(f"tid {tid}: NO TRACK in {variant}")
            ok = False
            continue
        pts_l = [(float(r[1]), float(r[2]) - float(r[4]) / 2,
                  float(r[3]) + float(r[5]) / 2) for r in trk]
        pts_r = [(float(r[1]), float(r[2]) + float(r[4]) / 2,
                  float(r[3]) + float(r[5]) / 2) for r in trk]
        valid = pair_crossings(pts_l, pts_r, gates, fps)
        o, d, fo, fd, _op, _dp, tag = classify_pair(pts_l, pts_r, gates, fps)
        card = lambda lg: legs.get(lg, f"L{lg}")  # noqa: E731
        print(f"tid {tid} ({variant}, {len(trk)} rows, "
              f"f{int(trk[0, 1])}-{int(trk[-1, 1])}): "
              f"{len(valid)} valid crossings")
        for f, lg, inward, _p in valid:
            print(f"     f{int(f)}  {'IN ' if inward else 'OUT'} over "
                  f"{card(lg)}")
        state = (f"OCCUPYING({card(o)}) -> EXITED({card(d)})"
                 if tag == "full" else tag)
        print(f"     machine: {state}   [{tag}]")
        got = (card(o) if o is not None else None,
               card(d) if d is not None else None)
        want = (exp_o, exp_d)
        exits = [c for c in valid if not c[2]]
        checks = [(f"origin/dest {want}", got == want)]
        if tid in NO_W_CROSSINGS:
            w_exits = [c for c in exits if card(c[1]) == "W"]
            checks.append(("no W exits", not w_exits))
            checks.append(("single S exit",
                           len([c for c in exits if card(c[1]) == "S"]) == 1))
        for name, passed in checks:
            print(f"     {'PASS' if passed else 'FAIL'}  {name}")
            ok = ok and passed
        print()
    print("ALL NAMED CHECKS PASS" if ok else "NAMED CHECK FAILURE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
