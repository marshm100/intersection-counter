"""Pipeline-V2 D2 — greedy baseline stitcher (plan_v2_week1_derisk §D2).

The FLOOR any solver must beat: appearance-free greedy linking. Candidates
from v2_common.candidate_links (self-calibrated CV + zero-velocity
hypotheses); accept links cheapest-first, each end/start used at most once.
No global reasoning, no structure — deliberately dumb but honest.

Import: stitch_greedy(table) -> (links, chains). CLI: quick stats.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import (candidate_links, chains_from_links,  # noqa: E402
                       fit_motion_residual, load_table)

ACCEPT_COST = 1.5      # legacy fixed-threshold mode (kept for A/B archaeology)
RATIO = 0.7            # mutual-best ratio test: accept only if best/second
                       # < RATIO on BOTH sides — scale-free, so acceptance
                       # tightens automatically with scene density (the
                       # held-out G-A1 failure was a fixed threshold
                       # over-accepting at PM density). Value frozen from
                       # the day-4 instrument sweep (0.5 dead-zone / 0.9
                       # weld-prone; 0.7 = p0.91 @0.5s, links 692) —
                       # constants ledger; held-outs judge it blind.


def stitch_greedy(t: dict, cal: dict | None = None,
                  ratio: float | None = RATIO,
                  accept_cost: float = ACCEPT_COST):
    """Default: mutual-best + ratio acceptance. ratio=None reverts to the
    legacy fixed accept_cost (the mode that failed the held-outs)."""
    if cal is None:
        cal = fit_motion_residual(t)
    ii, jj, dt, cost, hyp = candidate_links(t, cal)
    if ratio is None:
        order = np.argsort(cost)
        used_end, used_start, links = set(), set(), []
        for k in order:
            if cost[k] > accept_cost:
                break
            i, j = int(ii[k]), int(jj[k])
            if i in used_end or j in used_start or i == j:
                continue
            used_end.add(i)
            used_start.add(j)
            links.append((i, j))
        return links, chains_from_links(t["n"], links)

    best_out: dict[int, tuple] = {}   # i -> (c1, j1, c2)
    best_in: dict[int, tuple] = {}    # j -> (c1, i1, c2)
    for k in range(len(ii)):
        i, j, c = int(ii[k]), int(jj[k]), float(cost[k])
        bo = best_out.get(i)
        if bo is None:
            best_out[i] = (c, j, np.inf)
        elif c < bo[0]:
            best_out[i] = (c, j, bo[0])
        elif c < bo[2]:
            best_out[i] = (bo[0], bo[1], c)
        bi = best_in.get(j)
        if bi is None:
            best_in[j] = (c, i, np.inf)
        elif c < bi[0]:
            best_in[j] = (c, i, bi[0])
        elif c < bi[2]:
            best_in[j] = (bi[0], bi[1], c)
    links = []
    for i, (c1, j, c2_out) in best_out.items():
        bi = best_in.get(j)
        if bi is None or bi[1] != i:
            continue                       # not mutual
        c2_in = bi[2]
        r_out = c1 / c2_out if np.isfinite(c2_out) else 0.0
        r_in = bi[0] / c2_in if np.isfinite(c2_in) else 0.0
        if r_out < ratio and r_in < ratio:
            links.append((i, j))
    return links, chains_from_links(t["n"], links)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    args = ap.parse_args()
    t = load_table(args.table)
    cal = fit_motion_residual(t)
    links, chains = stitch_greedy(t, cal)
    multi = [c for c in chains if len(c) > 1]
    print(f"[D2] {args.table}: "
          f"cal={ {k: (round(v, 1) if isinstance(v, float) else v) for k, v in cal.items() if k != 'table'} } "
          f"links={len(links)} chains>1={len(multi)} "
          f"(n={t['n']} -> {len(chains)} chains)")
    print(f"     residual table: {cal['table']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
