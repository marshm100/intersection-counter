"""Tests for the auto-calibration service.

Mostly exercises the pure pieces (filter, cluster, geometry, cardinals) with
synthetic trajectories so we don't need to spin up real YOLO/cv2.
"""

import math

import pytest

from backend.services.auto_calibrator import (
    CalibrationResult, MIN_TRAJECTORIES_PER_LEG, ProposedLeg,
    assemble_legs, cluster_entry_points, compute_leg_geometry,
    compute_origin_line, compute_reference_heading, filter_trajectories,
    screen_bearing_to_cardinal,
)


IMAGE_SIZE = (1920, 1080)
CENTER = [IMAGE_SIZE[0] / 2, IMAGE_SIZE[1] / 2]


# ---------------------------------------------------------------------------
# Synthetic trajectory generators
# ---------------------------------------------------------------------------

def _line_trajectory(
    start: tuple, end: tuple, n_points: int = 20, start_frame: int = 0,
) -> list[tuple[float, float, int]]:
    """Generate a straight-line trajectory of n_points evenly between start/end."""
    points = []
    for i in range(n_points):
        t = i / (n_points - 1)
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t
        points.append((float(x), float(y), start_frame + i))
    return points


def _four_way_intersection(
    image_size: tuple[int, int] = IMAGE_SIZE,
    per_leg: int = MIN_TRAJECTORIES_PER_LEG + 5,
) -> dict[int, list[tuple[float, float, int]]]:
    """Generate trajectories for a 4-way intersection.

    N leg: enters top, moves toward center.
    E leg: enters right, moves toward center.
    S leg: enters bottom, moves toward center.
    W leg: enters left, moves toward center.
    """
    w, h = image_size
    cx, cy = w / 2, h / 2
    trajectories: dict[int, list[tuple[float, float, int]]] = {}
    tid = 1

    # N leg: entries clustered at top edge, moving downward
    for i in range(per_leg):
        offset = (i - per_leg // 2) * 8  # spread across a small lateral range
        start = (cx - 40 + offset, 20)
        end = (cx - 20 + offset, cy)
        trajectories[tid] = _line_trajectory(start, end)
        tid += 1

    # E leg: entries clustered at right edge
    for i in range(per_leg):
        offset = (i - per_leg // 2) * 8
        start = (w - 20, cy - 40 + offset)
        end = (cx, cy - 20 + offset)
        trajectories[tid] = _line_trajectory(start, end)
        tid += 1

    # S leg: entries clustered at bottom edge
    for i in range(per_leg):
        offset = (i - per_leg // 2) * 8
        start = (cx + 40 + offset, h - 20)
        end = (cx + 20 + offset, cy)
        trajectories[tid] = _line_trajectory(start, end)
        tid += 1

    # W leg: entries clustered at left edge
    for i in range(per_leg):
        offset = (i - per_leg // 2) * 8
        start = (20, cy + 40 + offset)
        end = (cx, cy + 20 + offset)
        trajectories[tid] = _line_trajectory(start, end)
        tid += 1

    return trajectories


# ---------------------------------------------------------------------------
# filter_trajectories
# ---------------------------------------------------------------------------

class TestFilterTrajectories:
    def test_keeps_long_moving_tracks(self):
        traj = {1: _line_trajectory((100, 100), (500, 100), n_points=20)}
        out = filter_trajectories(traj)
        assert 1 in out

    def test_drops_short_tracks(self):
        traj = {1: _line_trajectory((100, 100), (500, 100), n_points=3)}
        out = filter_trajectories(traj)
        assert 1 not in out

    def test_drops_stationary_tracks(self):
        # Long trajectory but moves <100 px total
        traj = {1: _line_trajectory((100, 100), (110, 110), n_points=20)}
        out = filter_trajectories(traj)
        assert 1 not in out


# ---------------------------------------------------------------------------
# cluster_entry_points
# ---------------------------------------------------------------------------

class TestClusterEntryPoints:
    def test_four_clusters_for_four_leg_intersection(self):
        traj = _four_way_intersection()
        clusters = cluster_entry_points(traj, IMAGE_SIZE)
        assert len(clusters) == 4

    def test_empty_input_returns_empty(self):
        assert cluster_entry_points({}, IMAGE_SIZE) == {}

    def test_num_legs_hint_truncates_extras(self):
        # Build extra noise clusters in the middle
        traj = _four_way_intersection()
        # Add a small cluster in the middle that would otherwise be a 5th
        for i in range(8):
            traj[1000 + i] = _line_trajectory(
                (IMAGE_SIZE[0] / 2 + i, IMAGE_SIZE[1] / 2 + i),
                (IMAGE_SIZE[0] / 2 + 200 + i, IMAGE_SIZE[1] / 2 + 200 + i),
            )
        # Without hint, DBSCAN may produce 5+ clusters
        all_clusters = cluster_entry_points(traj, IMAGE_SIZE)
        # With hint=4, we get at most 4
        capped = cluster_entry_points(traj, IMAGE_SIZE, num_legs_hint=4)
        assert len(capped) <= 4


# ---------------------------------------------------------------------------
# compute_leg_geometry
# ---------------------------------------------------------------------------

class TestComputeLegGeometry:
    def test_centroid_at_cluster_center(self):
        traj = {
            1: _line_trajectory((100, 200), (300, 200)),
            2: _line_trajectory((110, 210), (310, 210)),
            3: _line_trajectory((120, 190), (320, 190)),
        }
        cluster = [1, 2, 3]
        info = compute_leg_geometry(cluster, traj, IMAGE_SIZE)
        assert info["centroid"][0] == pytest.approx(110, abs=5)
        assert info["centroid"][1] == pytest.approx(200, abs=5)

    def test_flow_unit_points_inward(self):
        # Trajectories enter on the left moving right
        traj = {
            i: _line_trajectory((100, 200 + i * 10), (500, 200 + i * 10))
            for i in range(1, 6)
        }
        cluster = list(traj.keys())
        info = compute_leg_geometry(cluster, traj, IMAGE_SIZE)
        assert info["flow_unit"][0] > 0.9  # mostly +x
        assert abs(info["flow_unit"][1]) < 0.1


# ---------------------------------------------------------------------------
# compute_origin_line
# ---------------------------------------------------------------------------

class TestComputeOriginLine:
    def test_perpendicular_to_flow(self):
        # Flow = +x → perpendicular = +y (or -y), origin line is vertical
        line = compute_origin_line([500, 500], [1, 0], IMAGE_SIZE, length_fraction=0.1)
        # Both endpoints should have x ≈ 500
        assert line[0][0] == pytest.approx(500, abs=1)
        assert line[1][0] == pytest.approx(500, abs=1)
        # And different y values
        assert abs(line[0][1] - line[1][1]) > 50

    def test_clamps_to_image(self):
        line = compute_origin_line([0, 0], [1, 0], IMAGE_SIZE)
        for pt in line:
            assert 0 <= pt[0] <= IMAGE_SIZE[0]
            assert 0 <= pt[1] <= IMAGE_SIZE[1]


# ---------------------------------------------------------------------------
# compute_reference_heading
# ---------------------------------------------------------------------------

class TestComputeReferenceHeading:
    def test_points_toward_intersection_center(self):
        # Origin line at top of frame, center below
        line = [[400, 100], [600, 100]]
        center = [500, 500]
        heading = compute_reference_heading(line, center)
        # midpoint (500, 100) → (500, 500): direction is "down" in image (y+)
        # In our convention 0=up, 90=right, 180=down. So heading should be 180.
        assert heading == pytest.approx(180, abs=1)

    def test_horizontal_pointing(self):
        line = [[100, 400], [100, 600]]
        center = [500, 500]
        # midpoint (100, 500) → (500, 500): direction is "right". Heading = 90.
        assert compute_reference_heading(line, center) == pytest.approx(90, abs=1)


# ---------------------------------------------------------------------------
# screen_bearing_to_cardinal
# ---------------------------------------------------------------------------

class TestCardinalLabeling:
    def test_north_up(self):
        # screen_bearing 0 = top of screen. If north is "up", that's N.
        assert screen_bearing_to_cardinal(0, "up") == "N"
        assert screen_bearing_to_cardinal(90, "up") == "E"
        assert screen_bearing_to_cardinal(180, "up") == "S"
        assert screen_bearing_to_cardinal(270, "up") == "W"

    def test_north_right(self):
        # If real north is to the right of screen, screen_bearing 90 = N.
        assert screen_bearing_to_cardinal(90, "right") == "N"
        assert screen_bearing_to_cardinal(180, "right") == "E"
        assert screen_bearing_to_cardinal(270, "right") == "S"
        assert screen_bearing_to_cardinal(0, "right") == "W"

    def test_north_left(self):
        assert screen_bearing_to_cardinal(270, "left") == "N"

    def test_north_down(self):
        assert screen_bearing_to_cardinal(180, "down") == "N"

    def test_intercardinal(self):
        assert screen_bearing_to_cardinal(45, "up") == "NE"
        assert screen_bearing_to_cardinal(225, "up") == "SW"


# ---------------------------------------------------------------------------
# assemble_legs (end-to-end with synthetic data)
# ---------------------------------------------------------------------------

class TestAssembleLegs:
    def test_four_way_intersection_yields_NSEW(self):
        traj = _four_way_intersection()
        clusters = cluster_entry_points(traj, IMAGE_SIZE)
        infos = [compute_leg_geometry(c, traj, IMAGE_SIZE) for c in clusters.values()]
        # Compute weighted intersection center
        total = sum(i["trajectory_count"] for i in infos)
        cx = sum(i["centroid"][0] * i["trajectory_count"] for i in infos) / total
        cy = sum(i["centroid"][1] * i["trajectory_count"] for i in infos) / total

        legs = assemble_legs(infos, [cx, cy], IMAGE_SIZE, "up")
        cardinals = {leg.cardinal_direction for leg in legs}
        assert cardinals == {"N", "E", "S", "W"}
        # Sort order is clockwise from N
        assert [leg.cardinal_direction for leg in legs] == ["N", "E", "S", "W"]

    def test_origin_lines_are_inside_image(self):
        traj = _four_way_intersection()
        clusters = cluster_entry_points(traj, IMAGE_SIZE)
        infos = [compute_leg_geometry(c, traj, IMAGE_SIZE) for c in clusters.values()]
        total = sum(i["trajectory_count"] for i in infos)
        cx = sum(i["centroid"][0] * i["trajectory_count"] for i in infos) / total
        cy = sum(i["centroid"][1] * i["trajectory_count"] for i in infos) / total
        legs = assemble_legs(infos, [cx, cy], IMAGE_SIZE, "up")
        for leg in legs:
            for pt in leg.origin_zone:
                assert 0 <= pt[0] <= IMAGE_SIZE[0]
                assert 0 <= pt[1] <= IMAGE_SIZE[1]

    def test_reference_heading_points_toward_center(self):
        traj = _four_way_intersection()
        clusters = cluster_entry_points(traj, IMAGE_SIZE)
        infos = [compute_leg_geometry(c, traj, IMAGE_SIZE) for c in clusters.values()]
        total = sum(i["trajectory_count"] for i in infos)
        cx = sum(i["centroid"][0] * i["trajectory_count"] for i in infos) / total
        cy = sum(i["centroid"][1] * i["trajectory_count"] for i in infos) / total
        legs = assemble_legs(infos, [cx, cy], IMAGE_SIZE, "up")
        # Each leg's reference_heading should point roughly opposite its cardinal
        # (N leg is at top, points down → 180°; E is at right, points left → 270°; etc.)
        expected_heading = {"N": 180, "E": 270, "S": 0, "W": 90}
        for leg in legs:
            exp = expected_heading[leg.cardinal_direction]
            actual = leg.reference_heading
            diff = min(abs(actual - exp), 360 - abs(actual - exp))
            assert diff < 20, f"{leg.cardinal_direction}: heading {actual} not near {exp}"


# ---------------------------------------------------------------------------
# CalibrationResult.to_dict
# ---------------------------------------------------------------------------

class TestCalibrationResult:
    def test_success_to_dict(self):
        legs = [ProposedLeg(
            label="N Approach", cardinal_direction="N", sort_order=0,
            origin_zone=[[100, 100], [300, 100]], reference_heading=180.0,
            trajectory_count=50,
        )]
        r = CalibrationResult(
            success=True, legs=legs,
            intersection_center=[400, 400],
            frame_jpeg=b"\xff\xd8jpeg",
            frame_number=10,
        )
        d = r.to_dict()
        assert d["success"] is True
        assert len(d["legs"]) == 1
        assert d["legs"][0]["cardinal_direction"] == "N"
        assert d["frame_jpeg_size_bytes"] == len(b"\xff\xd8jpeg")

    def test_failure_to_dict(self):
        r = CalibrationResult(success=False, reason="not enough data")
        d = r.to_dict()
        assert d["success"] is False
        assert d["reason"] == "not enough data"
