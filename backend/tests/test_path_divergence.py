"""Unit tests — path_divergence (plan_cam5_lane_echo_2026-07-27, phase 0
item 3). Synthetic geometry: a thru path along y=0 and a right-turn path
that shares the first 100 px then bends away."""
from __future__ import annotations

from backend.services.path_divergence import (
    AMBIGUITY_PX, build_divergence_map, coverage_s_max, divergence_s,
    reaches_divergence)

# Shared-entry geometry: both start at (0,0) heading +x; the turn bends at
# x=100 toward +y, reaching y=200 by x=150 (fully separated well past amb).
THRU = [(0, 0), (400, 0)]
TURN = [(0, 0), (100, 0), (150, 100), (150, 300)]
PATHS = [
    {"origin_leg_id": 1, "destination_leg_id": 2, "polyline": THRU},
    {"origin_leg_id": 1, "destination_leg_id": 3, "polyline": TURN},
    # single-path origin -> excluded from the map
    {"origin_leg_id": 9, "destination_leg_id": 2, "polyline": [(0, 50), (400, 50)]},
]


def test_divergence_point_where_geometry_separates():
    # Along TURN, separation from THRU exceeds 30 px a bit after the bend:
    # y > 30 happens ~15 px of arc past (100, 0) plus sampling granularity.
    s = divergence_s([(float(x), float(y)) for x, y in TURN],
                     [(float(x), float(y)) for x, y in THRU])
    assert s is not None
    assert 100 <= s <= 145        # after the shared stretch, near the bend


def test_parallel_within_amb_never_diverges():
    a = [(0.0, 0.0), (400.0, 0.0)]
    b = [(0.0, 20.0), (400.0, 20.0)]   # 20 px apart < AMBIGUITY_PX
    assert divergence_s(a, b) is None
    assert AMBIGUITY_PX == 30.0        # the builder's constant, unchanged


def test_map_covers_multi_path_origins_only():
    m = build_divergence_map(PATHS)
    assert (1, 2) in m and (1, 3) in m
    assert (9, 2) not in m
    assert m[(1, 3)]["div"][2] is not None


def test_coverage_and_reaches():
    m = build_divergence_map(PATHS)
    # A stub covering only the shared stretch: cannot claim the turn.
    stub = [(float(x), 0.0) for x in range(0, 90, 5)]
    assert reaches_divergence(stub, (1, 3), m) is False
    # A track through the bend and beyond: reaches divergence.
    full = [(float(x), 0.0) for x in range(0, 100, 5)] + \
           [(110.0, 20.0), (130.0, 60.0), (150.0, 120.0), (150.0, 250.0)]
    assert reaches_divergence(full, (1, 3), m) is True
    # Far-away points do not cover (lateral gate 2*amb).
    far = [(x, 500.0) for x in (0.0, 100.0, 200.0)]
    assert coverage_s_max(far, m[(1, 3)]["poly"]) == 0.0


def test_reaches_none_when_undecidable():
    a = {"origin_leg_id": 1, "destination_leg_id": 2,
         "polyline": [(0, 0), (400, 0)]}
    b = {"origin_leg_id": 1, "destination_leg_id": 3,
         "polyline": [(0, 10), (400, 10)]}   # never separates
    m = build_divergence_map([a, b])
    assert reaches_divergence([(50.0, 0.0)], (1, 2), m) is None
    assert reaches_divergence([(50.0, 0.0)], (5, 5), m) is None
