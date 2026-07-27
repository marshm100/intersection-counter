"""Divergence geometry over the applied bank (plan_cam5_lane_echo_2026-07-27,
phase 0 item 3 — feeds the C component's claim-eligibility rule and the
chain-union coverage recovery).

For paths sharing an ORIGIN leg, the divergence point of path P from a
sibling Q is the first arc position s along P where P has separated from Q
by more than `amb` px (the builder's ambiguity constant, 30 — no new
constants). A track (or chain-union) whose projected coverage on P never
reaches past P's divergence from a sibling cannot geometrically be told
apart from that sibling over the covered stretch.

Pure geometry, no DB access: callers pass path dicts with
origin_leg_id / destination_leg_id / polyline (list of [x, y]).
"""
from __future__ import annotations

import math

AMBIGUITY_PX = 30.0   # = build_bank_gtfree's ambiguity_px default


def _pts(path) -> list[tuple[float, float]]:
    pl = path["polyline"]
    if isinstance(pl, str):
        import json
        pl = json.loads(pl)
    return [(float(p[0]), float(p[1])) for p in pl]


def _seg_dist(pt, a, b) -> float:
    ax, ay = a
    bx, by = b
    px, py = pt[0] - ax, pt[1] - ay
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, (px * dx + py * dy) / L2))
    return math.hypot(pt[0] - (ax + t * dx), pt[1] - (ay + t * dy))


def _poly_dist(pt, poly) -> float:
    return min(_seg_dist(pt, poly[i], poly[i + 1])
               for i in range(len(poly) - 1))


def _arc_positions(poly) -> list[float]:
    s = [0.0]
    for i in range(len(poly) - 1):
        s.append(s[-1] + math.hypot(poly[i + 1][0] - poly[i][0],
                                    poly[i + 1][1] - poly[i][1]))
    return s


def _sample(poly, step: float = 5.0):
    """(s, point) samples every `step` px of arc length."""
    arcs = _arc_positions(poly)
    total = arcs[-1]
    out = []
    s = 0.0
    seg = 0
    while s <= total:
        while seg < len(arcs) - 2 and arcs[seg + 1] < s:
            seg += 1
        span = arcs[seg + 1] - arcs[seg]
        t = 0.0 if span == 0 else (s - arcs[seg]) / span
        a, b = poly[seg], poly[seg + 1]
        out.append((s, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))))
        s += step
    return out


def divergence_s(p_poly, q_poly, amb: float = AMBIGUITY_PX) -> float | None:
    """First arc position s along P where P is > amb px from Q.
    None -> P never separates from Q (parallel/contained within amb)."""
    if len(p_poly) < 2 or len(q_poly) < 2:
        return None
    for s, pt in _sample(p_poly):
        if _poly_dist(pt, q_poly) > amb:
            return s
    return None


def build_divergence_map(paths, amb: float = AMBIGUITY_PX) -> dict:
    """{(o, d): {'length': arc_len, 'poly': [(x,y),...],
    'div': {sibling_d: s_div | None}}} over every origin group with
    >= 2 paths."""
    by_origin: dict = {}
    for p in paths:
        o, d = p.get("origin_leg_id"), p.get("destination_leg_id")
        if o is None or d is None or o == d:
            continue
        by_origin.setdefault(o, {})[d] = _pts(p)
    out = {}
    for o, sibs in by_origin.items():
        if len(sibs) < 2:
            continue
        for d, poly in sibs.items():
            div = {d2: divergence_s(poly, poly2, amb)
                   for d2, poly2 in sibs.items() if d2 != d}
            out[(o, d)] = {"length": _arc_positions(poly)[-1],
                           "poly": poly, "div": div}
    return out


def coverage_s_max(points, poly) -> float:
    """Max arc position on `poly` covered by `points` (projection of each
    point onto its nearest segment). Points farther than 2*AMBIGUITY_PX
    laterally are ignored (they don't cover the path)."""
    if len(poly) < 2:
        return 0.0
    arcs = _arc_positions(poly)
    s_max = 0.0
    for pt in points:
        best = (float("inf"), 0.0)
        for i in range(len(poly) - 1):
            a, b = poly[i], poly[i + 1]
            ax, ay = a
            dx, dy = b[0] - ax, b[1] - ay
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(
                0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / L2))
            proj = (ax + t * dx, ay + t * dy)
            dist = math.hypot(pt[0] - proj[0], pt[1] - proj[1])
            if dist < best[0]:
                best = (dist, arcs[i] + t * (arcs[i + 1] - arcs[i]))
        if best[0] <= 2 * AMBIGUITY_PX and best[1] > s_max:
            s_max = best[1]
    return s_max


def reaches_divergence(points, cell, div_map, margin: float = 0.0) -> bool | None:
    """Does this point set's coverage of `cell`'s path reach past its
    divergence from EVERY sibling? None -> cell not in the map (single-path
    origin) or no sibling ever diverges (undecidable by geometry).
    `margin` px of extra arc required past the farthest divergence."""
    info = div_map.get(cell)
    if info is None:
        return None
    div_ss = [s for s in info["div"].values() if s is not None]
    if not div_ss:
        return None
    s_max = coverage_s_max(points, info["poly"])
    return s_max > max(div_ss) + margin
