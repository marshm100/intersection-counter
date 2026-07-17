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

OPPOSITE = {
    "N": "S", "S": "N", "E": "W", "W": "E",
    "NE": "SW", "SW": "NE", "NW": "SE", "SE": "NW",
}


def bound_approach(cardinal: str | None) -> str:
    """Direction-of-travel (bound) for a leg whose cardinal is its POSITION.

    bound = opposite(position). Unknown / empty values pass through unchanged so
    a mis-set cardinal is visible rather than silently remapped.
    """
    c = (cardinal or "").upper()
    return OPPOSITE.get(c, c)
