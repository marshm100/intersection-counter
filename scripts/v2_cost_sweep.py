"""Pipeline-V2 — link-cost variant sweep (day-2; the anti-thrash step).

For each (pos_mode, vel_mode) combo and each gap class, measures on the
synthetic-fragmentation donors: true-link candidate presence, rank-1 rate
among present, median true/rival costs. No stitcher involved — this is
pure cost-function discrimination. Winner gets frozen in the verdict doc
and re-verified on a cam1 window (transfer check) before any counting.

Usage: py -X utf8 scripts/v2_cost_sweep.py runs/v2_week1/tracklets_cam2_study_0700.npz
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import candidate_links, fit_motion_residual, load_table  # noqa: E402
from v2_frag_instrument import (GAP_CLASSES, SEED, cut_donor,  # noqa: E402
                                pick_donors, rebuild_table)

COMBOS = [("fwd", "off"), ("fwd", "gated"),
          ("min", "off"), ("min", "gated"),
          ("mean", "off"), ("mean", "gated")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tables", nargs="+")
    args = ap.parse_args()
    for path in args.tables:
        t = load_table(path)
        rng = np.random.default_rng(SEED)
        donors = pick_donors(t, rng)
        cal = fit_motion_residual(t)
        print(f"\n=== {path} (donors pool={len(donors)}) ===")
        print(f"{'pos':>5} {'vel':>6} | " + " | ".join(
            f"g={g}: r1%/miss" for g in GAP_CLASSES))
        for pos_mode, vel_mode in COMBOS:
            cells = []
            for g in GAP_CLASSES:
                rng_g = np.random.default_rng(SEED + int(g * 10))
                cuts = {}
                for d in donors:
                    tr = t["rows"][int(t["starts"][d]):int(t["ends"][d])]
                    c = cut_donor(tr, t["fps"], g, rng_g)
                    if c is not None:
                        cuts[int(d)] = c
                t2, fragmap = rebuild_table(t, cuts)
                a_of = {d: i for i, (d, p) in fragmap.items() if p == "A"}
                b_of = {d: i for i, (d, p) in fragmap.items() if p == "B"}
                ii, jj, dts, costs, hyps = candidate_links(
                    t2, cal, pos_mode=pos_mode, vel_mode=vel_mode)
                outs = {}
                for k in range(len(ii)):
                    outs.setdefault(int(ii[k]), []).append(
                        (float(costs[k]), int(jj[k])))
                present = rank1 = 0
                for d in cuts:
                    A, B = a_of[d], b_of[d]
                    lst = outs.get(A, [])
                    tc = [c for c, j in lst if j == B]
                    if not tc:
                        continue
                    present += 1
                    if all(c >= tc[0] for c, j in lst if j != B):
                        rank1 += 1
                miss = len(cuts) - present
                cells.append(f"{100*rank1/max(present,1):4.0f}/{miss:<3}")
            print(f"{pos_mode:>5} {vel_mode:>6} | " + " | ".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
