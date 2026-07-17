"""Resolve the through-vs-right ambiguity from data alone (Grok Q-AMBIGUITY/Q-LEGS).

Uses the regenerated camera-1 trajectories + manual TMC to determine whether the
dominant L22 flow is really a through (label/leg problem) without hand-inspecting
the video. Three checks:

  1. Observed flow matrix F[origin_leg][dest_leg] by snapping each trajectory's
     start/end to the nearest leg origin point.
  2. Geometry label per (origin,dest) via derive_movement (rank-based, NOT the
     broken tangent labeler) -> aggregate to per-(origin,movement); compare to manual.
  3. Leg-placement check: observed entry heading per origin leg vs the stored
     reference_heading. A large mismatch means the leg/heading is wrong, not just
     the path label.

Usage: py scripts/diagnose_legs_flow.py
"""
from __future__ import annotations

import math
import sqlite3
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groundtruth import ALL_MVT, LEG_TO_APPROACH, db_processed_window, parse_manual_csv
from replay_attribution_changes import PROJECT_DB, load_events, load_legs
from backend.services.trajectory_classifier import _leg_origin_point, derive_movement
from tune_joint_scorer import manual_cells_for_window

NORM = {"through": "thru", "left": "left", "right": "right", "u_turn": "uturn",
        "insufficient_data": "none"}


def _heading(p1, p2):
    return math.degrees(math.atan2(p2[0] - p1[0], -(p2[1] - p1[1]))) % 360


def _nearest_leg(pt, legs):
    best, bd = None, 1e18
    for lg in legs:
        ox, oy = _leg_origin_point(lg)
        d = (pt[0] - ox) ** 2 + (pt[1] - oy) ** 2
        if d < bd:
            bd, best = d, lg["leg_id"]
    return best


def main() -> int:
    c = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(c)
    events = load_events(c)
    c.close()
    legd = {l["leg_id"]: l for l in legs}
    window = db_processed_window()
    manual = manual_cells_for_window(parse_manual_csv(), window)

    F: dict[tuple[int, int], int] = {}
    entry_head: dict[int, list] = {}
    for ev in events:
        t = ev["trajectory"]
        if not t or len(t) < 4:
            continue
        o = _nearest_leg(t[0], legs)
        d = _nearest_leg(t[-1], legs)
        F[(o, d)] = F.get((o, d), 0) + 1
        k = min(4, len(t) - 1)
        entry_head.setdefault(o, []).append(_heading(t[0], t[k]))

    print("=== Observed flow matrix F[origin -> dest] with geometry label ===")
    print(f"{'orig':<6} {'dest':<6} {'count':>6} {'derive_movement':>16}")
    for (o, d), n in sorted(F.items(), key=lambda kv: -kv[1]):
        mv = derive_movement(legd[o], legd[d], all_legs=legs) if o in legd and d in legd else "?"
        print(f"L{o:<5} L{d:<5} {n:>6} {mv:>16}")

    print("\n=== Per-(origin, movement) via derive_movement vs MANUAL ===")
    obs: dict[tuple[int, str], float] = {}
    for (o, d), n in F.items():
        mv = NORM.get(derive_movement(legd[o], legd[d], all_legs=legs), "none")
        obs[(o, mv)] = obs.get((o, mv), 0) + n
    print(f"{'Leg':<4} {'Mvt':<6} {'Manual':>7} {'Observed(derive)':>17}")
    for lid in LEG_TO_APPROACH:
        for m in ALL_MVT:
            man = manual[lid][m]
            o = obs.get((lid, m), 0)
            if man == 0 and o == 0:
                continue
            print(f"L{lid:<3} {m:<6} {man:>7.1f} {o:>17}")

    print("\n=== Leg-placement check: observed entry heading vs stored reference_heading ===")
    print(f"{'Leg':<4} {'approach':<22} {'ref_head':>9} {'obs_entry_median':>17} {'n':>5} {'diff':>6}")
    for lid in sorted(entry_head):
        lg = legd[lid]
        ref = float(lg.get("reference_heading") or 0)
        hs = entry_head[lid]
        # circular median-ish via mean of sin/cos
        mx = sum(math.cos(math.radians(h)) for h in hs)
        my = sum(math.sin(math.radians(h)) for h in hs)
        obsh = math.degrees(math.atan2(my, mx)) % 360
        diff = abs((obsh - ref + 180) % 360 - 180)
        appr = LEG_TO_APPROACH.get(lid, lg.get("label", "?"))
        print(f"L{lid:<3} {str(appr):<22} {ref:>9.1f} {obsh:>17.1f} {len(hs):>5} {diff:>6.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
