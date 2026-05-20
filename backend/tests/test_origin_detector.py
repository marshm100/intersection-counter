"""Tests for origin zone line-crossing detection geometry."""

import math
import pytest

from backend.services.origin_detector import (
    assign_origin_by_backward_extrapolation,
    backward_extrapolated_entry,
    closest_zone,
    compute_reference_heading,
    crossing_direction,
    did_cross_line,
    distance_point_to_line,
    early_motion_vector,
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

    # --- Heading-based tests (reference_heading provided) ---

    def test_heading_north_vehicle_approaching(self):
        # NB leg: reference_heading=0° (North). Vehicle moving upward (toward top of frame)
        # dy < 0 in image coords → angle ≈ 0° → within ±90° of 0° → 'enter'
        result = crossing_direction(
            (500, 820), (500, 780),
            (700, 800), (300, 800),
            reference_heading=0.0,
        )
        assert result == "enter"

    def test_heading_north_vehicle_receding(self):
        # Same leg but vehicle moving south (away from intersection) → 'exit'
        result = crossing_direction(
            (500, 780), (500, 820),
            (700, 800), (300, 800),
            reference_heading=0.0,
        )
        assert result == "exit"

    def test_heading_east_vehicle_approaching(self):
        # EB leg: reference_heading=90° (East). Vehicle moving right (dx > 0) → 'enter'
        result = crossing_direction(
            (180, 500), (220, 500),
            (200, 700), (200, 300),
            reference_heading=90.0,
        )
        assert result == "enter"

    def test_heading_east_vehicle_receding(self):
        # Same leg but vehicle moving west (away from intersection) → 'exit'
        result = crossing_direction(
            (220, 500), (180, 500),
            (200, 700), (200, 300),
            reference_heading=90.0,
        )
        assert result == "exit"

    def test_stationary_vehicle_defaults_to_enter(self):
        # No movement → 'enter' by default
        result = crossing_direction(
            (500, 800), (500, 800),
            (700, 800), (300, 800),
            reference_heading=0.0,
        )
        assert result == "enter"

    def test_orientation_independent_same_result_both_line_directions(self):
        # The same vehicle crossing the same leg line should give 'enter' regardless
        # of which direction the line was drawn during calibration.
        # NB leg: reference_heading=0°, vehicle moving north.
        result_fwd = crossing_direction(
            (500, 820), (500, 780),
            (700, 800), (300, 800),  # line drawn right-to-left
            reference_heading=0.0,
        )
        result_rev = crossing_direction(
            (500, 820), (500, 780),
            (300, 800), (700, 800),  # line drawn left-to-right
            reference_heading=0.0,
        )
        assert result_fwd == "enter"
        assert result_rev == "enter"


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


# Sunnyvale TX intersection (project 97a7849a, camera 1) — realistic
# 4-leg geometry that drives the backward-extrapolation logic. L19 and
# L20 sit near frame edges; L18 and L21 are interior. Frame is 640x480.
SUNNYVALE_LEGS = [
    {"leg_id": 18, "reference_heading": 259.3, "origin_zone": [[474.0, 211.0]]},
    {"leg_id": 19, "reference_heading":  61.0, "origin_zone": [[ 85.0, 370.0]]},
    {"leg_id": 20, "reference_heading": 290.8, "origin_zone": [[547.0, 326.0]]},
    {"leg_id": 21, "reference_heading": 123.1, "origin_zone": [[217.0, 234.0]]},
]
SUNNYVALE_FRAME = (640, 480)
BWD_RADIUS = 180.0
BWD_MIN_DISP = 15.0
BWD_WINDOW = 8


class TestEarlyMotionVector:
    def test_returns_none_for_single_point(self):
        assert early_motion_vector([(100, 100)], BWD_MIN_DISP, BWD_WINDOW) is None

    def test_returns_none_for_stationary_window(self):
        # Tracker jitter under the displacement floor.
        traj = [(100.0, 100.0)] + [(100.1, 100.2)] * 6
        assert early_motion_vector(traj, BWD_MIN_DISP, BWD_WINDOW) is None

    def test_unit_vector_for_clear_eastward_motion(self):
        traj = [(100.0, 100.0), (120.0, 100.0)]
        v = early_motion_vector(traj, BWD_MIN_DISP, BWD_WINDOW)
        assert v == pytest.approx((1.0, 0.0))

    def test_uses_window_when_displacement_floor_not_reached(self):
        # Each step is small; cumulative reaches floor at frame 4.
        traj = [(100.0, 100.0), (104.0, 100.0), (108.0, 100.0),
                (112.0, 100.0), (116.0, 100.0)]
        v = early_motion_vector(traj, BWD_MIN_DISP, BWD_WINDOW)
        assert v == pytest.approx((1.0, 0.0))


class TestBackwardExtrapolatedEntry:
    def test_eastbound_vehicle_backward_to_left_edge(self):
        traj = [(200.0, 300.0), (240.0, 300.0)]
        entry = backward_extrapolated_entry(
            traj, *SUNNYVALE_FRAME, BWD_MIN_DISP, BWD_WINDOW
        )
        assert entry == pytest.approx((0.0, 300.0))

    def test_northeast_vehicle_backward_to_left_or_bottom(self):
        # L19-style approach: vehicle first seen well inside frame, moving NE
        traj = [(200.0, 320.0), (235.0, 300.0)]
        entry = backward_extrapolated_entry(
            traj, *SUNNYVALE_FRAME, BWD_MIN_DISP, BWD_WINDOW
        )
        assert entry is not None
        # Must hit either x=0 or y=480 — not both, depending on slope.
        x, y = entry
        assert (x == pytest.approx(0.0, abs=0.1)
                or y == pytest.approx(480.0, abs=0.1))


class TestAssignOriginByBackwardExtrapolation:
    """Realistic Sunnyvale scenarios; these are the actual L19/L20/L18
    failure cases from the 2026-05-20 truncation-test replay."""

    def test_late_detected_L19_assigns_L19(self):
        # NB Belt Line vehicle first detected past the L19 tripwire,
        # heading northeast toward the intersection center.
        traj = [(200.0, 320.0), (235.0, 305.0), (270.0, 290.0), (305.0, 275.0)]
        lid = assign_origin_by_backward_extrapolation(
            traj, SUNNYVALE_LEGS, *SUNNYVALE_FRAME,
            BWD_RADIUS, BWD_MIN_DISP, BWD_WINDOW,
        )
        assert lid == 19

    def test_late_detected_L20_assigns_L20(self):
        # Driveway vehicle first detected mid-frame after the L20 tripwire.
        # Mirrors ev1523 K=10 from the offline replay.
        traj = [(214.0, 260.0), (180.0, 264.0), (140.0, 268.0), (100.0, 270.0)]
        lid = assign_origin_by_backward_extrapolation(
            traj, SUNNYVALE_LEGS, *SUNNYVALE_FRAME,
            BWD_RADIUS, BWD_MIN_DISP, BWD_WINDOW,
        )
        assert lid == 20

    def test_central_L18_with_pure_west_motion_does_not_pick_far_leg(self):
        # A vehicle first detected at (475, 211) moving WSW (L18 approach)
        # backward-extrapolates to the right frame edge. L20 (547, 326) is
        # the nearest edge-leg but should be too far when the synthetic
        # entry lands at (640, ~119) — distance > radius. Either result
        # is acceptable EXCEPT mis-assigning to L20.
        traj = [(475.0, 211.0), (450.0, 225.0), (425.0, 239.0), (400.0, 253.0)]
        lid = assign_origin_by_backward_extrapolation(
            traj, SUNNYVALE_LEGS, *SUNNYVALE_FRAME,
            BWD_RADIUS, BWD_MIN_DISP, BWD_WINDOW,
        )
        assert lid != 20

    def test_stationary_vehicle_returns_none(self):
        traj = [(300.0, 300.0)] + [(300.1, 300.1)] * 8
        lid = assign_origin_by_backward_extrapolation(
            traj, SUNNYVALE_LEGS, *SUNNYVALE_FRAME,
            BWD_RADIUS, BWD_MIN_DISP, BWD_WINDOW,
        )
        assert lid is None

    def test_empty_legs_returns_none(self):
        traj = [(200.0, 320.0), (235.0, 305.0)]
        lid = assign_origin_by_backward_extrapolation(
            traj, [], *SUNNYVALE_FRAME,
            BWD_RADIUS, BWD_MIN_DISP, BWD_WINDOW,
        )
        assert lid is None

    def test_tight_radius_rejects_far_match(self):
        # Same L19-style trajectory, but radius too tight for the nearest
        # leg origin — should return None rather than picking a wrong leg.
        traj = [(200.0, 320.0), (235.0, 305.0)]
        lid = assign_origin_by_backward_extrapolation(
            traj, SUNNYVALE_LEGS, *SUNNYVALE_FRAME,
            match_radius_px=20.0,
            min_disp_px=BWD_MIN_DISP,
            window_frames=BWD_WINDOW,
        )
        assert lid is None
