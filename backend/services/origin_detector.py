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
    origin_point: tuple, reference_heading: float, half_length: float = 40.0,
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
    # Perpendicular to the approach direction:
    perp_rad = math.radians(reference_heading + 90.0)
    dx = math.sin(perp_rad)
    dy = -math.cos(perp_rad)
    x, y = float(origin_point[0]), float(origin_point[1])
    return (
        (x - dx * half_length, y - dy * half_length),
        (x + dx * half_length, y + dy * half_length),
    )


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
