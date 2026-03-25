"""Trajectory-based turn classification.

Analyzes a vehicle's tracked center-point trajectory to classify the
movement as through, left turn, right turn, or U-turn.  Uses the
calibrated reference_heading as the known entry direction and computes
the exit heading from the trajectory's tail, so gradual sweeping turns
are captured correctly.
"""

import logging
import math

from backend.config import (
    TRAJECTORY_CURVATURE_THRESHOLD,
    TRAJECTORY_MIN_DISTANCE_PX,
    TRAJECTORY_MIN_POINTS,
    TRAJECTORY_THROUGH_MAX_ANGLE,
    TRAJECTORY_TURN_MIN_ANGLE,
    TRAJECTORY_UTURN_MIN_ANGLE,
)

logger = logging.getLogger(__name__)


def compute_heading(p1: tuple, p2: tuple) -> float:
    """Heading angle in degrees from p1 to p2.

    Convention: 0°=North (up), 90°=East (right), 180°=South (down),
    270°=West (left).  Image coordinates (y increases downward).
    """
    return math.degrees(math.atan2(p2[0] - p1[0], -(p2[1] - p1[1]))) % 360


def compute_net_heading_change(
    trajectory: list[tuple], reference_heading: float
) -> float:
    """Net heading change: exit heading vs calibrated entry heading.

    Uses the calibrated reference_heading as the known entry direction
    rather than estimating it from noisy early trajectory points.

    Returns degrees in [-180, +180].
    Positive = turned right (clockwise), Negative = turned left (CCW).
    """
    n = len(trajectory)
    # Exit window: ~20% of trajectory, up to 7 points.  Larger than the old
    # 5-point cap to capture more of the final direction on long trajectories,
    # but small enough that the chord closely approximates the tangent.
    window = max(1, min(n // 5, 7))
    exit_start_idx = max(0, n - 1 - window)
    exit_heading = compute_heading(trajectory[exit_start_idx], trajectory[-1])

    # Net change = how far exit deviated from the calibrated entry heading
    change = exit_heading - reference_heading
    change = (change + 180) % 360 - 180
    return change


def compute_cumulative_curvature(trajectory: list[tuple]) -> float:
    """Total absolute angular change along the path.

    Uses every 3rd point to reduce tracking jitter.
    """
    # Smooth: take every 3rd point
    smoothed = trajectory[::3]
    # Ensure last point is included
    if len(trajectory) > 1 and smoothed[-1] != trajectory[-1]:
        smoothed.append(trajectory[-1])

    if len(smoothed) < 3:
        return 0.0

    total = 0.0
    for i in range(1, len(smoothed) - 1):
        h1 = compute_heading(smoothed[i - 1], smoothed[i])
        h2 = compute_heading(smoothed[i], smoothed[i + 1])
        delta = (h2 - h1 + 180) % 360 - 180
        total += abs(delta)
    return total


def compute_path_distance(trajectory: list[tuple]) -> float:
    """Sum of Euclidean distances between consecutive points."""
    total = 0.0
    for i in range(1, len(trajectory)):
        dx = trajectory[i][0] - trajectory[i - 1][0]
        dy = trajectory[i][1] - trajectory[i - 1][1]
        total += math.hypot(dx, dy)
    return total


def compute_straight_line_distance(trajectory: list[tuple]) -> float:
    """Euclidean distance from first to last point."""
    if len(trajectory) < 2:
        return 0.0
    dx = trajectory[-1][0] - trajectory[0][0]
    dy = trajectory[-1][1] - trajectory[0][1]
    return math.hypot(dx, dy)


def compute_path_straightness(trajectory: list[tuple]) -> float:
    """Ratio of straight-line distance to path distance. 1.0 = perfectly straight."""
    path_dist = compute_path_distance(trajectory)
    if path_dist == 0:
        return 0.0
    return compute_straight_line_distance(trajectory) / path_dist


def _distance_to_nearest_boundary(angle: float) -> tuple[float, float]:
    """Compute distance from angle to nearest classification boundary.

    Returns (distance, half_zone_width) for confidence scoring.
    Boundaries: 0 (through center), ±25 (through/ambiguous), ±35 (turn start),
    ±135 (turn/uturn), ±180 (uturn center).
    """
    abs_angle = abs(angle)
    boundaries = [0, TRAJECTORY_THROUGH_MAX_ANGLE, TRAJECTORY_TURN_MIN_ANGLE,
                  TRAJECTORY_UTURN_MIN_ANGLE, 180]

    min_dist = float("inf")
    for b in boundaries:
        d = abs(abs_angle - b)
        if d < min_dist:
            min_dist = d

    # Half zone widths for each region
    if abs_angle <= TRAJECTORY_THROUGH_MAX_ANGLE:
        half_width = TRAJECTORY_THROUGH_MAX_ANGLE / 2.0
    elif abs_angle <= TRAJECTORY_TURN_MIN_ANGLE:
        half_width = (TRAJECTORY_TURN_MIN_ANGLE - TRAJECTORY_THROUGH_MAX_ANGLE) / 2.0
    elif abs_angle <= TRAJECTORY_UTURN_MIN_ANGLE:
        half_width = (TRAJECTORY_UTURN_MIN_ANGLE - TRAJECTORY_TURN_MIN_ANGLE) / 2.0
    else:
        half_width = (180 - TRAJECTORY_UTURN_MIN_ANGLE) / 2.0

    return min_dist, half_width


def _compute_confidence(net_heading_change: float) -> float:
    """Compute confidence score based on distance from nearest boundary."""
    dist, half_width = _distance_to_nearest_boundary(net_heading_change)
    if half_width == 0:
        return 0.5
    conf = dist / half_width
    return max(0.1, min(0.99, conf))


def classify_trajectory(
    trajectory: list[tuple], reference_heading: float
) -> dict:
    """Classify a trajectory as through, left, right, uturn, or insufficient_data.

    Returns a dict with movement, confidence, and diagnostic metrics.
    """
    num_points = len(trajectory)
    path_dist = compute_path_distance(trajectory)

    # 1. Insufficient data check
    if num_points < TRAJECTORY_MIN_POINTS or path_dist < TRAJECTORY_MIN_DISTANCE_PX:
        return {
            "movement": "insufficient_data",
            "confidence": 0.0,
            "net_heading_change": 0.0,
            "cumulative_curvature": 0.0,
            "path_straightness": 0.0,
            "path_distance": path_dist,
            "num_points": num_points,
        }

    # 2. Compute metrics
    net_change = compute_net_heading_change(trajectory, reference_heading)
    curvature = compute_cumulative_curvature(trajectory)
    straightness = compute_path_straightness(trajectory)
    abs_change = abs(net_change)

    # 3. Classification using reference-anchored heading change
    #    and cumulative curvature as tiebreaker for ambiguous cases.

    # U-turn: |net| >= 135°
    if abs_change >= TRAJECTORY_UTURN_MIN_ANGLE:
        movement = "uturn"
    # Clear through: |net| <= 25°
    elif abs_change <= TRAJECTORY_THROUGH_MAX_ANGLE:
        movement = "through"
    # Clear left: -35° > net > -135°
    elif net_change < -TRAJECTORY_TURN_MIN_ANGLE and net_change > -TRAJECTORY_UTURN_MIN_ANGLE:
        movement = "left"
    # Clear right: 35° < net < 135°
    elif net_change > TRAJECTORY_TURN_MIN_ANGLE and net_change < TRAJECTORY_UTURN_MIN_ANGLE:
        movement = "right"
    # Ambiguous zone (25-35°): use curvature to decide
    else:
        if curvature > TRAJECTORY_CURVATURE_THRESHOLD:
            movement = "left" if net_change < 0 else "right"
        else:
            movement = "through"

    confidence = _compute_confidence(net_change)

    logger.debug(
        "classify: movement=%s net_heading=%.1f straightness=%.2f "
        "curvature=%.1f dist=%.1f pts=%d ref_heading=%.1f",
        movement, net_change, straightness, curvature,
        path_dist, num_points, reference_heading,
    )

    return {
        "movement": movement,
        "confidence": confidence,
        "net_heading_change": net_change,
        "cumulative_curvature": curvature,
        "path_straightness": straightness,
        "path_distance": path_dist,
        "num_points": num_points,
    }


def classify_trajectory_batch(
    trajectories: list[dict],
) -> list[dict]:
    """Classify multiple trajectories.

    Each input dict has {'trajectory': [...], 'reference_heading': float}.
    """
    return [
        classify_trajectory(t["trajectory"], t["reference_heading"])
        for t in trajectories
    ]
