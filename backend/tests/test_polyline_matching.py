"""Unit tests for polyline-based origin attribution + destination scoring.

These cover the Phase-1 helpers in:
  backend/services/origin_detector.py
    - point_to_polyline_distance
    - average_perpendicular_distance
    - _entry_segment
    - score_origin_by_polyline
  backend/services/trajectory_classifier.py
    - _path_hausdorff_oneway
    - score_destination_by_polyline

The Sunnyvale-shaped fixtures encode the geometry that matters for the
real bug we're solving: edge-leg origins (L19 at lower-left), close-
together legs (L18 and L20 both westbound), and curving roads (the
through-pair polylines actually bend through the intersection).
"""
import math

import pytest

from backend.services.origin_detector import (
    _entry_segment,
    _point_to_segment_distance,
    average_perpendicular_distance,
    point_to_polyline_distance,
    score_origin_by_polyline,
)
from backend.services.trajectory_classifier import (
    _path_hausdorff_oneway,
    score_destination_by_polyline,
)


# ---------------------------------------------------------------------------
# Sunnyvale-shaped fixtures. Polylines reflect approximate real geometry:
# Belt Line bends through the intersection (L18<->L19), Northwest Dr is a
# terminating side street (L21), Private Driveway is the right-edge stub
# (L20). All polylines are listed off-frame-entry -> off-frame-exit.
# ---------------------------------------------------------------------------

SUNNYVALE_PATHS = [
    # L18 (SB Belt Line, origin ~474,211) -> L19 (NB Belt Line, ~85,370) THROUGH
    # The road curves through the intersection — entry comes in from upper
    # right, bends through center, exits lower left.
    {"path_id": 1, "camera_id": 1, "origin_leg_id": 18, "destination_leg_id": 19,
     "polyline": [[610, 180], [500, 200], [400, 235], [300, 290],
                  [200, 335], [85, 370], [10, 410]],
     "movement_label": "through", "supporting_count": 250, "source": "manual"},
    # L19 (NB) -> L18 (SB) THROUGH — the reverse curve
    {"path_id": 2, "camera_id": 1, "origin_leg_id": 19, "destination_leg_id": 18,
     "polyline": [[10, 410], [85, 370], [200, 335], [300, 290],
                  [400, 235], [500, 200], [610, 180]],
     "movement_label": "through", "supporting_count": 230, "source": "manual"},
    # L18 -> L21 (Northwest Dr) RIGHT TURN — sharper bend toward upper-middle
    {"path_id": 3, "camera_id": 1, "origin_leg_id": 18, "destination_leg_id": 21,
     "polyline": [[610, 180], [500, 200], [400, 220], [320, 230],
                  [250, 235], [217, 234], [180, 230]],
     "movement_label": "right", "supporting_count": 80, "source": "manual"},
    # L20 (driveway) -> L19 (NB Belt Line) LEFT — turn out of driveway
    {"path_id": 4, "camera_id": 1, "origin_leg_id": 20, "destination_leg_id": 19,
     "polyline": [[630, 320], [547, 326], [400, 340], [200, 360],
                  [85, 370], [10, 410]],
     "movement_label": "left", "supporting_count": 12, "source": "manual"},
]


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------

class TestPointToSegmentDistance:
    def test_perpendicular_to_segment(self):
        # Point (5, 5) perpendicular-distance 5 from y=0 segment
        d = _point_to_segment_distance(5, 5, 0, 0, 10, 0)
        assert d == pytest.approx(5.0)

    def test_beyond_endpoint_a(self):
        # Point (-3, 0) is past the (0,0) end of the segment — distance is
        # straight-line distance to that endpoint.
        d = _point_to_segment_distance(-3, 0, 0, 0, 10, 0)
        assert d == pytest.approx(3.0)

    def test_beyond_endpoint_b(self):
        d = _point_to_segment_distance(15, 0, 0, 0, 10, 0)
        assert d == pytest.approx(5.0)

    def test_degenerate_segment_uses_point_distance(self):
        # Zero-length "segment" — distance falls back to point-to-point.
        d = _point_to_segment_distance(3, 4, 0, 0, 0, 0)
        assert d == pytest.approx(5.0)


class TestPointToPolylineDistance:
    def test_takes_shortest_across_segments(self):
        # Polyline with an L-shape: vertical from (0,0)-(0,10), then
        # horizontal (0,10)-(10,10). Point (3, 7) is closer to vertical leg.
        poly = [[0, 0], [0, 10], [10, 10]]
        d = point_to_polyline_distance((3, 7), poly)
        assert d == pytest.approx(3.0)

    def test_empty_polyline_returns_inf(self):
        assert point_to_polyline_distance((1, 1), []) == float("inf")


class TestAveragePerpendicularDistance:
    def test_all_points_on_polyline_is_zero(self):
        poly = [[0, 0], [100, 0]]
        pts = [(10, 0), (50, 0), (90, 0)]
        assert average_perpendicular_distance(pts, poly) == pytest.approx(0.0)

    def test_constant_offset_returns_offset(self):
        # Polyline along y=0, points all at y=5 -> mean dist = 5
        poly = [[0, 0], [100, 0]]
        pts = [(10, 5), (50, 5), (90, 5)]
        assert average_perpendicular_distance(pts, poly) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Entry-segment slicing
# ---------------------------------------------------------------------------

class TestEntrySegment:
    def test_short_polyline_returned_intact(self):
        assert _entry_segment([[0, 0], [10, 10]]) == [[0, 0], [10, 10]]

    def test_long_polyline_keeps_first_half_inclusive(self):
        # 11-point polyline -> first ceil(11/2)+1 = 7 points
        poly = [[i, 0] for i in range(11)]
        seg = _entry_segment(poly)
        assert len(seg) == 7
        assert seg[0] == [0, 0]
        assert seg[-1] == [6, 0]


# ---------------------------------------------------------------------------
# score_origin_by_polyline — Sunnyvale-shaped integration tests
# ---------------------------------------------------------------------------

class TestScoreOriginByPolyline:
    def test_curving_traj_matches_curving_path(self):
        # A trajectory that comes in along L18's natural curve. The first 6
        # points trace the entry segment of path 1 (L18->L19 through).
        prefix = [(605, 182), (560, 195), (510, 205), (460, 220),
                  (410, 235), (360, 255)]
        r = score_origin_by_polyline(prefix, SUNNYVALE_PATHS,
                                     max_avg_distance_px=30.0)
        assert r["origin_leg_id"] == 18

    def test_far_off_axis_returns_none(self):
        # Prefix at y=500 (off all polylines by >100 px) -> no match
        prefix = [(300, 500), (320, 500), (340, 500), (360, 500)]
        r = score_origin_by_polyline(prefix, SUNNYVALE_PATHS,
                                     max_avg_distance_px=30.0)
        assert r["origin_leg_id"] is None

    def test_radius_filter_rejects_marginal_match(self):
        # A prefix ~20 px off L18's entry segment matches L18 at loose
        # threshold but is rejected at tight threshold.
        prefix = [(605, 200), (560, 215), (510, 225), (460, 240)]
        loose = score_origin_by_polyline(prefix, SUNNYVALE_PATHS,
                                         max_avg_distance_px=30.0)
        tight = score_origin_by_polyline(prefix, SUNNYVALE_PATHS,
                                         max_avg_distance_px=5.0)
        assert loose["origin_leg_id"] == 18
        assert tight["origin_leg_id"] is None

    def test_empty_paths_returns_none(self):
        prefix = [(100, 100), (110, 100), (120, 100)]
        r = score_origin_by_polyline(prefix, [], max_avg_distance_px=30.0)
        assert r["origin_leg_id"] is None
        assert r["considered"] == 0

    def test_ties_broken_by_supporting_count(self):
        # Two paths with identical entry segments but different support counts.
        # When distance ties, the higher-supporting path wins.
        paths = [
            {"path_id": 1, "origin_leg_id": 1, "destination_leg_id": 2,
             "polyline": [[0, 0], [50, 0], [100, 0], [200, 0]],
             "movement_label": "through", "supporting_count": 10},
            {"path_id": 2, "origin_leg_id": 1, "destination_leg_id": 3,
             "polyline": [[0, 0], [50, 0], [100, 0], [200, 100]],
             "movement_label": "right", "supporting_count": 100},
        ]
        # Prefix on the shared portion only — both score 0
        prefix = [(10, 0), (30, 0), (50, 0)]
        r = score_origin_by_polyline(prefix, paths)
        assert r["origin_leg_id"] == 1
        # Both paths have origin_leg_id=1 anyway, but path_id should be the
        # high-support one (path_id=2 with count 100).
        assert r["path_id"] == 2


# ---------------------------------------------------------------------------
# score_destination_by_polyline
# ---------------------------------------------------------------------------

class TestScoreDestinationByPolyline:
    def test_l18_curving_through_picks_l19(self):
        # Full L18->L19 through trajectory follows path 1's polyline.
        traj = [(605, 182), (500, 200), (400, 235), (300, 290),
                (200, 335), (85, 370), (10, 410)]
        r = score_destination_by_polyline(traj, origin_leg_id=18,
                                           paths=SUNNYVALE_PATHS,
                                           max_avg_distance_px=30.0)
        assert r["destination_leg_id"] == 19
        assert r["movement_label"] == "through"

    def test_l18_right_turn_picks_l21(self):
        # Full L18->L21 right turn follows path 3.
        traj = [(605, 182), (500, 200), (400, 220), (320, 230),
                (250, 235), (217, 234)]
        r = score_destination_by_polyline(traj, origin_leg_id=18,
                                           paths=SUNNYVALE_PATHS,
                                           max_avg_distance_px=30.0)
        assert r["destination_leg_id"] == 21
        assert r["movement_label"] == "right"

    def test_only_paths_from_origin_considered(self):
        # An L20 vehicle trajectory tested with origin_leg_id=18 should NOT
        # match any path starting from L18, even if the trajectory's shape
        # roughly matches path 4 (which starts from L20).
        l20_traj = [(630, 320), (547, 326), (400, 340), (200, 360), (85, 370)]
        r = score_destination_by_polyline(l20_traj, origin_leg_id=18,
                                           paths=SUNNYVALE_PATHS,
                                           max_avg_distance_px=30.0)
        # No L18-origin path matches this trajectory's spatial shape, so None.
        # (Verifies that we filter by origin_leg_id, not just take the best
        # match across all paths.)
        assert r["destination_leg_id"] is None

    def test_no_paths_returns_none(self):
        r = score_destination_by_polyline([(1, 2), (3, 4)],
                                           origin_leg_id=18, paths=[])
        assert r["destination_leg_id"] is None
        assert r["considered"] == 0


class TestPathHausdorffOneway:
    def test_aligned_trajectory_distance_zero(self):
        poly = [[0, 0], [100, 0]]
        traj = [(10, 0), (50, 0), (90, 0)]
        assert _path_hausdorff_oneway(traj, poly) == pytest.approx(0.0)

    def test_empty_inputs_return_inf(self):
        assert _path_hausdorff_oneway([], [[0, 0], [10, 0]]) == float("inf")
        assert _path_hausdorff_oneway([(1, 1)], []) == float("inf")
