"""Origin zone line-crossing detection geometry functions.

An origin zone is a line segment (two endpoints). A vehicle "crosses" an
origin zone when its tracked center point moves from one side of the line
to the other between consecutive frames.
"""

import math


def point_side_of_line(
    point: tuple, line_start: tuple, line_end: tuple
) -> int:
    """Return +1 if point is left of line, -1 if right, 0 if on the line.

    Uses the cross product: (line_end - line_start) × (point - line_start).
    """
    cross = (
        (line_end[0] - line_start[0]) * (point[1] - line_start[1])
        - (line_end[1] - line_start[1]) * (point[0] - line_start[0])
    )
    if cross > 0:
        return 1
    elif cross < 0:
        return -1
    return 0


def did_cross_line(
    prev_point: tuple, curr_point: tuple,
    line_start: tuple, line_end: tuple,
) -> bool:
    """Return True if movement from prev_point to curr_point crosses the
    finite line segment from line_start to line_end.

    Uses parametric line-segment intersection (NOT infinite line).
    """
    d1x = line_end[0] - line_start[0]
    d1y = line_end[1] - line_start[1]
    d2x = curr_point[0] - prev_point[0]
    d2y = curr_point[1] - prev_point[1]

    denom = d1x * d2y - d1y * d2x
    if denom == 0:
        return False  # parallel

    dx = prev_point[0] - line_start[0]
    dy = prev_point[1] - line_start[1]

    t = (dx * d2y - dy * d2x) / denom
    u = (dx * d1y - dy * d1x) / denom

    return 0 <= t <= 1 and 0 <= u <= 1


def crossing_direction(
    prev_point: tuple,
    curr_point: tuple,
    line_start: tuple,
    line_end: tuple,
    reference_heading: float | None = None,
) -> str:
    """Return 'enter' or 'exit'.

    If reference_heading is provided (degrees, 0=North, image convention),
    compares vehicle movement vector against the expected approach direction.
    A vehicle within ±90° of reference_heading is 'entering'.

    Falls back to the original side-of-line check when reference_heading is None.
    """
    if reference_heading is not None:
        dx = curr_point[0] - prev_point[0]
        dy = curr_point[1] - prev_point[1]
        if dx == 0 and dy == 0:
            return "enter"  # stationary — default to enter
        movement_angle = math.degrees(math.atan2(dx, -dy)) % 360
        diff = abs((movement_angle - reference_heading + 180) % 360 - 180)
        return "enter" if diff <= 90 else "exit"
    # Legacy fallback
    side = point_side_of_line(prev_point, line_start, line_end)
    return "enter" if side <= 0 else "exit"


def distance_point_to_line(
    point: tuple, line_start: tuple, line_end: tuple
) -> float:
    """Perpendicular distance from a point to a finite line segment."""
    dx = line_end[0] - line_start[0]
    dy = line_end[1] - line_start[1]
    length_sq = dx * dx + dy * dy

    if length_sq == 0:
        # Degenerate segment (single point)
        return math.hypot(point[0] - line_start[0], point[1] - line_start[1])

    # Parameter t of the projection onto the line
    t = ((point[0] - line_start[0]) * dx + (point[1] - line_start[1]) * dy) / length_sq

    if t < 0:
        # Closest to line_start
        return math.hypot(point[0] - line_start[0], point[1] - line_start[1])
    elif t > 1:
        # Closest to line_end
        return math.hypot(point[0] - line_end[0], point[1] - line_end[1])
    else:
        # Perpendicular projection falls within segment
        proj_x = line_start[0] + t * dx
        proj_y = line_start[1] + t * dy
        return math.hypot(point[0] - proj_x, point[1] - proj_y)


def closest_zone(
    point: tuple, zones: list[list[list[float]]]
) -> int:
    """Return the index of the closest zone to the point.

    Each zone is [[x1, y1], [x2, y2]].
    """
    best_idx = 0
    best_dist = float("inf")
    for i, zone in enumerate(zones):
        d = distance_point_to_line(point, tuple(zone[0]), tuple(zone[1]))
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


def tripwire_from_point(
    origin_point: tuple, reference_heading: float, half_length: float | None = None,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """From a single calibrated origin node + the approach heading, build a
    tripwire line segment perpendicular to the approach. Returns (start, end).

    Used because v3 calibration captures one origin point per leg (a click on
    the approach arm), but the pipeline's origin assignment is line-crossing
    based. The synthesized line is perpendicular to the vehicle's approach
    direction so vehicles entering along reference_heading will cross it.

    Heading convention: 0°=North(up), 90°=East(right), 180°=South(down).
    Image coordinates (y increases downward).
    """
    # Default half-length comes from config so it's tunable per intersection
    # type without code changes. Imported lazily so tests that don't need
    # the full config don't pay the import cost.
    if half_length is None:
        from backend.config import TRIPWIRE_HALF_LENGTH_PX
        half_length = TRIPWIRE_HALF_LENGTH_PX
    # Perpendicular to the approach direction:
    perp_rad = math.radians(reference_heading + 90.0)
    dx = math.sin(perp_rad)
    dy = -math.cos(perp_rad)
    x, y = float(origin_point[0]), float(origin_point[1])
    return (
        (x - dx * half_length, y - dy * half_length),
        (x + dx * half_length, y + dy * half_length),
    )


# ---------------------------------------------------------------------------
# Polyline-based origin attribution (Phase 1).
#
# When a camera has rows in intersection_paths, the pipeline scores each
# new trajectory's first K points against the ENTRY SEGMENT of every path
# from that camera. The leg whose path has the smallest mean-perpendicular
# distance wins, provided the distance is below max_avg_distance_px.
#
# Why entry segment and not full polyline: at origin-attribution time the
# trajectory has only ~8 frames and the vehicle hasn't reached the
# intersection yet. Matching against the full polyline (which extends
# through and past the intersection) would be biased toward whichever
# polyline happens to start where our prefix is.
# ---------------------------------------------------------------------------


def _point_to_segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float,
) -> float:
    """Shortest distance from point (px, py) to the finite segment
    [(ax, ay), (bx, by)]. Standard projection formula with parameter clamp."""
    dx = bx - ax
    dy = by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    if t < 0.0:
        return math.hypot(px - ax, py - ay)
    if t > 1.0:
        return math.hypot(px - bx, py - by)
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def point_to_polyline_distance(
    point: tuple, polyline: list,
) -> float:
    """Shortest distance from point to ANY segment of the polyline."""
    if not polyline or len(polyline) < 2:
        if polyline:
            return math.hypot(point[0] - polyline[0][0], point[1] - polyline[0][1])
        return float("inf")
    best = float("inf")
    for i in range(len(polyline) - 1):
        a = polyline[i]
        b = polyline[i + 1]
        d = _point_to_segment_distance(
            float(point[0]), float(point[1]),
            float(a[0]), float(a[1]),
            float(b[0]), float(b[1]),
        )
        if d < best:
            best = d
    return best


def average_perpendicular_distance(
    points: list, polyline: list,
) -> float:
    """Mean of point-to-polyline distances across all `points`.

    Symmetric variant (Hausdorff) would also reverse — measure how well
    polyline points are covered by the trajectory — but for origin
    attribution we only care that the trajectory lies ON the polyline,
    not that the polyline lies on the trajectory (the polyline can
    extend past the trajectory). One-sided mean is the right metric.
    """
    if not points:
        return float("inf")
    total = 0.0
    n = 0
    for p in points:
        total += point_to_polyline_distance(p, polyline)
        n += 1
    return total / n if n > 0 else float("inf")


def _entry_segment(polyline: list) -> list:
    """First half of the polyline — the off-frame-entry-to-intersection-center
    portion. For an N-point polyline, returns the first ceil(N/2) + 1 points
    (inclusive of the midpoint) so the entry segment ends at the geometric
    middle of the polyline."""
    if not polyline:
        return []
    n = len(polyline)
    if n <= 2:
        return list(polyline)
    mid = (n + 1) // 2 + 1   # ceil(n/2) + 1 for an inclusive midpoint
    return list(polyline[:mid])


def score_origin_by_polyline(
    trajectory_prefix: list,
    paths: list,
    *,
    max_avg_distance_px: float = 30.0,
) -> dict:
    """Pick the leg whose path's entry segment best matches the prefix.

    Args:
      trajectory_prefix: list of (x, y) points — usually the first 6-10
        trajectory points (vehicle hasn't reached the intersection yet).
      paths: list of dicts from list_paths_for_camera. Each must have
        'polyline' (list of [x, y]) and 'origin_leg_id'.
      max_avg_distance_px: reject the best match if its mean perpendicular
        distance exceeds this — better to fall through to a downstream
        tier than to assign with low confidence.

    Returns:
      {'origin_leg_id': int|None, 'distance': float, 'path_id': int|None,
       'considered': int}
    """
    if not trajectory_prefix or not paths:
        return {"origin_leg_id": None, "distance": float("inf"),
                "path_id": None, "considered": 0}

    best_dist = float("inf")
    best_leg = None
    best_path_id = None
    best_support = -1
    for p in paths:
        entry = _entry_segment(p.get("polyline") or [])
        if len(entry) < 2:
            continue
        d = average_perpendicular_distance(trajectory_prefix, entry)
        # Tie-break by supporting_count desc — a path backed by more
        # observed trajectories is more trustworthy at the same distance.
        if (d < best_dist or
                (d == best_dist and p.get("supporting_count", 0) > best_support)):
            best_dist = d
            best_leg = p.get("origin_leg_id")
            best_path_id = p.get("path_id")
            best_support = p.get("supporting_count", 0)

    if best_leg is None or best_dist > max_avg_distance_px:
        return {"origin_leg_id": None, "distance": best_dist,
                "path_id": best_path_id, "considered": len(paths)}
    return {"origin_leg_id": best_leg, "distance": best_dist,
            "path_id": best_path_id, "considered": len(paths)}


def compute_reference_heading(
    line_start: tuple, line_end: tuple, intersection_center: tuple
) -> float:
    """Compute the reference heading for an origin zone.

    The reference heading points from the zone line's midpoint toward
    the intersection center.

    Returns degrees: 0°=North(up), 90°=East(right), 180°=South(down),
    270°=West(left).  Image coordinate convention (y increases downward).
    """
    mid_x = (line_start[0] + line_end[0]) / 2
    mid_y = (line_start[1] + line_end[1]) / 2
    heading = math.degrees(
        math.atan2(
            intersection_center[0] - mid_x,
            -(intersection_center[1] - mid_y),
        )
    ) % 360
    return heading
