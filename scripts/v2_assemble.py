"""Pipeline-V2 D3 — global tracklet assembly via min-cost flow
(plan_v2_week1_derisk §D3; formulation per research_synthesis §S4).

Node-split MCF over tracklets: each tracklet used at most once (structural
exclusivity); the solver may DROP a tracklet whose evidence can't pay for
its birth+death (phantom filter); births/deaths are CHEAP at explained
locations (leg gates / frame border / window edges) and EXPENSIVE
mid-scene — so mid-scene fragmentation is structurally forced to stitch,
through candidate links priced by the self-calibrated CV/ZV hypotheses.

All cost weights are in EVIDENCE UNITS (1.0 = the median full-journey
tracklet's evidence) — the constants ledger lists the three structural
ratios; nothing is per-camera.

Import: stitch_mcf(table, cal) -> (links, chains)
CLI: py -X utf8 scripts/v2_assemble.py runs/v2_week1/tracklets_cam2_study_0700.npz
"""
from __future__ import annotations

import argparse
import json
import sys
import time

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import (candidate_links, chains_from_links,  # noqa: E402
                       fit_motion_residual, load_table)

SCALE = 1000               # integerization for OR-Tools
# Constants ledger (structural ratios, unit = median full-track evidence):
B_INTERIOR = 2.0           # mid-scene birth penalty
D_INTERIOR = 2.0           # mid-scene death penalty
LINK_UNIT = 0.5            # link cost = LINK_UNIT * normalized residual
BORDER_FRAC = 0.03         # frame-border band as fraction of frame extent
EDGE_S = 2.0               # window-start/end slack (seconds)


def _seg_dist(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    if L2 < 1e-9:
        return float(np.hypot(px - ax, py - ay))
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
    return float(np.hypot(px - (ax + t * vx), py - (ay + t * vy)))


def explained_mask(t: dict, alpha: float, beta: float):
    """(birth_explained, death_explained) — near a leg gate, near the frame
    border, or at the window's temporal edges."""
    gates = t["meta"].get("gates", {})
    f_lo, f_hi = t["meta"]["frames"]
    fps = t["fps"]
    # crossing localization noise: bbox jitter + ~3 frame-steps of travel —
    # NOT a second of motion (54 px mislabeled mid-scene endpoints as
    # gate-explained; day-1 instrument finding #2)
    gate_tol = 2.0 * alpha + 3.0 * beta / fps
    xs = np.concatenate([t["x0"], t["x1"]])
    ys = np.concatenate([t["y0"], t["y1"]])
    W, H = xs.max(), ys.max()
    band = BORDER_FRAC * max(W, H)
    birth = np.zeros(t["n"], bool)
    death = np.zeros(t["n"], bool)
    for i in range(t["n"]):
        s = (t["x0"][i], t["y0"][i])
        e = (t["x1"][i], t["y1"][i])
        near_gate_s = any(_seg_dist(s, g[0], g[1]) <= gate_tol
                          for g in gates.values())
        near_gate_e = any(_seg_dist(e, g[0], g[1]) <= gate_tol
                          for g in gates.values())
        border_s = (s[0] <= band or s[1] <= band
                    or s[0] >= W - band or s[1] >= H - band)
        border_e = (e[0] <= band or e[1] <= band
                    or e[0] >= W - band or e[1] >= H - band)
        birth[i] = near_gate_s or border_s or (t["f0"][i] <= f_lo + EDGE_S * fps)
        death[i] = near_gate_e or border_e or (t["f1"][i] >= f_hi - EDGE_S * fps)
    return birth, death


def stitch_mcf(t: dict, cal: dict | None = None):
    from ortools.graph.python import min_cost_flow as mcfmod
    if cal is None:
        cal = fit_motion_residual(t)
    n = t["n"]
    ii, jj, dts, costs, hyps = candidate_links(t, cal)
    birth_ok, death_ok = explained_mask(t, cal["alpha"], cal["beta"])

    ev_raw = np.asarray(t["n_pts"] * t["mean_conf"], dtype=float)
    if "tag" in t and np.any(t["tag"] == 0):
        ev_norm = float(np.median(ev_raw[t["tag"] == 0]))
    else:
        ev_norm = float(np.median(ev_raw))
    evidence = np.minimum(1.0, ev_raw / max(ev_norm, 1e-9))

    # nodes: S=0, T=1, u_i=2+2i, v_i=3+2i
    S, T = 0, 1
    smcf = mcfmod.SimpleMinCostFlow()
    add = smcf.add_arc_with_capacity_and_unit_cost
    for i in range(n):
        u, v = 2 + 2 * i, 3 + 2 * i
        add(u, v, 1, -int(round(SCALE * evidence[i])))
        add(S, u, 1, 0 if birth_ok[i] else int(round(SCALE * B_INTERIOR)))
        add(v, T, 1, 0 if death_ok[i] else int(round(SCALE * D_INTERIOR)))
    link_arc_ids = {}
    for k in range(len(ii)):
        i_k, j_k = int(ii[k]), int(jj[k])
        # A link that overrides an EXPLAINED endpoint pays that endpoint's
        # interior price — otherwise welding a fragment into any gate-born
        # track is free profit (day-1 instrument finding, on the record).
        lc = (LINK_UNIT * float(costs[k])
              + (B_INTERIOR if birth_ok[j_k] else 0.0)
              + (D_INTERIOR if death_ok[i_k] else 0.0))
        a = add(3 + 2 * i_k, 2 + 2 * j_k, 1, int(round(SCALE * lc)))
        link_arc_ids[a] = (i_k, j_k)
    bypass = add(S, T, n, 0)
    smcf.set_node_supply(S, n)
    smcf.set_node_supply(T, -n)
    status = smcf.solve()
    if status != smcf.OPTIMAL:
        raise RuntimeError(f"MCF not optimal: {status}")
    links = [link_arc_ids[a] for a in link_arc_ids if smcf.flow(a) > 0]
    # dropped tracklets = u->v arcs (id 3*i: each tracklet added 3 arcs) w/o flow
    dropped = {i for i in range(n) if smcf.flow(3 * i) == 0}
    chains = [c for c in chains_from_links(n, links)
              if not (len(c) == 1 and c[0] in dropped)]
    return links, chains, sorted(dropped)


P_EXPLAINED = 0.2   # terminate/spawn price at a gate/border/window edge
P_INTERIOR = 1.2    # terminate/spawn price mid-scene (constants ledger:
                    # structural ratio pair; a link A->B beats (dump A +
                    # spawn B) iff cost < d_A + b_B, so interior fragments
                    # pull hard to stitch while gate endpoints stay honest)


def stitch_assign(t: dict, cal: dict | None = None,
                  p_explained: float = P_EXPLAINED,
                  p_interior: float = P_INTERIOR):
    """Two-stage assembly, structure-aware bipartite assignment.

    Stage 1 — optimal end->start assignment where every END pays a
    position-priced terminate (cheap at exits: gates/border/window-edge;
    expensive mid-scene) and every START pays a position-priced spawn
    (cheap at entries; expensive mid-scene). Pure bipartite — no chain
    economics, no evidence bounties (day-1 lesson) — but the entry/exit
    STRUCTURE now discriminates: giving A its true interior-start B frees
    only a cheap gate spawn for the rival, so structure adds margin the
    pairwise cost lacks (day-2 lesson).
    Stage 2 — phantom filter on assembled chains (unchanged).
    """
    from ortools.graph.python import min_cost_flow as mcfmod
    if cal is None:
        cal = fit_motion_residual(t)
    n = t["n"]
    ii, jj, dts, costs, hyps = candidate_links(t, cal)
    birth_ok, death_ok = explained_mask(t, cal["alpha"], cal["beta"])
    d_price = np.where(death_ok, p_explained, p_interior)
    b_price = np.where(birth_ok, p_explained, p_interior)

    # Network: S=0, T=1, DUMP=2, SPARE=3, end_i=4+2i, start_i=5+2i.
    # ends: +1 supply each -> link or DUMP(d_i). starts: -1 demand each
    # <- link or SPARE(b_j). S supplies SPARE (n, relief arc SPARE->T for
    # the unused remainder); DUMP->T drains dumped ends. Balanced for any
    # number of accepted links.
    S, T, DUMP, SPARE = 0, 1, 2, 3
    smcf = mcfmod.SimpleMinCostFlow()
    add = smcf.add_arc_with_capacity_and_unit_cost
    for i in range(n):
        end_n, start_n = 4 + 2 * i, 5 + 2 * i
        add(end_n, DUMP, 1, int(round(SCALE * float(d_price[i]))))
        add(SPARE, start_n, 1, int(round(SCALE * float(b_price[i]))))
        smcf.set_node_supply(end_n, 1)
        smcf.set_node_supply(start_n, -1)
    link_arcs = {}
    for k in range(len(ii)):
        i_k, j_k = int(ii[k]), int(jj[k])
        a = add(4 + 2 * i_k, 5 + 2 * j_k, 1,
                int(round(SCALE * float(costs[k]))))
        link_arcs[a] = (i_k, j_k)
    add(DUMP, T, n, 0)
    add(S, SPARE, n, 0)
    add(SPARE, T, n, 0)
    smcf.set_node_supply(S, n)
    smcf.set_node_supply(T, -n)
    status = smcf.solve()
    if status != smcf.OPTIMAL:
        raise RuntimeError(f"assignment MCF not optimal: {status}")
    links = [link_arcs[a] for a in link_arcs if smcf.flow(a) > 0]
    chains = chains_from_links(n, links)

    # Stage 2: phantom filter at CHAIN level.
    ev_raw = np.asarray(t["n_pts"] * t["mean_conf"], dtype=float)
    if "tag" in t and np.any(t["tag"] == 0):
        ev_norm = float(np.median(ev_raw[t["tag"] == 0]))
    else:
        ev_norm = float(np.median(ev_raw))
    kept, dropped = [], []
    for ch in chains:
        ok = (birth_ok[ch[0]] or death_ok[ch[-1]]
              or ev_raw[list(ch)].sum() >= ev_norm)
        (kept if ok else dropped).append(ch)
    return links, kept, [c for ch in dropped for c in ch]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("--engine", default="assign", choices=["assign", "mcf"])
    args = ap.parse_args()
    t = load_table(args.table)
    cal = fit_motion_residual(t)
    t0 = time.time()
    fn = stitch_assign if args.engine == "assign" else stitch_mcf
    links, chains, dropped = fn(t, cal)
    multi = [c for c in chains if len(c) > 1]
    print(f"[D3:{args.engine}] {args.table}: links={len(links)} "
          f"chains>1={len(multi)} dropped_tracklets={len(dropped)} "
          f"(n={t['n']} -> {len(chains)} kept chains, {time.time()-t0:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
