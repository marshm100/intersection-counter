"""Tests for origin zone line-crossing detection geometry."""

import math
import pytest

from backend.services.origin_detector import (
    closest_zone,
    compute_reference_heading,
    crossing_direction,
    did_cross_line,
    distance_point_to_line,
    point_side_of_line,
)


class TestPointSideOfLine:
    """Tests for point_side_of_line()."""

    def test_horizontal_line_point_above(self):
        # Line from (100,200) → (300,200), point above at (200,180)
        side = point_side_of_line((200, 180), (100, 200), (300, 200))
        assert side != 0

    def test_horizontal_line_point_below(self):
        # Line from (100,200) → (300,200), point below at (200,220)
        side = point_side_of_line((200, 220), (100, 200), (300, 200))
        assert side != 0

    def test_horizontal_line_opposite_sides(self):
        # Points above and below a horizontal line should return opposite signs
        side_above = point_side_of_line((200, 180), (100, 200), (300, 200))
        side_below = point_side_of_line((200, 220), (100, 200), (300, 200))
        assert side_above == -side_below

    def test_point_on_line(self):
        # Point exactly on the line → returns 0
        side = point_side_of_line((200, 200), (100, 200), (300, 200))
        assert side == 0

    def test_vertical_line_opposite_sides(self):
        # Vertical line from (200,100) → (200,300)
        side_left = point_side_of_line((180, 200), (200, 100), (200, 300))
        side_right = point_side_of_line((220, 200), (200, 100), (200, 300))
        assert side_left != 0
        assert side_right != 0
        assert side_left == -side_right


class TestDidCrossLine:
    """Tests for did_cross_line()."""

    def test_crosses_horizontal_segment(self):
        # Movement (200,180) → (200,220) crosses horizontal line (100,200)→(300,200)
        assert did_cross_line((200, 180), (200, 220), (100, 200), (300, 200)) is True

    def test_stays_same_side(self):
        # Movement (200,180) → (200,190) stays above the line
        assert did_cross_line((200, 180), (200, 190), (100, 200), (300, 200)) is False

    def test_crosses_infinite_but_not_finite_left(self):
        # Movement at x=50 crosses the infinite line but NOT the finite segment [100,300]
        assert did_cross_line((50, 180), (50, 220), (100, 200), (300, 200)) is False

    def test_crosses_infinite_but_not_finite_right(self):
        # Movement at x=400 crosses the infinite line but NOT the finite segment
        assert did_cross_line((400, 180), (400, 220), (100, 200), (300, 200)) is False

    def test_diagonal_line_crossing(self):
        # Diagonal line from (0,0) → (100,100), movement that crosses
        assert did_cross_line((0, 50), (50, 0), (0, 0), (100, 100)) is True

    def test_parallel_movement(self):
        # Movement parallel to the line → False
        assert did_cross_line((100, 180), (300, 180), (100, 200), (300, 200)) is False


class TestCrossingDirection:
    """Tests for crossing_direction()."""

    def test_enter_horizontal(self):
        # Horizontal line (100,200)→(300,200).
        # Movement from right side (-1) to left side (+1) → 'enter'
        side_above = point_side_of_line((200, 180), (100, 200), (300, 200))
        side_below = point_side_of_line((200, 220), (100, 200), (300, 200))
        # Determine which side is -1 (exterior) and which is +1 (interior)
        if side_above == -1:
            result = crossing_direction((200, 180), (200, 220), (100, 200), (300, 200))
            assert result == "enter"
        else:
            result = crossing_direction((200, 220), (200, 180), (100, 200), (300, 200))
            assert result == "enter"

    def test_exit_horizontal(self):
        # Opposite direction should be 'exit'
        side_above = point_side_of_line((200, 180), (100, 200), (300, 200))
        if side_above == 1:
            result = crossing_direction((200, 180), (200, 220), (100, 200), (300, 200))
            assert result == "exit"
        else:
            result = crossing_direction((200, 220), (200, 180), (100, 200), (300, 200))
            assert result == "exit"

    def test_vertical_line_opposite_directions(self):
        # Vertical line — two directions should return different values
        dir1 = crossing_direction((180, 200), (220, 200), (200, 100), (200, 300))
        dir2 = crossing_direction((220, 200), (180, 200), (200, 100), (200, 300))
        assert dir1 != dir2
        assert dir1 in ("enter", "exit")
        assert dir2 in ("enter", "exit")


class TestDistancePointToLine:
    """Tests for distance_point_to_line()."""

    def test_perpendicular_to_midpoint(self):
        # Horizontal line (0,0) → (100,0), point at (50,30)
        # Perpendicular distance should be exactly 30
        dist = distance_point_to_line((50, 30), (0, 0), (100, 0))
        assert dist == pytest.approx(30.0)

    def test_closest_to_endpoint(self):
        # Point at (-10, 0) is outside the segment; closest to (0,0)
        dist = distance_point_to_line((-10, 0), (0, 0), (100, 0))
        assert dist == pytest.approx(10.0)

    def test_closest_to_other_endpoint(self):
        # Point at (110, 0) is outside the segment; closest to (100,0)
        dist = distance_point_to_line((110, 0), (0, 0), (100, 0))
        assert dist == pytest.approx(10.0)

    def test_point_on_line(self):
        # Point exactly on the line → distance ≈ 0
        dist = distance_point_to_line((50, 0), (0, 0), (100, 0))
        assert dist == pytest.approx(0.0, abs=1e-10)

    def test_diagonal_line(self):
        # Line from (0,0) → (10,10), point at (0,10)
        # Perpendicular distance to the line y=x is |0-10|/sqrt(2) = 10/sqrt(2)
        dist = distance_point_to_line((0, 10), (0, 0), (10, 10))
        assert dist == pytest.approx(10 / math.sqrt(2), abs=1e-6)


class TestClosestZone:
    """Tests for closest_zone()."""

    def test_three_zones_closest_first(self):
        zones = [
            [[100, 100], [200, 100]],  # zone 0 — top
            [[100, 500], [200, 500]],  # zone 1 — bottom
            [[500, 100], [500, 200]],  # zone 2 — right
        ]
        # Point near zone 0
        assert closest_zone((150, 110), zones) == 0

    def test_three_zones_closest_second(self):
        zones = [
            [[100, 100], [200, 100]],
            [[100, 500], [200, 500]],
            [[500, 100], [500, 200]],
        ]
        # Point near zone 1
        assert closest_zone((150, 490), zones) == 1

    def test_three_zones_closest_third(self):
        zones = [
            [[100, 100], [200, 100]],
            [[100, 500], [200, 500]],
            [[500, 100], [500, 200]],
        ]
        # Point near zone 2
        assert closest_zone((490, 150), zones) == 2

    def test_deterministic_equidistant(self):
        # Two zones, point equidistant — should return a consistent index
        zones = [
            [[0, 0], [100, 0]],
            [[0, 100], [100, 100]],
        ]
        result = closest_zone((50, 50), zones)
        assert result in (0, 1)
        # Should be deterministic on repeated calls
        assert closest_zone((50, 50), zones) == result


class TestComputeReferenceHeading:
    """Tests for compute_reference_heading()."""

    def test_heading_north(self):
        # Zone at bottom of frame (y=500), center above (y=250)
        # Heading from zone midpoint toward center → North (0°)
        heading = compute_reference_heading((200, 500), (400, 500), (300, 250))
        assert heading == pytest.approx(0.0, abs=1.0)

    def test_heading_east(self):
        # Zone at left of frame (x=50), center to the right (x=400)
        heading = compute_reference_heading((50, 200), (50, 400), (400, 300))
        assert heading == pytest.approx(90.0, abs=1.0)

    def test_heading_south(self):
        # Zone at top of frame (y=50), center below (y=400)
        heading = compute_reference_heading((200, 50), (400, 50), (300, 400))
        assert heading == pytest.approx(180.0, abs=1.0)

    def test_heading_west(self):
        # Zone at right of frame (x=700), center to the left (x=300)
        heading = compute_reference_heading((700, 200), (700, 400), (300, 300))
        assert heading == pytest.approx(270.0, abs=1.0)
