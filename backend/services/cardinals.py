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
    POSITION, snapped 8-way around the legs' centroid.

    points: {key: (x, y)}. Returns {key: 'N'|'NE'|...}. Keys pass
    through untouched (the client uses leg indices)."""
    if not points:
        return {}
    cx = sum(p[0] for p in points.values()) / len(points)
    cy = sum(p[1] for p in points.values()) / len(points)
    out = {}
    for key, (x, y) in points.items():
        dx, dy = x - cx, y - cy
        # 0 = screen-up, clockwise positive (image y is down, so -dy is up)
        bearing = (math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0
        rel = (bearing - north_deg) % 360.0
        out[key] = COMPASS_8[round(rel / 45.0) % 8]
    return out


def bound_approach(cardinal: str | None) -> str:
    """Direction-of-travel (bound) for a leg whose cardinal is its POSITION.

    bound = opposite(position). Unknown / empty values pass through unchanged so
    a mis-set cardinal is visible rather than silently remapped.
    """
    c = (cardinal or "").upper()
    return OPPOSITE.get(c, c)
