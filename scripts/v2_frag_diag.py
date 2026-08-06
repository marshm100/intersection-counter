"""Pipeline-V2 — instrument diagnostic: WHY does a stitcher miss true pairs?

For one gap class, rebuilds the fragmented table, then reports per donor:
  - true link present in candidate set? at what cost?
  - rank of the true link among candidates OUT of A and INTO B;
  - the solver's actual disposition of A-end and B-start (linked-true /
    welded-to-other / terminated / dropped).
Prints the aggregate fate table — the debugging instrument for cost design.

Usage: py -X utf8 scripts/v2_frag_diag.py runs/v2_week1/tracklets_cam2_study_0700.npz --gap 0.5 --stitcher mcf
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import candidate_links, fit_motion_residual, load_table  # noqa: E402
from v2_frag_instrument import cut_donor, pick_donors, rebuild_table, SEED  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("--gap", type=float, default=0.5)
    ap.add_argument("--stitcher", default="mcf", choices=["greedy", "mcf"])
    args = ap.parse_args()

    t = load_table(args.table)
    rng = np.random.default_rng(SEED)
    donors = pick_donors(t, rng)
    cal = fit_motion_residual(t)

    rng_g = np.random.default_rng(SEED + int(args.gap * 10))
    cuts = {}
    for d in donors:
        tr = t["rows"][int(t["starts"][d]):int(t["ends"][d])]
        c = cut_donor(tr, t["fps"], args.gap, rng_g)
        if c is not None:
            cuts[int(d)] = c
    t2, fragmap = rebuild_table(t, cuts)
    a_of = {d: i for i, (d, p) in fragmap.items() if p == "A"}
    b_of = {d: i for i, (d, p) in fragmap.items() if p == "B"}

    ii, jj, dts, costs, hyps = candidate_links(t2, cal)
    out_of = {}
    into = {}
    for k in range(len(ii)):
        out_of.setdefault(int(ii[k]), []).append((float(costs[k]), int(jj[k])))
        into.setdefault(int(jj[k]), []).append((float(costs[k]), int(ii[k])))

    if args.stitcher == "mcf":
        from v2_assemble import stitch_mcf
        links, chains, dropped = stitch_mcf(t2, cal)
        dropped = set(dropped)
    else:
        from v2_baseline_greedy import stitch_greedy
        links, chains = stitch_greedy(t2, cal)
        dropped = set()
    nxt = {i: j for i, j in links}
    prv = {j: i for i, j in links}

    fates = Counter()
    cand_stats = Counter()
    true_costs, best_rival = [], []
    for d in sorted(cuts):
        A, B = a_of[d], b_of[d]
        outs = sorted(out_of.get(A, []))
        true_entry = [c for c, j in outs if j == B]
        if not true_entry:
            cand_stats["true_link_MISSING"] += 1
        else:
            cand_stats["true_link_present"] += 1
            true_costs.append(true_entry[0])
            rank = 1 + sum(1 for c, j in outs if j != B and c < true_entry[0])
            cand_stats[f"rank_{min(rank,4)}{'+' if rank>=4 else ''}"] += 1
            rivals = [c for c, j in outs if j != B]
            if rivals:
                best_rival.append(min(rivals))
        got = nxt.get(A)
        if got == B:
            fates["A->B linked (TRUE)"] += 1
        elif got is not None:
            fates["A welded to other"] += 1
        elif A in dropped:
            fates["A dropped"] += 1
        else:
            fates["A terminated (no link)"] += 1
        gin = prv.get(B)
        if gin == A:
            pass
        elif gin is not None:
            fates["B welded from other"] += 1
        elif B in dropped:
            fates["B dropped"] += 1
        else:
            fates["B unlinked (interior birth)"] += 1

    print(f"donors={len(cuts)} gap={args.gap}s stitcher={args.stitcher}")
    print("candidates:", dict(cand_stats))
    if true_costs:
        print(f"true-link cost: med={np.median(true_costs):.2f} "
              f"p90={np.percentile(true_costs,90):.2f}")
    if best_rival:
        print(f"best-rival cost: med={np.median(best_rival):.2f}")
    print("fates:", dict(fates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
