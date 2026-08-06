"""Pipeline-V2 — WHERE do counted journeys cross their origin gate?

For one origin leg, projects every full journey's entry-crossing point
onto the gate axis (0..1 along p1->p2) and prints the distribution per
destination. If a destination's crossings cluster at one end of the span
while the leg's other movements cluster elsewhere, the gate span admits
foreign-lane traffic there -> lane-restricted origin claims are the fix.

Usage:
  py -X utf8 scripts/v2_gate_cross_probe.py runs/v2_week1/tracklets_cam2_study_0700.npz --origin 28
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import load_table, track_points         # noqa: E402
from backend.services.entry_gates import classify      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("--origin", type=int, required=True)
    args = ap.parse_args()
    t = load_table(args.table)
    fps = t["fps"]
    gates = {int(k): (tuple(v[0]), tuple(v[1]), tuple(v[2]))
             for k, v in t["meta"]["gates"].items()}
    g = gates[args.origin]
    p1, p2 = np.array(g[0]), np.array(g[1])
    axis = p2 - p1
    L = float(np.hypot(*axis)) or 1.0
    axis = axis / L

    by_dest: dict[int, list[float]] = {}
    idx = np.where((t["tag"] == 0) & (t["origin_leg"] == args.origin))[0]
    for i in idx:
        tr = track_points(t, int(i))
        track = [(float(f), float(x), float(y))
                 for f, x, y in zip(tr[:, 1], tr[:, 2], tr[:, 3])]
        o, d, ofr, dfr, opos, dpos, tag = classify(track, gates, fps)
        if tag != "full" or o != args.origin or opos is None:
            continue
        proj = float((np.array(opos) - p1) @ axis) / L
        by_dest.setdefault(int(d), []).append(proj)

    print(f"origin leg {args.origin}: gate span {L:.0f}px  "
          f"p1={g[0]} p2={g[1]}  ({args.table})")
    bins = np.linspace(0, 1, 11)
    for d, projs in sorted(by_dest.items()):
        h, _ = np.histogram(np.clip(projs, 0, 1), bins=bins)
        bar = " ".join(f"{c:>3}" for c in h)
        print(f"  -> dest {d}: n={len(projs):>4} med={np.median(projs):.2f} "
              f"deciles(0..1 x10): {bar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
