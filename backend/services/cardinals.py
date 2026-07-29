"""Cardinal-direction convention (project-wide).

A leg's ``cardinal_direction`` is its POSITION at the intersection — the arm it
sits on (N/NE/E/SE/S/SW/W/NW). The APPROACH is named by the traffic's direction
of travel, which is the OPPOSITE compass direction: a leg on the SE corner
carries NW-bound traffic. This matches the standard TMC convention — a
"Northbound approach" is the traffic heading north, located on the south side
(see ITSIQA / Miovision approach-naming).

So: cardinal = position; approach (bound) = ``bound_approach(cardinal)`` =
opposite(position). Anything that renders an approach name or a bound direction
to a user (Excel headers, QA labels, spot-count keys) must go through
``bound_approach``; turn classification (left/right/through) is convention-
invariant and does not.
"""
from __future__ import annotations

import math

OPPOSITE = {
    "N": "S", "S": "N", "E": "W", "W": "E",
    "NE": "SW", "SW": "NE", "NW": "SE", "SE": "NW",
}

# clockwise from north — the 8-way snap ring the cardinal wizard uses
COMPASS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def derive_cardinals(points: dict, north_deg: float) -> dict:
    """The Stage-4 cardinal wizard's one source of truth
    (plan_stage4_childtest_ux 4.3): leg origin positions in IMAGE
    coordinates (y grows down) + the image-space direction SITE NORTH
    points (degrees, 0 = screen-up, clockwise) -> each leg's cardinal
    POSITION.

    ASSIGNMENT-BASED, not per-leg snap (6.4 rehearsal finding #1,
    2026-07-29): on oblique views the image angles between arms are
    perspective-compressed, and on 3-leg Ts the centroid skews — cam3's
    correct N/S/W was UNREACHABLE at any dial angle under independent
    8-way snapping. What perspective cannot distort is the CYCLIC ORDER
    of the arms around the intersection, so the wizard assigns DISTINCT
    cardinals preserving that order, minimizing total circular error to
    the compass slots. Symmetric 4-leg layouts get exactly the old
    answer; skewed real views get the nearest consistent one.

    points: {key: (x, y)}. Returns {key: 'N'|'NE'|...}. Keys pass
    through untouched (the client uses leg indices)."""
    if not points:
        return {}
    cx = sum(p[0] for p in points.values()) / len(points)
    cy = sum(p[1] for p in points.values()) / len(points)
    rel = {}
    for key, (x, y) in points.items():
        dx, dy = x - cx, y - cy
        # 0 = screen-up, clockwise positive (image y is down, so -dy is up)
        bearing = (math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0
        rel[key] = (bearing - north_deg) % 360.0
    keys = sorted(rel, key=lambda k: rel[k])
    n = len(keys)
    if n > len(COMPASS_8):
        return {k: COMPASS_8[round(rel[k] / 45.0) % 8] for k in keys}

    def circ(a: float, b: float) -> float:
        d = abs(a - b) % 360.0
        return d if d <= 180.0 else 360.0 - d

    from itertools import combinations
    best: tuple[float, dict] | None = None
    for slots in combinations(range(8), n):
        for rot in range(n):              # which leg takes the first slot
            cost = 0.0
            assign = {}
            for i, s in enumerate(slots):
                k = keys[(rot + i) % n]
                cost += circ(rel[k], s * 45.0)
                assign[k] = COMPASS_8[s]
            if best is None or cost < best[0]:
                best = (cost, assign)
    return best[1] if best else {}


def bound_approach(cardinal: str | None) -> str:
    """Direction-of-travel (bound) for a leg whose cardinal is its POSITION.

    bound = opposite(position). Unknown / empty values pass through unchanged so
    a mis-set cardinal is visible rather than silently remapped.
    """
    c = (cardinal or "").upper()
    return OPPOSITE.get(c, c)
