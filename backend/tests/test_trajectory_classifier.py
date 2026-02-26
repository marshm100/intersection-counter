"""Tests for trajectory-based turn classification.

These are the most important tests in the project — if the classifier is
wrong, every count is wrong.
"""

import math
import random

import pytest

from backend.services.trajectory_classifier import (
    classify_trajectory,
    classify_trajectory_batch,
    compute_cumulative_curvature,
    compute_heading,
    compute_net_heading_change,
    compute_path_distance,
    compute_path_straightness,
    compute_straight_line_distance,
)


# ---------------------------------------------------------------------------
# Synthetic trajectory generators
# ---------------------------------------------------------------------------

def make_straight_trajectory(
    start: tuple, heading_deg: float, num_points: int = 30, step: float = 20.0
) -> list[tuple]:
    """Generate a straight-line trajectory from start in the given heading."""
    rad = math.radians(heading_deg)
    dx = step * math.sin(rad)
    dy = -step * math.cos(rad)
    return [(start[0] + i * dx, start[1] + i * dy) for i in range(num_points)]


def make_turn_trajectory(
    start: tuple,
    entry_heading_deg: float,
    turn_angle_deg: float,
    num_points: int = 30,
    radius: float = 300.0,
) -> list[tuple]:
    """Generate a curved trajectory that turns by turn_angle_deg.

    Negative turn_angle = left turn, Positive = right turn.
    Uses parametric arc generation.
    """
    # Direction of entry in image coords
    entry_rad = math.radians(entry_heading_deg)
    entry_dx = math.sin(entry_rad)
    entry_dy = -math.cos(entry_rad)

    # Perpendicular direction to find center of turning circle
    # Right turn: center is to the right of the direction of travel
    # Left turn: center is to the left
    if turn_angle_deg >= 0:  # right turn
        perp_dx = entry_dy   # rotate 90° CW in image coords: (dx,dy) -> (dy, -dx)
        perp_dy = -entry_dx
    else:  # left turn
        perp_dx = -entry_dy  # rotate 90° CCW: (dx,dy) -> (-dy, dx)
        perp_dy = entry_dx

    # Arc center
    cx = start[0] + radius * perp_dx
    cy = start[1] + radius * perp_dy

    # Starting angle on the circle (from center back to start point)
    start_angle = math.atan2(start[1] - cy, start[0] - cx)

    # Sweep angle — for right turn (positive turn_angle) we sweep clockwise
    # In standard math coords CW is negative, but image coords flip y
    sweep = math.radians(turn_angle_deg)

    points = []
    for i in range(num_points):
        t = i / (num_points - 1)
        angle = start_angle + sweep * t
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        points.append((x, y))
    return points


def add_jitter(
    trajectory: list[tuple], max_pixels: float = 3.0, seed: int = 42
) -> list[tuple]:
    """Add random jitter to simulate tracking noise."""
    rng = random.Random(seed)
    return [
        (x + rng.uniform(-max_pixels, max_pixels),
         y + rng.uniform(-max_pixels, max_pixels))
        for x, y in trajectory
    ]


# ---------------------------------------------------------------------------
# TestComputeHeading
# ---------------------------------------------------------------------------

class TestComputeHeading:
    def test_north(self):
        h = compute_heading((500, 500), (500, 400))
        assert h == pytest.approx(0.0, abs=0.1)

    def test_east(self):
        h = compute_heading((500, 500), (600, 500))
        assert h == pytest.approx(90.0, abs=0.1)

    def test_south(self):
        h = compute_heading((500, 500), (500, 600))
        assert h == pytest.approx(180.0, abs=0.1)

    def test_west(self):
        h = compute_heading((500, 500), (400, 500))
        assert h == pytest.approx(270.0, abs=0.1)


# ---------------------------------------------------------------------------
# TestComputeNetHeadingChange
# ---------------------------------------------------------------------------

class TestComputeNetHeadingChange:
    def test_straight_trajectory(self):
        traj = make_straight_trajectory((500, 800), heading_deg=0, num_points=30)
        change = compute_net_heading_change(traj, reference_heading=0)
        assert abs(change) < 5.0  # approximately 0°

    def test_left_curve(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=-90)
        change = compute_net_heading_change(traj, reference_heading=0)
        assert change < -30  # clearly negative (left)

    def test_right_curve(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=90)
        change = compute_net_heading_change(traj, reference_heading=0)
        assert change > 30  # clearly positive (right)

    def test_uturn(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=170)
        change = compute_net_heading_change(traj, reference_heading=0)
        assert abs(change) > 120  # large magnitude


# ---------------------------------------------------------------------------
# TestPathMetrics
# ---------------------------------------------------------------------------

class TestPathMetrics:
    def test_path_distance_straight(self):
        traj = make_straight_trajectory((0, 0), heading_deg=90, num_points=11, step=10)
        # 10 segments × 10 px each = 100
        dist = compute_path_distance(traj)
        assert dist == pytest.approx(100.0, abs=0.5)

    def test_straight_line_distance_matches_path(self):
        traj = make_straight_trajectory((0, 0), heading_deg=45, num_points=20, step=15)
        path_d = compute_path_distance(traj)
        straight_d = compute_straight_line_distance(traj)
        assert straight_d == pytest.approx(path_d, rel=0.01)

    def test_straightness_straight_line(self):
        traj = make_straight_trajectory((100, 100), heading_deg=0, num_points=30)
        s = compute_path_straightness(traj)
        assert s == pytest.approx(1.0, abs=0.01)

    def test_straightness_curved_less_than_one(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=-90)
        s = compute_path_straightness(traj)
        assert s < 1.0

    def test_cumulative_curvature_straight_near_zero(self):
        traj = make_straight_trajectory((100, 100), heading_deg=0, num_points=30, step=20)
        c = compute_cumulative_curvature(traj)
        assert c < 10.0  # very small for straight

    def test_cumulative_curvature_turn_is_large(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=-90)
        c = compute_cumulative_curvature(traj)
        assert c > 30.0  # significantly more curvature


# ---------------------------------------------------------------------------
# TestClassifyTrajectory — THE CRITICAL TESTS
# ---------------------------------------------------------------------------

class TestClassifyTrajectory:
    """16 core direction × movement tests + noisy + edge cases."""

    # --- Northbound (entry heading 0°) ---

    def test_nb_through(self):
        traj = make_straight_trajectory((500, 800), heading_deg=0, num_points=30, step=20)
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "through"

    def test_nb_left(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=-90)
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "left"

    def test_nb_right(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=90)
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "right"

    def test_nb_uturn(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=170, num_points=40)
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "uturn"

    # --- Eastbound (entry heading 90°) ---

    def test_eb_through(self):
        traj = make_straight_trajectory((100, 500), heading_deg=90, num_points=30, step=20)
        r = classify_trajectory(traj, reference_heading=90)
        assert r["movement"] == "through"

    def test_eb_left(self):
        traj = make_turn_trajectory((100, 500), entry_heading_deg=90, turn_angle_deg=-90)
        r = classify_trajectory(traj, reference_heading=90)
        assert r["movement"] == "left"

    def test_eb_right(self):
        traj = make_turn_trajectory((100, 500), entry_heading_deg=90, turn_angle_deg=90)
        r = classify_trajectory(traj, reference_heading=90)
        assert r["movement"] == "right"

    def test_eb_uturn(self):
        traj = make_turn_trajectory((100, 500), entry_heading_deg=90, turn_angle_deg=170, num_points=40)
        r = classify_trajectory(traj, reference_heading=90)
        assert r["movement"] == "uturn"

    # --- Southbound (entry heading 180°) ---

    def test_sb_through(self):
        traj = make_straight_trajectory((500, 100), heading_deg=180, num_points=30, step=20)
        r = classify_trajectory(traj, reference_heading=180)
        assert r["movement"] == "through"

    def test_sb_left(self):
        traj = make_turn_trajectory((500, 100), entry_heading_deg=180, turn_angle_deg=-90)
        r = classify_trajectory(traj, reference_heading=180)
        assert r["movement"] == "left"

    def test_sb_right(self):
        traj = make_turn_trajectory((500, 100), entry_heading_deg=180, turn_angle_deg=90)
        r = classify_trajectory(traj, reference_heading=180)
        assert r["movement"] == "right"

    def test_sb_uturn(self):
        traj = make_turn_trajectory((500, 100), entry_heading_deg=180, turn_angle_deg=170, num_points=40)
        r = classify_trajectory(traj, reference_heading=180)
        assert r["movement"] == "uturn"

    # --- Westbound (entry heading 270°) ---

    def test_wb_through(self):
        traj = make_straight_trajectory((800, 500), heading_deg=270, num_points=30, step=20)
        r = classify_trajectory(traj, reference_heading=270)
        assert r["movement"] == "through"

    def test_wb_left(self):
        traj = make_turn_trajectory((800, 500), entry_heading_deg=270, turn_angle_deg=-90)
        r = classify_trajectory(traj, reference_heading=270)
        assert r["movement"] == "left"

    def test_wb_right(self):
        traj = make_turn_trajectory((800, 500), entry_heading_deg=270, turn_angle_deg=90)
        r = classify_trajectory(traj, reference_heading=270)
        assert r["movement"] == "right"

    def test_wb_uturn(self):
        traj = make_turn_trajectory((800, 500), entry_heading_deg=270, turn_angle_deg=170, num_points=40)
        r = classify_trajectory(traj, reference_heading=270)
        assert r["movement"] == "uturn"

    # --- Noisy trajectory tests ---

    def test_noisy_through(self):
        traj = make_straight_trajectory((500, 800), heading_deg=0, num_points=30, step=20)
        noisy = add_jitter(traj, max_pixels=3)
        r = classify_trajectory(noisy, reference_heading=0)
        assert r["movement"] == "through"

    def test_noisy_left(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=-90)
        noisy = add_jitter(traj, max_pixels=3)
        r = classify_trajectory(noisy, reference_heading=0)
        assert r["movement"] == "left"

    def test_noisy_right(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=90)
        noisy = add_jitter(traj, max_pixels=3)
        r = classify_trajectory(noisy, reference_heading=0)
        assert r["movement"] == "right"

    def test_noisy_uturn(self):
        traj = make_turn_trajectory((500, 800), entry_heading_deg=0, turn_angle_deg=170, num_points=40)
        noisy = add_jitter(traj, max_pixels=3)
        r = classify_trajectory(noisy, reference_heading=0)
        assert r["movement"] == "uturn"

    # --- Edge cases ---

    def test_too_few_points(self):
        traj = [(100, 100), (200, 200), (300, 300)]
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "insufficient_data"
        assert r["confidence"] == 0.0

    def test_too_short_distance(self):
        # 10+ points but all very close together (< 50px total)
        traj = [(100 + i * 0.5, 100) for i in range(15)]
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "insufficient_data"

    def test_single_point(self):
        r = classify_trajectory([(500, 500)], reference_heading=0)
        assert r["movement"] == "insufficient_data"

    def test_all_identical_points(self):
        traj = [(400, 400)] * 20
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "insufficient_data"

    # --- Confidence tests ---

    def test_clear_left_high_confidence(self):
        # ~90° left turn → well inside left zone → higher confidence
        traj = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=-90,
            num_points=40, radius=200,
        )
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "left"
        assert r["confidence"] > 0.7

    def test_ambiguous_low_confidence(self):
        # ~38° heading change → between through (30) and left (45) → low confidence
        traj = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=-38,
            num_points=30, radius=500,
        )
        r = classify_trajectory(traj, reference_heading=0)
        assert r["confidence"] < 0.7

    def test_clear_higher_than_ambiguous(self):
        # Confidence for a clear turn should be higher than an ambiguous one
        clear = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=-90,
        )
        ambig = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=-38,
            num_points=30, radius=500,
        )
        r_clear = classify_trajectory(clear, reference_heading=0)
        r_ambig = classify_trajectory(ambig, reference_heading=0)
        assert r_clear["confidence"] > r_ambig["confidence"]

    # --- Return dict structure ---

    def test_result_keys(self):
        traj = make_straight_trajectory((500, 800), heading_deg=0, num_points=30)
        r = classify_trajectory(traj, reference_heading=0)
        expected_keys = {
            "movement", "confidence", "net_heading_change",
            "cumulative_curvature", "path_straightness",
            "path_distance", "num_points",
        }
        assert set(r.keys()) == expected_keys


# ---------------------------------------------------------------------------
# TestClassifyTrajectoryBatch
# ---------------------------------------------------------------------------

class TestClassifyTrajectoryBatch:
    def test_batch_of_four(self):
        batch = [
            {
                "trajectory": make_straight_trajectory((500, 800), 0, 30, 20),
                "reference_heading": 0,
            },
            {
                "trajectory": make_turn_trajectory((500, 800), 0, -90),
                "reference_heading": 0,
            },
            {
                "trajectory": make_turn_trajectory((500, 800), 0, 90),
                "reference_heading": 0,
            },
            {
                "trajectory": make_turn_trajectory((500, 800), 0, 170, num_points=40),
                "reference_heading": 0,
            },
        ]
        results = classify_trajectory_batch(batch)
        assert len(results) == 4
        assert results[0]["movement"] == "through"
        assert results[1]["movement"] == "left"
        assert results[2]["movement"] == "right"
        assert results[3]["movement"] == "uturn"
