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
    derive_movement,
    score_destination_leg,
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

    # Perpendicular direction to find center of turning circle.
    # In image coords (y-down), "visual right" from direction (dx, dy) is (-dy, dx)
    # and "visual left" is (dy, -dx).
    if turn_angle_deg >= 0:  # right turn: center to the right
        perp_dx = -entry_dy
        perp_dy = entry_dx
    else:  # left turn: center to the left
        perp_dx = entry_dy
        perp_dy = -entry_dx

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
        traj = [(100, 100)]
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "insufficient_data"
        assert r["confidence"] == 0.0

    def test_too_short_distance(self):
        # 10+ points but all very close together (< 15px total)
        traj = [(100 + i * 0.1, 100) for i in range(15)]
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


# ---------------------------------------------------------------------------
# TestGradualTurns — sweeping turns with large radius
# ---------------------------------------------------------------------------

class TestGradualTurns:
    """Gradual, sweeping turns that the old classifier missed."""

    def test_gradual_right_90_large_radius(self):
        """Wide, sweeping 90° right turn (radius=600) — must classify as right."""
        traj = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=90,
            num_points=40, radius=600,
        )
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "right"

    def test_gradual_left_90_large_radius(self):
        """Wide, sweeping 90° left turn (radius=600) — must classify as left."""
        traj = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=-90,
            num_points=40, radius=600,
        )
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "left"

    def test_gradual_right_60(self):
        """Moderate 60° right turn — must classify as right, not through."""
        traj = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=60,
            num_points=30, radius=500,
        )
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "right"

    def test_gradual_left_60(self):
        """Moderate 60° left turn — must classify as left, not through."""
        traj = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=-60,
            num_points=30, radius=500,
        )
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "left"

    def test_gradual_right_45(self):
        """45° right turn — borderline but should be right with curvature."""
        traj = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=45,
            num_points=30, radius=400,
        )
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "right"

    def test_gradual_left_45(self):
        """45° left turn — borderline but should be left with curvature."""
        traj = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=-45,
            num_points=30, radius=400,
        )
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "left"

    def test_all_four_directions_gradual_right(self):
        """Gradual 90° right from all four cardinal directions."""
        for heading in [0, 90, 180, 270]:
            traj = make_turn_trajectory(
                (500, 500), entry_heading_deg=heading, turn_angle_deg=90,
                num_points=40, radius=500,
            )
            r = classify_trajectory(traj, reference_heading=heading)
            assert r["movement"] == "right", (
                f"heading={heading}: expected right, got {r['movement']} "
                f"(net={r['net_heading_change']:.1f})"
            )

    def test_noisy_entry_still_classifies_correctly(self):
        """Noisy first few points shouldn't matter — entry heading from reference."""
        traj = make_turn_trajectory(
            (500, 800), entry_heading_deg=0, turn_angle_deg=-90,
            num_points=30, radius=300,
        )
        # Add heavy jitter to first 5 points only
        import random
        rng = random.Random(99)
        for i in range(5):
            x, y = traj[i]
            traj[i] = (x + rng.uniform(-20, 20), y + rng.uniform(-20, 20))
        r = classify_trajectory(traj, reference_heading=0)
        assert r["movement"] == "left"


# ---------------------------------------------------------------------------
# Phase B — destination-leg classification + movement derivation.
# A canonical 4-leg orthogonal intersection centered at (500, 500) with:
#   Leg S (id=1): origin at (500, 800), ref_heading 0   (points N into center)
#   Leg N (id=2): origin at (500, 200), ref_heading 180 (points S into center)
#   Leg W (id=3): origin at (200, 500), ref_heading 90  (points E into center)
#   Leg E (id=4): origin at (800, 500), ref_heading 270 (points W into center)
# Centroid = (500, 500). Tests exercise every movement type from leg S.
# ---------------------------------------------------------------------------

@pytest.fixture
def four_leg_intersection():
    return [
        {"leg_id": 1, "origin_zone": [[500, 800]], "reference_heading": 0.0,   "label": "South"},
        {"leg_id": 2, "origin_zone": [[500, 200]], "reference_heading": 180.0, "label": "North"},
        {"leg_id": 3, "origin_zone": [[200, 500]], "reference_heading": 90.0,  "label": "West"},
        {"leg_id": 4, "origin_zone": [[800, 500]], "reference_heading": 270.0, "label": "East"},
    ]


class TestDestinationScoring:
    def test_through_from_south_picks_north(self, four_leg_intersection):
        """Vehicle enters from south (origin leg 1), continues north. The
        destination should be the north leg (leg 2)."""
        # Trajectory: starts near south leg, moves north (decreasing y).
        traj = [(500, 800 - i * 30) for i in range(20)]  # 800 → 230
        result = score_destination_leg(traj, origin_leg_id=1, all_legs=four_leg_intersection)
        assert result["destination_leg_id"] == 2
        # Posterior should give the right leg most of the mass.
        assert result["confidence"] > 0.5

    def test_right_turn_from_south_picks_east(self, four_leg_intersection):
        """South origin, exit toward east (right turn from driver's POV)."""
        # Trajectory: starts near south leg, curves east. End up near east leg.
        traj = [(500, 800), (500, 700), (500, 600), (520, 550), (580, 510),
                (650, 500), (720, 500), (800, 500)]
        result = score_destination_leg(traj, origin_leg_id=1, all_legs=four_leg_intersection)
        assert result["destination_leg_id"] == 4  # East leg

    def test_left_turn_from_south_picks_west(self, four_leg_intersection):
        """South origin, exit toward west (left turn from driver's POV)."""
        traj = [(500, 800), (500, 700), (500, 600), (480, 550), (420, 510),
                (350, 500), (280, 500), (200, 500)]
        result = score_destination_leg(traj, origin_leg_id=1, all_legs=four_leg_intersection)
        assert result["destination_leg_id"] == 3  # West leg

    def test_uturn_from_south_picks_south(self, four_leg_intersection):
        """South origin, vehicle reverses back south. Destination = origin
        (u-turn detected)."""
        # Goes north then loops back south.
        traj = [(500, 800), (500, 700), (500, 600), (510, 550), (510, 600),
                (510, 700), (510, 800)]
        result = score_destination_leg(traj, origin_leg_id=1, all_legs=four_leg_intersection)
        assert result["destination_leg_id"] == 1

    def test_posterior_sums_to_one(self, four_leg_intersection):
        traj = [(500, 800 - i * 30) for i in range(20)]
        result = score_destination_leg(traj, origin_leg_id=1, all_legs=four_leg_intersection)
        assert abs(sum(result["posterior"].values()) - 1.0) < 1e-6

    def test_short_trajectory_returns_empty(self, four_leg_intersection):
        result = score_destination_leg([(500, 800)], 1, four_leg_intersection)
        assert result["destination_leg_id"] is None

    def test_no_legs_returns_empty(self):
        result = score_destination_leg([(0, 0), (1, 1)], 1, [])
        assert result["destination_leg_id"] is None


class TestDeriveMovement:
    def test_opposite_leg_is_through(self, four_leg_intersection):
        origin = four_leg_intersection[0]    # South, ref=0
        dest = four_leg_intersection[1]      # North, ref=180
        assert derive_movement(origin, dest) == "through"

    def test_90_cw_is_left(self, four_leg_intersection):
        """delta of +90° (destination ref is 90° clockwise of origin's)
        means the driver rotated 90° CCW = left turn from driver's POV."""
        origin = four_leg_intersection[0]    # South, ref=0
        dest = four_leg_intersection[2]      # West, ref=90
        assert derive_movement(origin, dest) == "left"

    def test_90_ccw_is_right(self, four_leg_intersection):
        origin = four_leg_intersection[0]    # South, ref=0
        dest = four_leg_intersection[3]      # East, ref=270
        assert derive_movement(origin, dest) == "right"

    def test_same_leg_is_u_turn(self, four_leg_intersection):
        origin = four_leg_intersection[0]
        assert derive_movement(origin, origin) == "u_turn"

    def test_destination_none_is_insufficient(self, four_leg_intersection):
        assert derive_movement(four_leg_intersection[0], None) == "insufficient_data"


class TestEndToEndDestinationClassification:
    """Glue test: score_destination + derive_movement together should
    produce the same movement labels a human watching the live preview
    would assign, on canonical 4-leg trajectories."""

    @pytest.mark.parametrize("origin_id,traj_endpoint,expected_movement", [
        (1, (500, 200), "through"),   # S → N
        (1, (800, 500), "right"),     # S → E
        (1, (200, 500), "left"),      # S → W
        (2, (500, 800), "through"),   # N → S
        (2, (200, 500), "right"),     # N → W (driver going south turns west = right)
        (2, (800, 500), "left"),      # N → E
        (3, (800, 500), "through"),   # W → E
        (4, (200, 500), "through"),   # E → W
    ])
    def test_movements_at_orthogonal_intersection(
        self, four_leg_intersection, origin_id, traj_endpoint, expected_movement,
    ):
        origin_leg = next(l for l in four_leg_intersection if l["leg_id"] == origin_id)
        origin_pt = origin_leg["origin_zone"][0]
        # Synthesize a straight trajectory from origin point to destination.
        ex, ey = traj_endpoint
        ox, oy = origin_pt
        steps = 20
        traj = [(ox + (ex - ox) * i / steps, oy + (ey - oy) * i / steps)
                for i in range(steps + 1)]
        result = score_destination_leg(traj, origin_id, four_leg_intersection)
        dest_leg = next(
            (l for l in four_leg_intersection if l["leg_id"] == result["destination_leg_id"]),
            None,
        )
        movement = derive_movement(origin_leg, dest_leg, all_legs=four_leg_intersection)
        assert movement == expected_movement, (
            f"origin={origin_id} endpoint={traj_endpoint} "
            f"got destination={result['destination_leg_id']} movement={movement} "
            f"posterior={result['posterior']}"
        )


@pytest.fixture
def skewed_intersection():
    """Real-world non-orthogonal intersection from Sunnyvale TX
    (NBeltLineRd/NorthwestDr) — legs are at 259°/61°/290°/123°, nowhere
    near 90° apart. The fixed-bucket derive_movement mis-classified ~22
    of 58 events from Leg 1 because delta(Leg 1, Leg 3) = 31° (≤ 45°)
    landed in the u_turn bucket even though Leg 3 is a real other leg."""
    return [
        {"leg_id": 1, "reference_heading": 259.3, "label": "Leg 1"},
        {"leg_id": 2, "reference_heading": 61.0,  "label": "Leg 2"},
        {"leg_id": 3, "reference_heading": 290.8, "label": "Leg 3"},
        {"leg_id": 4, "reference_heading": 123.1, "label": "Leg 4"},
    ]


class TestDeriveMovementSkewedGeometry:
    """Rank-based derivation must produce sensible labels at intersections
    where legs aren't 90° apart. Validates the fix for the Sunnyvale TX
    bug where the bucket rule called real turns 'u_turn'."""

    def test_origin1_leg3_is_left_not_uturn(self, skewed_intersection):
        # delta(L1, L3) = 31.5° → old bucket said u_turn.
        # Rank: L3 has the smallest delta → rank 0 → left.
        origin = skewed_intersection[0]  # Leg 1
        dest = skewed_intersection[2]    # Leg 3
        assert derive_movement(origin, dest, all_legs=skewed_intersection) == "left"

    def test_origin1_leg2_is_through(self, skewed_intersection):
        # delta(L1, L2) = 161.7° → closest to 180° → through (rank 1).
        origin = skewed_intersection[0]
        dest = skewed_intersection[1]
        assert derive_movement(origin, dest, all_legs=skewed_intersection) == "through"

    def test_origin1_leg4_is_right(self, skewed_intersection):
        # delta(L1, L4) = 223.8° → CCW-most → rank 2 → right.
        origin = skewed_intersection[0]
        dest = skewed_intersection[3]
        assert derive_movement(origin, dest, all_legs=skewed_intersection) == "right"

    def test_self_destination_is_uturn(self, skewed_intersection):
        origin = skewed_intersection[0]
        assert derive_movement(origin, origin, all_legs=skewed_intersection) == "u_turn"

    def test_origin2_left_through_right_assignment(self, skewed_intersection):
        # From Leg 2 (ref 61°):
        #   L4 (ref 123, delta 62)  → rank 0 → left
        #   L1 (ref 259, delta 198) → rank 1 → through
        #   L3 (ref 290, delta 229) → rank 2 → right
        origin = skewed_intersection[1]
        assert derive_movement(origin, skewed_intersection[3], all_legs=skewed_intersection) == "left"
        assert derive_movement(origin, skewed_intersection[0], all_legs=skewed_intersection) == "through"
        assert derive_movement(origin, skewed_intersection[2], all_legs=skewed_intersection) == "right"


class TestDeriveMovementTJunction:
    """T-junctions have 3 legs total. Origin can be the stem (in which
    case there's no through, only left+right) or a cross leg (one
    opposite + one perpendicular)."""

    @pytest.fixture
    def t_junction_orthogonal(self):
        # Cross legs at refs 90° and 270° (east/west); stem at 0° (south).
        return [
            {"leg_id": 1, "reference_heading": 0.0,   "label": "Stem"},
            {"leg_id": 2, "reference_heading": 90.0,  "label": "West"},
            {"leg_id": 3, "reference_heading": 270.0, "label": "East"},
        ]

    def test_stem_origin_no_through(self, t_junction_orthogonal):
        # From stem: West (delta 90) and East (delta 270). No through.
        origin = t_junction_orthogonal[0]
        assert derive_movement(origin, t_junction_orthogonal[1], all_legs=t_junction_orthogonal) == "left"
        assert derive_movement(origin, t_junction_orthogonal[2], all_legs=t_junction_orthogonal) == "right"

    def test_cross_origin_has_through(self, t_junction_orthogonal):
        # From West (ref 90): East (delta 180) is through; Stem (delta -90) is a turn.
        origin = t_junction_orthogonal[1]
        assert derive_movement(origin, t_junction_orthogonal[2], all_legs=t_junction_orthogonal) == "through"
        # Stem at delta = (0 - 90) mod 360 = 270 → right
        assert derive_movement(origin, t_junction_orthogonal[0], all_legs=t_junction_orthogonal) == "right"
