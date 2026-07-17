"""Partial-evidence posterior (item-8 mechanism 1, posterior half).

docs/plan_posterior_half_2026-07-15.md — when gate evidence cannot decide a
single cell, build an explicit posterior over the FEASIBLE cells and count at
the posterior max, recording the posterior + margin so Feeder-1 queues the
near-ties. Feasibility is the joint scorer's own admission (its `candidates`
list, docs in trajectory_classifier.score_path_joint) — this module adds NO
geometry constants of its own.

Weights: corpus-support PROPORTIONS x the scorer's shape squash. Proportions,
not absolutes, so standing-rule-2's scale-1 requirement holds by construction
(the same posterior falls out of a 30-min or a 2-h corpus with the same mix).
Add-one smoothing keeps a zero-support path feasible without letting it win a
tie against real traffic.

Pure math, no DB, no pipeline state — unit-tested standalone.
"""
from __future__ import annotations


def _weight(cand: dict) -> float:
    """(support + 1) x shape_term. shape_term is the joint scorer's own cost
    squash (1/(1+cost/10)) so shape influence here matches its influence in
    the composite — one squash, one semantics."""
    support = float(cand["path"].get("supporting_count") or 0)
    shape = 1.0 / (1.0 + float(cand["cost"]) / 10.0)
    return (support + 1.0) * shape


def _marginalize(cands: list[dict], key: str) -> tuple[dict, dict]:
    """(marginals {leg_id: prob}, best {leg_id: cand}) over cands grouped by
    path[key]. best = highest-weight candidate within each group (the concrete
    path an event lands on when its group wins)."""
    totals: dict = {}
    best: dict = {}
    for c in cands:
        leg = c["path"].get(key)
        if leg is None:
            continue
        w = _weight(c)
        totals[leg] = totals.get(leg, 0.0) + w
        if leg not in best or w > _weight(best[leg]):
            best[leg] = c
    z = sum(totals.values())
    if z <= 0.0:
        return {}, {}
    return {leg: w / z for leg, w in totals.items()}, best


def origin_posterior(cands: list[dict]) -> tuple[dict, dict]:
    """Branch 1 (unevidenced origin): marginals over the admitted candidates'
    origin legs. Returns ({origin_leg: prob}, {origin_leg: best cand})."""
    return _marginalize(cands, "origin_leg_id")


def destination_posterior(cands: list[dict]) -> tuple[dict, dict]:
    """Branch 2 (evidenced-truncated destination): marginals over destination
    legs of a TIED candidate set."""
    return _marginalize(cands, "destination_leg_id")


def tied_candidates(cands: list[dict], best_cost: float, band: float) -> list[dict]:
    """Candidates whose cost sits within `band` (a ratio) of the winner's —
    their separating geometry lies past the track's death point, so shape
    cannot rank them. A near-zero winner cost degenerates the ratio; treat
    everything under 1 px as tied with it (sub-pixel costs are noise)."""
    if best_cost < 1.0:
        return [c for c in cands if float(c["cost"]) < 1.0 or
                float(c["cost"]) <= best_cost + band * 10.0]
    lim = best_cost * (1.0 + band)
    return [c for c in cands if float(c["cost"]) <= lim]


def supports_posterior(paths: list[dict]) -> tuple[dict, dict]:
    """Rescue (evidenced track, nothing admitted, chain would DROP it):
    posterior over the evidenced origin's cells from corpus supports alone —
    no shape signal exists, so the margin is honest about that and Feeder-1
    queues it. Input = the origin-filtered bank paths (not scorer candidates).
    Returns ({destination_leg: prob}, {destination_leg: path})."""
    totals: dict = {}
    best: dict = {}
    for p in paths:
        leg = p.get("destination_leg_id")
        if leg is None:
            continue
        w = float(p.get("supporting_count") or 0) + 1.0
        totals[leg] = totals.get(leg, 0.0) + w
        cur = best.get(leg)
        if cur is None or w > (float(cur.get("supporting_count") or 0) + 1.0):
            best[leg] = p
    z = sum(totals.values())
    if z <= 0.0:
        return {}, {}
    return {leg: w / z for leg, w in totals.items()}, best
