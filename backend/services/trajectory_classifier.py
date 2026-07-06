"""Trajectory-based turn classification.

Analyzes a vehicle's tracked center-point trajectory to classify the
movement as through, left turn, right turn, or U-turn.  Uses the
calibrated reference_heading as the known entry direction and computes
the exit heading from the trajectory's tail, so gradual sweeping turns
are captured correctly.
"""

import logging
import math
from statistics import median

from backend.config import (
    TRAJECTORY_CURVATURE_THRESHOLD,
    TRAJECTORY_MIN_DISTANCE_PX,
    TRAJECTORY_MIN_POINTS,
    TRAJECTORY_THROUGH_MAX_ANGLE,
    TRAJECTORY_TURN_MIN_ANGLE,
    TRAJECTORY_UTURN_MIN_ANGLE,
    TRAJECTORY_UTURN_MIN_NET_DISPLACEMENT_PX,
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


def _distance_to_nearest_boundary(
    angle: float, through_max: float, turn_min: float, uturn_min: float,
) -> tuple[float, float]:
    """Compute distance from angle to nearest classification boundary.

    Returns (distance, half_zone_width) for confidence scoring.
    Boundaries: 0 (through center), ±through_max (through/ambiguous),
    ±turn_min (turn start), ±uturn_min (turn/uturn), ±180 (uturn center).
    """
    abs_angle = abs(angle)
    boundaries = [0, through_max, turn_min, uturn_min, 180]
    min_dist = float("inf")
    for b in boundaries:
        d = abs(abs_angle - b)
        if d < min_dist:
            min_dist = d
    if abs_angle <= through_max:
        half_width = through_max / 2.0
    elif abs_angle <= turn_min:
        half_width = (turn_min - through_max) / 2.0
    elif abs_angle <= uturn_min:
        half_width = (uturn_min - turn_min) / 2.0
    else:
        half_width = (180 - uturn_min) / 2.0
    return min_dist, half_width


def _compute_confidence(
    net_heading_change: float, through_max: float, turn_min: float, uturn_min: float,
) -> float:
    """Compute confidence score based on distance from nearest boundary."""
    dist, half_width = _distance_to_nearest_boundary(
        net_heading_change, through_max, turn_min, uturn_min,
    )
    if half_width == 0:
        return 0.5
    conf = dist / half_width
    return max(0.1, min(0.99, conf))


def classify_trajectory(
    trajectory: list[tuple], reference_heading: float,
    *,
    through_max_angle: float | None = None,
    turn_min_angle: float | None = None,
    uturn_min_angle: float | None = None,
) -> dict:
    """Classify a trajectory as through, left, right, uturn, or insufficient_data.

    The three angle thresholds can be overridden per call (the pipeline passes
    per-intersection overrides from the calibration UI when present); each
    defaults to its module-level config constant when None.

    Returns a dict with movement, confidence, and diagnostic metrics.
    """
    eff_through = TRAJECTORY_THROUGH_MAX_ANGLE if through_max_angle is None else through_max_angle
    eff_turn    = TRAJECTORY_TURN_MIN_ANGLE    if turn_min_angle    is None else turn_min_angle
    eff_uturn   = TRAJECTORY_UTURN_MIN_ANGLE   if uturn_min_angle   is None else uturn_min_angle

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

    if abs_change >= eff_uturn:
        # Reject doubling-back tracking artifacts: a real U-turn ends a meaningful
        # net distance from its entry; an ID-switch/coasting loop ends near its
        # start despite a large arc. Gate on net (start->end) displacement.
        sx, sy = trajectory[0][0], trajectory[0][1]
        ex, ey = trajectory[-1][0], trajectory[-1][1]
        if math.hypot(ex - sx, ey - sy) < TRAJECTORY_UTURN_MIN_NET_DISPLACEMENT_PX:
            return {
                "movement": "insufficient_data",
                "confidence": 0.0,
                "net_heading_change": net_change,
                "cumulative_curvature": curvature,
                "path_straightness": straightness,
                "path_distance": path_dist,
                "num_points": num_points,
            }
        movement = "uturn"
    elif abs_change <= eff_through:
        movement = "through"
    elif net_change < -eff_turn and net_change > -eff_uturn:
        movement = "left"
    elif net_change > eff_turn and net_change < eff_uturn:
        movement = "right"
    # Ambiguous zone (between through_max and turn_min): use curvature
    else:
        if curvature > TRAJECTORY_CURVATURE_THRESHOLD:
            movement = "left" if net_change < 0 else "right"
        else:
            movement = "through"

    confidence = _compute_confidence(net_change, eff_through, eff_turn, eff_uturn)

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


# ---------------------------------------------------------------------------
# Polyline-based destination + movement (Phase 1, replaces the
# softmax-over-legs scorer below when intersection_paths has rows for
# the camera).
#
# For each known path (one polyline per (origin_leg, dest_leg) pair, with
# a stored movement_label), we score the FULL trajectory against the
# full polyline. Full-polyline matching here (vs just-exit-segment) is
# right because the trajectory has played out and we want to confirm it
# actually FOLLOWED the path's shape — not just ended near its endpoint.
# The path's movement_label comes for free; derive_movement is bypassed.
# ---------------------------------------------------------------------------


def _path_hausdorff_oneway(
    trajectory: list[tuple], polyline: list,
) -> float:
    """One-way Hausdorff: mean point-to-polyline distance across the
    trajectory. Reuses the polyline distance helper from origin_detector
    so the metric stays consistent across origin and destination scoring."""
    # Lazy import to avoid a top-level circular reference path.
    from backend.services.origin_detector import point_to_polyline_distance
    if not trajectory or not polyline or len(polyline) < 2:
        return float("inf")
    total = 0.0
    for p in trajectory:
        total += point_to_polyline_distance(p, polyline)
    return total / len(trajectory)


def score_destination_by_polyline(
    trajectory: list[tuple],
    origin_leg_id: int,
    paths: list[dict],
    *,
    max_avg_distance_px: float = 20.0,
) -> dict:
    """Pick the (destination_leg, movement) that best matches this trajectory.

    Args:
      trajectory: full trajectory as list of (x, y) points.
      origin_leg_id: the leg this vehicle was attributed to. Only paths
        with matching origin_leg_id are considered (the destination is a
        property of the (origin, destination) pair).
      paths: full list of paths for the camera (from list_paths_for_camera);
        we filter by origin_leg_id internally.
      max_avg_distance_px: reject if best match exceeds this distance.

    Returns:
      {'destination_leg_id': int|None, 'movement_label': str|None,
       'distance': float, 'path_id': int|None, 'considered': int}
    """
    candidates = [p for p in paths if p.get("origin_leg_id") == origin_leg_id]
    if not candidates or len(trajectory) < 2:
        return {"destination_leg_id": None, "movement_label": None,
                "distance": float("inf"), "path_id": None, "considered": 0}

    best_dist = float("inf")
    best = None
    best_support = -1
    for p in candidates:
        d = _path_hausdorff_oneway(trajectory, p.get("polyline") or [])
        # Tie-break by support count: a more-observed path wins ties.
        if (d < best_dist or
                (d == best_dist and p.get("supporting_count", 0) > best_support)):
            best_dist = d
            best = p
            best_support = p.get("supporting_count", 0)

    if best is None or best_dist > max_avg_distance_px:
        return {"destination_leg_id": None, "movement_label": None,
                "distance": best_dist,
                "path_id": best.get("path_id") if best else None,
                "considered": len(candidates)}
    return {
        "destination_leg_id": best.get("destination_leg_id"),
        "movement_label": best.get("movement_label"),
        "distance": best_dist,
        "path_id": best.get("path_id"),
        "considered": len(candidates),
    }


# ---------------------------------------------------------------------------
# Joint partial-Fréchet path scorer (Attribution v2, 2026-05-27).
#
# Supersedes the separate score_origin_by_polyline + score_destination_by_polyline
# pair for polyline-equipped cameras. Rationale (docs/methodology_research_2026-05-26.md
# + docs/implementation_plan_accuracy_2026-05-27.md):
#
#   At this camera vehicles enter YOLO's FOV mid-turn, so a polyline's ENTRY
#   tangent reflects turn state, not approach direction — the entry-tangent
#   assumption baked into score_origin_by_polyline is structurally wrong here.
#   Instead we match the WHOLE trajectory against the best-aligning SUB-CURVE of
#   each candidate path (partial Fréchet). A track that starts mid-turn matches a
#   SUFFIX of the polyline; the uncovered approach portion doesn't contribute to
#   the cost. Origin is then READ OFF the winning path's stored origin_leg_id —
#   never estimated from the unreliable entry tangent. Tails are the trustworthy
#   directional signal here, so a tail-direction prior (exit tangent) breaks ties.
#
# Discrete Fréchet is implemented locally (numpy) rather than depending on
# similaritymeasures/frechetdist — the curves are short, the algorithm is ~30
# lines, and it avoids new-dependency friction on the CPU/Windows target.
# ---------------------------------------------------------------------------


def _unit(vx: float, vy: float) -> tuple[float, float]:
    n = math.hypot(vx, vy)
    if n < 1e-9:
        return (0.0, 0.0)
    return (vx / n, vy / n)


def _densify_polyline(pts: list, step_px: float) -> list:
    """Resample a coarse polyline to ~one point every step_px along its arc.

    Hand-drawn polylines have ~9 vertices spanning the whole frame, so raw
    discrete Fréchet would couple at sparse vertices and overstate distance.
    Densifying makes discrete Fréchet approximate the continuous metric.
    """
    if not pts or len(pts) < 2:
        return [tuple(p) for p in pts]
    out: list[tuple[float, float]] = [(float(pts[0][0]), float(pts[0][1]))]
    for i in range(1, len(pts)):
        ax, ay = float(pts[i - 1][0]), float(pts[i - 1][1])
        bx, by = float(pts[i][0]), float(pts[i][1])
        seg = math.hypot(bx - ax, by - ay)
        if seg < 1e-9:
            continue
        n_steps = max(1, int(seg // step_px))
        for s in range(1, n_steps + 1):
            t = s / n_steps
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return out


def _resample_to(pts: list, n: int) -> list:
    """Uniform index-resample a point list down to at most n points.

    Caps the trajectory length so the Fréchet DP stays cheap on long tracks
    without changing the curve's shape materially.
    """
    m = len(pts)
    if m <= n:
        return [(float(p[0]), float(p[1])) for p in pts]
    idx = [round(i * (m - 1) / (n - 1)) for i in range(n)]
    return [(float(pts[j][0]), float(pts[j][1])) for j in idx]


def _discrete_frechet(P: list, Q: list) -> float:
    """Discrete Fréchet distance between two polylines (lists of (x, y)).

    Standard coupled-walk DP, O(len(P)*len(Q)), computed with a rolling pair of
    rows so memory is O(len(Q)). Returns inf for empty input.
    """
    np_local = _np()
    n, m = len(P), len(Q)
    if n == 0 or m == 0:
        return float("inf")
    Pa = np_local.asarray(P, dtype=np_local.float64)
    Qa = np_local.asarray(Q, dtype=np_local.float64)
    prev = np_local.empty(m, dtype=np_local.float64)
    curr = np_local.empty(m, dtype=np_local.float64)
    # Pairwise distances row-by-row to avoid an n*m matrix on long tracks.
    for i in range(n):
        d_row = np_local.hypot(Qa[:, 0] - Pa[i, 0], Qa[:, 1] - Pa[i, 1])
        for j in range(m):
            if i == 0 and j == 0:
                curr[j] = d_row[0]
            elif i == 0:
                curr[j] = max(curr[j - 1], d_row[j])
            elif j == 0:
                curr[j] = max(prev[0], d_row[0])
            else:
                curr[j] = max(min(prev[j], prev[j - 1], curr[j - 1]), d_row[j])
        prev, curr = curr, prev
    return float(prev[m - 1])


def _np():
    import numpy as np
    return np


def _dtw_mean(P: list, Q: list) -> float:
    """Mean coupled distance between two polylines via DTW alignment.

    Like _discrete_frechet, DTW finds a monotone coupling that respects point
    order (so it measures SHAPE, not just spatial overlap the way one-way
    Hausdorff does). Unlike Fréchet — which reports the single worst coupled
    distance (a sup norm) — DTW accumulates the SUM along the optimal coupling,
    which we normalise to a per-step mean. That makes it robust to the tracking
    jitter that spikes Fréchet on real trajectories: empirically, real
    best-match Fréchet costs here run ~80 px median (outlier-dominated) while
    the mean coupled distance lives at the ~20-30 px scale the proven Stage A
    mean-perpendicular destination scorer operated at.

    Normalised by the actual optimal warping-path length (tracked alongside the
    cost DP), so the returned value is a true mean coupled distance in pixels.
    """
    np_local = _np()
    n, m = len(P), len(Q)
    if n == 0 or m == 0:
        return float("inf")
    Pa = np_local.asarray(P, dtype=np_local.float64)
    Qa = np_local.asarray(Q, dtype=np_local.float64)
    prev = np_local.empty(m, dtype=np_local.float64)
    curr = np_local.empty(m, dtype=np_local.float64)
    prev_k = np_local.empty(m, dtype=np_local.int64)   # warping-path length to each cell
    curr_k = np_local.empty(m, dtype=np_local.int64)
    for i in range(n):
        d_row = np_local.hypot(Qa[:, 0] - Pa[i, 0], Qa[:, 1] - Pa[i, 1])
        for j in range(m):
            if i == 0 and j == 0:
                curr[j] = d_row[0]; curr_k[j] = 1
            elif i == 0:
                curr[j] = curr[j - 1] + d_row[j]; curr_k[j] = curr_k[j - 1] + 1
            elif j == 0:
                curr[j] = prev[0] + d_row[0]; curr_k[j] = prev_k[0] + 1
            else:
                up, diag, left = prev[j], prev[j - 1], curr[j - 1]
                best = min(up, diag, left)
                curr[j] = d_row[j] + best
                if best == diag:
                    curr_k[j] = prev_k[j - 1] + 1
                elif best == left:
                    curr_k[j] = curr_k[j - 1] + 1
                else:
                    curr_k[j] = prev_k[j] + 1
        prev, curr = curr, prev
        prev_k, curr_k = curr_k, prev_k
    return float(prev[m - 1]) / int(prev_k[m - 1])


def _subsequence_dtw(traj: list, poly_dense: list) -> tuple[int, int, float]:
    """Best free-start / fixed-end alignment of the FULL trajectory to a SUFFIX
    of poly_dense, in ONE DP pass — the fast equivalent of sweeping every start
    index and running a full DTW each time.

    Subsequence-DTW: the trajectory's first point may align to ANY polyline point
    for free (row 0 = raw distances, not cumulative), so a prefix of the polyline
    is skipped at no cost (the mid-turn-entry case). The match must consume the
    whole trajectory and end at the polyline's last point (fixed exit). Tracks
    the optimal warping-path length (for a true mean coupled distance) and the
    start index it entered at (for the coverage penalty).

    Returns (start_idx, end_idx=m-1, mean_coupled_distance). O(n*m) once, vs the
    old O(m) full DTWs — ~m× faster, which is the difference between a seconds
    and a tens-of-minutes replay over the full trajectory set.
    """
    np_local = _np()
    n, m = len(traj), len(poly_dense)
    if n == 0 or m == 0:
        return (0, max(0, m - 1), float("inf"))
    T = np_local.asarray(traj, dtype=np_local.float64)
    P = np_local.asarray(poly_dense, dtype=np_local.float64)
    INF = float("inf")
    prev_c = np_local.empty(m); curr_c = np_local.empty(m)
    prev_k = np_local.empty(m, dtype=np_local.int64); curr_k = np_local.empty(m, dtype=np_local.int64)
    prev_s = np_local.empty(m, dtype=np_local.int64); curr_s = np_local.empty(m, dtype=np_local.int64)
    for i in range(n):
        d_row = np_local.hypot(P[:, 0] - T[i, 0], P[:, 1] - T[i, 1])
        for j in range(m):
            d = d_row[j]
            if i == 0:
                # Free start: trajectory[0] may begin at any polyline point.
                curr_c[j] = d; curr_k[j] = 1; curr_s[j] = j
            elif j == 0:
                curr_c[j] = d + prev_c[0]; curr_k[j] = prev_k[0] + 1; curr_s[j] = prev_s[0]
            else:
                up, diag, left = prev_c[j], prev_c[j - 1], curr_c[j - 1]
                best = min(up, diag, left)
                curr_c[j] = d + best
                if best == diag:
                    curr_k[j] = prev_k[j - 1] + 1; curr_s[j] = prev_s[j - 1]
                elif best == left:
                    curr_k[j] = curr_k[j - 1] + 1; curr_s[j] = curr_s[j - 1]
                else:
                    curr_k[j] = prev_k[j] + 1; curr_s[j] = prev_s[j]
        prev_c, curr_c = curr_c, prev_c
        prev_k, curr_k = curr_k, prev_k
        prev_s, curr_s = curr_s, prev_s
    end = m - 1
    total = float(prev_c[end])
    if total == INF:
        return (0, end, INF)
    return (int(prev_s[end]), end, total / int(prev_k[end]))


def _mdh_cost(P: list, Q: list) -> float:
    """Fragmentation-robust matching cost (Phase 2.3): MIN of the two directed
    mean-of-minimum distances + tail-direction term + exit-proximity term.

    The published basis (arXiv 2111.09171: min directed Hausdorff + angle +
    end-proximity, purpose-built for broken vision trajectories, 99.8% vs
    56.9% for symmetric Hausdorff on dense oblique views): a FRAGMENT of a
    movement lies close to its full reference polyline in ONE direction (every
    fragment point is near the polyline) even though the reverse direction is
    large (most of the polyline is far from the fragment) — so taking the MIN
    tolerates partial coverage without a free-start DP. The tail-direction and
    exit-proximity terms restore the discrimination the relaxation gives up
    (they separate a through fragment from a collinear turn's shared prefix).
    Units: px (degrees weighted in at 0.5 px/deg).
    """
    np_local = _np()
    if len(P) < 2 or len(Q) < 2:
        return float("inf")
    Pa = np_local.asarray(P, dtype=np_local.float64)
    Qa = np_local.asarray(Q, dtype=np_local.float64)
    diff = Pa[:, None, :] - Qa[None, :, :]
    dmat = np_local.hypot(diff[..., 0], diff[..., 1])
    base = min(float(dmat.min(axis=1).mean()), float(dmat.min(axis=0).mean()))

    def _tail_bearing(A):
        k = min(3, len(A) - 1)
        v = A[-1] - A[-1 - k]
        if abs(v[0]) < 1e-9 and abs(v[1]) < 1e-9:
            return None
        import math as _m
        return _m.degrees(_m.atan2(v[0], -v[1])) % 360
    tb_p, tb_q = _tail_bearing(Pa), _tail_bearing(Qa)
    ang = 0.0
    if tb_p is not None and tb_q is not None:
        ang = abs((tb_p - tb_q + 180) % 360 - 180)
    end_prox = float(np_local.hypot(*(Pa[-1] - Qa[-1])))
    return base + 0.5 * ang + 0.25 * end_prox


def _min_directed(P: list, Q: list) -> float:
    """MIN of the two directed mean-of-minimum point distances between two
    polylines — the ``base`` term of :func:`_mdh_cost` in isolation.

    A small value means the two curves are collinear/overlapping along at least
    one direction: every point of one curve lies near the other. This is exactly
    the mdh ambiguity the entry-tiebreak resolves — two paths that merge to a
    shared exit read as "the same shape" here even though their entries diverge.
    Kept as a standalone kernel (small duplication of _mdh_cost's base) so the
    shipped scoring cost is untouched.
    """
    np_local = _np()
    if len(P) < 2 or len(Q) < 2:
        return float("inf")
    Pa = np_local.asarray(P, dtype=np_local.float64)
    Qa = np_local.asarray(Q, dtype=np_local.float64)
    diff = Pa[:, None, :] - Qa[None, :, :]
    dmat = np_local.hypot(diff[..., 0], diff[..., 1])
    return min(float(dmat.min(axis=1).mean()), float(dmat.min(axis=0).mean()))


_COST_METRICS = {
    "dtw_mean": _dtw_mean,
    "frechet": _discrete_frechet,
    "mdh": _mdh_cost,
}


def _best_partial_frechet(
    traj: list, poly_dense: list, *, stride: int = 1, cost_metric: str = "dtw_mean",
) -> tuple[int, int, float]:
    """Best matching SUB-CURVE of poly_dense for the full trajectory.

    Sweeps the start index over poly_dense (the matched portion is the
    suffix poly_dense[start:]), keeping the polyline's exit fixed. This
    directly targets the mid-turn-entry failure mode: a trajectory that
    only sees the back half of a movement matches a suffix of the path,
    and the missing approach prefix is not penalised. Returns
    (start_idx, end_idx, cost).

    cost_metric selects the per-candidate coupling cost: "dtw_mean" (robust
    mean coupled distance, the default — see _dtw_mean) or "frechet" (the
    classic sup-norm discrete Fréchet, kept for comparison/tests).
    """
    m = len(poly_dense)
    if m < 2 or len(traj) < 2:
        return (0, max(0, m - 1), float("inf"))
    # Fast single-pass subsequence DP for the (default) mean metric.
    if cost_metric == "dtw_mean":
        return _subsequence_dtw(traj, poly_dense)
    # MDH is partial-overlap-tolerant by construction (min of directed
    # distances) — no start sweep needed; one full-curve evaluation.
    if cost_metric == "mdh":
        return (0, m - 1, _mdh_cost(traj, poly_dense))
    # Sup-norm Fréchet has no cheap free-start DP form; sweep start indices.
    cost_fn = _COST_METRICS[cost_metric]
    best_cost = float("inf")
    best_start = 0
    end = m - 1
    for start in range(0, m - 1, max(1, stride)):
        sub = poly_dense[start:]
        if len(sub) < 2:
            break
        c = cost_fn(traj, sub)
        if c < best_cost:
            best_cost = c
            best_start = start
    return (best_start, end, best_cost)


def score_path_joint(
    trajectory: list,
    paths: list,
    *,
    max_cost: float = 35.0,
    min_coverage_frac: float = 0.28,
    tail_window: int = 7,
    tail_weight: float = 0.35,
    coverage_weight: float = 0.15,
    densify_step_px: float = 12.0,
    traj_cap: int = 30,
    stride: int = 1,
    cost_metric: str = "dtw_mean",
    turn_tail_prior_floor: float = 0.85,
    turn_min_coverage: float = 0.40,
    entry_tiebreak: bool = False,
    entry_tiebreak_exit_px: float = 15.0,
    entry_tiebreak_collinear_px: float = 15.0,
    entry_tiebreak_min_entry_sep_px: float = 60.0,
    entry_tiebreak_decisive_px: float = 30.0,
    speed_tiebreak: bool = False,
    speed_tiebreak_decisive: float = 1.0,
    speed_tiebreak_min_sep: float = 1.5,
) -> dict:
    """Joint origin+destination+movement scorer via partial Fréchet.

    For each candidate path polyline:
      1. Partial Fréchet — best-aligning sub-curve (suffix) of the polyline vs
         the full trajectory. The matched cost ignores the polyline's uncovered
         approach prefix, so mid-turn-entry tracks still match cleanly.
      2. Coverage — fraction of polyline arc length the matched sub-curve spans.
         Paths matched only by a tiny fragment are rejected (< min_coverage_frac).
      3. Tail-direction prior — cosine similarity between the trajectory's tail
         heading and the matched sub-curve's exit tangent (tails are the
         trustworthy directional signal at this camera; entries are not).
      4. Composite score blends shape, tail prior, and coverage; ties broken by
         supporting_count. A final gate rejects matches whose raw Fréchet cost
         exceeds max_cost.

    Origin is READ OFF the winning path — never estimated from the entry tangent.

    Returns:
      {'origin_leg_id', 'destination_leg_id', 'movement_label', 'path_id',
       'distance', 'coverage', 'considered', 'via'} — all *_id None when no
      path clears the thresholds.
    """
    empty = {
        "origin_leg_id": None, "destination_leg_id": None,
        "movement_label": None, "path_id": None,
        "distance": float("inf"), "coverage": 0.0,
        "considered": 0, "via": "joint_partial_frechet",
        "entry_tiebreak_applied": False, "speed_tiebreak_applied": False,
    }
    if not paths or len(trajectory) < 4:
        return empty

    traj = _resample_to(trajectory, traj_cap)
    tw = min(tail_window, len(traj))
    tail = traj[-tw:]
    tail_dir = _unit(tail[-1][0] - tail[0][0], tail[-1][1] - tail[0][1])

    # Observed pixel speed = median inter-point step of the RAW (un-resampled)
    # trajectory. A blind per-approach signature the speed-tiebreak uses to split
    # collinear shared-exit pairs mdh can't (cam2 SB approaches run ~5 px/step,
    # EB ~1-2 due to camera foreshortening). Computed on the raw points so
    # resampling doesn't distort it.
    _steps = [math.hypot(trajectory[i + 1][0] - trajectory[i][0],
                         trajectory[i + 1][1] - trajectory[i][1])
              for i in range(len(trajectory) - 1)]
    observed_speed = median(_steps) if len(_steps) >= 3 else None

    best_score = -1.0
    best = None
    best_cost = float("inf")
    best_cov = 0.0
    # Every candidate that clears the coverage + turn gates, kept for the
    # entry-tiebreak post-step (only consulted when entry_tiebreak + mdh).
    cands: list = []

    for p in paths:
        poly = p.get("polyline") or []
        if len(poly) < 3:
            continue
        poly_dense = _densify_polyline(poly, densify_step_px)
        if len(poly_dense) < 2:
            continue

        start, end, cost = _best_partial_frechet(
            traj, poly_dense, stride=stride, cost_metric=cost_metric,
        )
        if cost == float("inf"):
            continue

        poly_len = compute_path_distance(poly_dense)
        sub_len = compute_path_distance(poly_dense[start:end + 1])
        coverage = sub_len / poly_len if poly_len > 1e-9 else 0.0
        if coverage < min_coverage_frac:
            continue

        # Exit tangent of the matched sub-curve.
        ex = poly_dense[end]
        ex_prev = poly_dense[max(start, end - 1)]
        exit_dir = _unit(ex[0] - ex_prev[0], ex[1] - ex_prev[1])
        tail_cos = (tail_dir[0] * exit_dir[0] + tail_dir[1] * exit_dir[1])
        tail_prior = (tail_cos + 1.0) / 2.0  # [0, 1]

        # Strict gate for TURN-labelled paths: a turn may only claim a track
        # whose tail genuinely aligns with the turn's exit tangent and that
        # covers enough of the turn arc. Without this, a straight through
        # trajectory shape-matches a turn polyline's sub-curve and gets
        # mislabelled (the EB over-attribution: 245 vs manual 36). Through tails
        # don't align with a turn's exit, so they're rejected here; real turns
        # pass. See docs/turn_attribution_plan_2026-05-29.md.
        if (p.get("movement_label") in ("left", "right", "u_turn")
                and (tail_prior < turn_tail_prior_floor or coverage < turn_min_coverage)):
            continue

        shape_term = 1.0 / (1.0 + cost / 10.0)  # squash; lower cost -> higher
        composite = (
            (1.0 - tail_weight - coverage_weight) * shape_term
            + tail_weight * tail_prior
            + coverage_weight * coverage
        )

        support = p.get("supporting_count", 0)
        cands.append({
            "path": p, "composite": composite, "cost": cost, "coverage": coverage,
            "entry": poly_dense[0], "exit": poly_dense[end], "poly": poly_dense,
        })
        if (composite > best_score
                or (abs(composite - best_score) < 1e-4
                    and best is not None
                    and support > best.get("supporting_count", 0))):
            best_score = composite
            best = p
            best_cost = cost
            best_cov = coverage

    # --- Entry-tiebreak: shared-exit collinear disambiguation (mdh only) -----
    # mdh's min-directed relaxation makes two paths that MERGE to a shared exit
    # and run collinear near it read as the same shape, discarding the ENTRY
    # that actually separates them (cam2 SB-thru vs EB-right, 11 px apart, entries
    # 171 px apart). When the winner has such a rival AND their entries are well
    # separated, re-pick by which candidate's entry is closest to the track's
    # first point. A RELATIVE tiebreak between already-collinear candidates — never
    # an absolute entry->origin estimate (that regressed cam2 14.4->23.5). Fires
    # only under mdh, so dtw cameras are byte-identical. See config
    # ENTRY_TIEBREAK_* + docs/handoff_2026-07-02_session_end.md.
    entry_applied = False
    if (entry_tiebreak and cost_metric == "mdh"
            and best is not None and len(cands) >= 2):
        def _d(a, b):
            return math.hypot(a[0] - b[0], a[1] - b[1])
        top = next((c for c in cands if c["path"] is best), None)
        top_dest = top["path"].get("destination_leg_id") if top else None
        if top is not None and top_dest is not None:
            cluster = [top]
            for c in cands:
                if c is top:
                    continue
                if c["path"].get("destination_leg_id") != top_dest:
                    continue  # not the same exit leg
                if _d(c["exit"], top["exit"]) > entry_tiebreak_exit_px:
                    continue  # exits not co-located
                if _min_directed(c["poly"], top["poly"]) > entry_tiebreak_collinear_px:
                    continue  # not collinear -> shape already separates them
                if _d(c["entry"], top["entry"]) < entry_tiebreak_min_entry_sep_px:
                    continue  # entries too close to be a useful discriminator
                cluster.append(c)
            if len(cluster) >= 2:
                traj_entry = traj[0]
                winner = min(cluster, key=lambda c: _d(c["entry"], traj_entry))
                if (winner is not top
                        and _d(top["entry"], traj_entry) - _d(winner["entry"], traj_entry)
                        >= entry_tiebreak_decisive_px):
                    best = winner["path"]
                    best_cost = winner["cost"]
                    best_cov = winner["coverage"]
                    entry_applied = True

    # --- Speed-tiebreak: same shared-exit collinear cluster, but split by the
    # track's PIXEL SPEED vs each candidate path's `expected_speed` signature.
    # Unlike the (disproven) entry signal, speed is a per-approach signature mdh
    # doesn't use and that FOV-clipping doesn't corrupt: at cam2 SB approaches run
    # ~5 px/step, EB ~1-2. Overrides the mdh pick only when the track's speed is
    # DECISIVELY closer to a collinear rival whose signature differs enough to
    # discriminate. Inert unless the bank paths carry `expected_speed` (blind:
    # computed from supporting tracks, not GT). See config SPEED_TIEBREAK_*.
    speed_applied = False
    if (speed_tiebreak and cost_metric == "mdh" and observed_speed is not None
            and best is not None and len(cands) >= 2 and not entry_applied):
        def _pd(a, b):
            return math.hypot(a[0] - b[0], a[1] - b[1])
        top = next((c for c in cands if c["path"] is best), None)
        top_dest = top["path"].get("destination_leg_id") if top else None
        top_spd = top["path"].get("expected_speed") if top else None
        if top is not None and top_dest is not None and top_spd is not None:
            cluster = [top]
            for c in cands:
                if c is top:
                    continue
                if c["path"].get("destination_leg_id") != top_dest:
                    continue  # not the same exit leg
                if _pd(c["exit"], top["exit"]) > entry_tiebreak_exit_px:
                    continue  # exits not co-located
                if _min_directed(c["poly"], top["poly"]) > entry_tiebreak_collinear_px:
                    continue  # not collinear -> shape already separates them
                c_spd = c["path"].get("expected_speed")
                if c_spd is None or abs(c_spd - top_spd) < speed_tiebreak_min_sep:
                    continue  # no signature, or signatures too close to discriminate
                cluster.append(c)
            if len(cluster) >= 2:
                winner = min(cluster,
                             key=lambda c: abs(observed_speed - c["path"]["expected_speed"]))
                if (winner is not top
                        and abs(observed_speed - top_spd)
                        - abs(observed_speed - winner["path"]["expected_speed"])
                        >= speed_tiebreak_decisive):
                    best = winner["path"]
                    best_cost = winner["cost"]
                    best_cov = winner["coverage"]
                    speed_applied = True

    if best is None or best_cost > max_cost:
        return {**empty,
                "distance": best_cost if best is not None else float("inf"),
                "coverage": best_cov,
                "considered": len(paths)}

    return {
        "origin_leg_id": best.get("origin_leg_id"),
        "destination_leg_id": best.get("destination_leg_id"),
        "movement_label": best.get("movement_label"),
        "path_id": best.get("path_id"),
        "distance": best_cost,
        "coverage": best_cov,
        "considered": len(paths),
        "via": "joint_partial_frechet",
        "entry_tiebreak_applied": entry_applied,
        "speed_tiebreak_applied": speed_applied,
    }


# ---------------------------------------------------------------------------
# Destination-leg classification (bug #5 Phase B).
#
# The angle-bucket classifier above flattens the whole trajectory into one
# number (net_heading_change) and was biased toward "through" — at
# Sunnyvale TX it counted ~120 throughs to ~3 turns per leg, while the
# true split is closer to 60/40. The fix below shifts the decision to
# "which leg did the vehicle exit toward?" by scoring each candidate leg
# on heading + position alignment. Movement type (through/left/right/u_turn)
# is then derived from the (origin, destination) reference-heading geometry,
# not from any hardcoded turn matrix.
#
# When intersection_paths has rows for the camera, score_destination_by_polyline
# above takes precedence in the pipeline. The softmax scorer here is the
# fallback path used by cameras without polyline calibration.
# ---------------------------------------------------------------------------


def _leg_origin_point(leg: dict) -> tuple[float, float]:
    """Return a single (x, y) representing the leg's tripwire location.

    v3 calibration: origin_zone is [[x, y]] (single point). v2: it's
    [[x1, y1], [x2, y2]] — return the midpoint so both shapes feed the
    same downstream geometry.
    """
    oz = leg.get("origin_zone") or []
    if not oz:
        return (0.0, 0.0)
    if len(oz) == 1:
        return (float(oz[0][0]), float(oz[0][1]))
    # Multi-point: average. For 2-point lines this is the midpoint;
    # for unusual shapes it's still a reasonable representative point.
    sx = sum(float(p[0]) for p in oz) / len(oz)
    sy = sum(float(p[1]) for p in oz) / len(oz)
    return (sx, sy)


def _intersection_center(legs: list[dict]) -> tuple[float, float]:
    """Centroid of every leg's origin point. Zero new calibration."""
    if not legs:
        return (0.0, 0.0)
    points = [_leg_origin_point(leg) for leg in legs]
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return (cx, cy)


def _normalize(vx: float, vy: float) -> tuple[float, float]:
    n = math.hypot(vx, vy)
    if n == 0:
        return (0.0, 0.0)
    return (vx / n, vy / n)


def _exit_velocity(trajectory: list[tuple]) -> tuple[float, float]:
    """Unit vector of the trajectory's final motion, averaged over the
    tail to smooth jitter."""
    n = len(trajectory)
    if n < 2:
        return (0.0, 0.0)
    window = max(1, min(n // 5, 7))
    start = trajectory[max(0, n - 1 - window)]
    end = trajectory[-1]
    return _normalize(end[0] - start[0], end[1] - start[1])


def _exit_displacement(trajectory: list[tuple]) -> float:
    """Raw pixel magnitude of the tail-window motion (pre-normalization).

    A near-zero displacement means the vehicle stalled or the trajectory
    finalized mid-frame; in that case the exit-direction signal is just
    detection jitter and score_destination_leg should refuse rather than
    invent a confident answer.
    """
    n = len(trajectory)
    if n < 2:
        return 0.0
    window = max(1, min(n // 5, 7))
    start = trajectory[max(0, n - 1 - window)]
    end = trajectory[-1]
    return math.hypot(end[0] - start[0], end[1] - start[1])


EXIT_DISPLACEMENT_MIN_PX = 20.0


def score_destination_leg(
    trajectory: list[tuple],
    origin_leg_id: int,
    all_legs: list[dict],
    *,
    heading_weight: float = 0.7,
    position_weight: float = 0.3,
    exit_displacement_min_px: float = EXIT_DISPLACEMENT_MIN_PX,
) -> dict:
    """Pick the leg the vehicle most likely exited toward.

    Returns:
      {
        "destination_leg_id": int,
        "confidence": float in [0, 1],
        "posterior": {leg_id: probability},
      }

    Empty result (destination_leg_id=None) when the trajectory is too
    short or there are no candidate legs.

    Scoring: for each leg L, the expected exit direction is the unit
    vector from intersection center to L's origin point. We score the
    trajectory's exit velocity and exit-position-from-center against
    this expected direction. Including the origin leg as a candidate
    is what makes u-turns detectable (exit velocity aligns with the
    origin-direction-from-center).
    """
    if not all_legs or len(trajectory) < 2:
        return {"destination_leg_id": None, "confidence": 0.0, "posterior": {}}

    # Refuse to score when the tail window shows essentially no motion —
    # softmax over a near-zero exit_vel produces a confident wrong answer
    # (defaults to the leg opposite the origin, which derive_movement
    # then labels "through").
    if _exit_displacement(trajectory) < exit_displacement_min_px:
        return {"destination_leg_id": None, "confidence": 0.0, "posterior": {}}

    center = _intersection_center(all_legs)
    exit_vel = _exit_velocity(trajectory)
    exit_pos = trajectory[-1]
    exit_pos_dir = _normalize(exit_pos[0] - center[0], exit_pos[1] - center[1])

    raw_scores: dict[int, float] = {}
    for leg in all_legs:
        lp = _leg_origin_point(leg)
        expected = _normalize(lp[0] - center[0], lp[1] - center[1])
        if expected == (0.0, 0.0):
            raw_scores[leg["leg_id"]] = -1.0  # leg is at the center — unscorable
            continue
        heading_score = exit_vel[0] * expected[0] + exit_vel[1] * expected[1]
        position_score = exit_pos_dir[0] * expected[0] + exit_pos_dir[1] * expected[1]
        raw_scores[leg["leg_id"]] = (
            heading_weight * heading_score + position_weight * position_score
        )

    # Convert raw scores (in [-1, 1]) to a posterior via softmax. Temperature
    # of 4.0 sharpens the distribution so the argmax usually exceeds 0.5
    # when one leg is clearly favored, without being so peaky that small
    # geometric differences get drowned out.
    temp = 4.0
    max_score = max(raw_scores.values())
    exp_scores = {lid: math.exp(temp * (s - max_score)) for lid, s in raw_scores.items()}
    total = sum(exp_scores.values()) or 1.0
    posterior = {lid: v / total for lid, v in exp_scores.items()}

    dest_id = max(posterior, key=posterior.get)
    return {
        "destination_leg_id": dest_id,
        "confidence": posterior[dest_id],
        "posterior": posterior,
    }


def derive_movement(
    origin_leg: dict,
    destination_leg: dict | None,
    all_legs: list[dict] | None = None,
) -> str:
    """Derive movement type from intersection geometry, rank-based.

    Fixed-bucket assignment (delta ≤ 45° → u_turn, etc.) only works at
    perfectly orthogonal intersections. At skewed real-world geometries
    (e.g., NBeltLineRd/NorthwestDr in Sunnyvale, where legs are at
    259°, 61°, 290°, 123° — nowhere near 90° apart) the bucket rule
    mis-labels real destinations:

      origin = Leg 1 (ref 259°)
      → Leg 3 (ref 290°), delta=31° → bucket said u_turn  (wrong!)
      → Leg 4 (ref 123°), delta=224° → bucket said through (also wrong)

    Instead we sort the non-origin legs by delta CCW from origin and
    assign by rank:
      - 3 other legs (4-leg intersection): rank 0/1/2 → left/through/right
      - 2 other legs (T-junction): detect through (delta ≈ 180); other
        becomes left or right by its CCW position
      - 1 other leg (degenerate): left or right by delta
      - ≥4 other legs (5+ leg intersection): fall back to nearest-canonical
        (delta closest to 90/180/270 wins left/through/right).

    Same-leg destinations are u_turn regardless of geometry.

    all_legs is the list of all legs at this intersection (origin
    included). When omitted we fall back to a delta-only check that's
    correct for orthogonal intersections but unreliable otherwise.
    """
    if destination_leg is None:
        return "insufficient_data"
    if destination_leg["leg_id"] == origin_leg["leg_id"]:
        return "u_turn"

    origin_ref = float(origin_leg.get("reference_heading", 0))

    def _delta(leg: dict) -> float:
        return (float(leg.get("reference_heading", 0)) - origin_ref) % 360

    if not all_legs:
        # Legacy callers / tests that haven't passed all_legs. Use the
        # fixed-bucket fallback (correct for orthogonal layouts).
        delta = _delta(destination_leg)
        if 135 <= delta <= 225:
            return "through"
        if delta < 135:
            return "left"
        return "right"

    others = sorted(
        [l for l in all_legs if l["leg_id"] != origin_leg["leg_id"]],
        key=_delta,
    )
    if not others:
        return "u_turn"   # only the origin exists; defensive
    rank = next(
        (i for i, l in enumerate(others) if l["leg_id"] == destination_leg["leg_id"]),
        None,
    )
    if rank is None:
        return "insufficient_data"

    n = len(others)
    if n == 1:
        # Degenerate intersection (only origin + one other). Call it a
        # turn based on which side of origin's heading the other leg sits.
        return "left" if _delta(others[0]) < 180 else "right"

    if n == 2:
        d0 = _delta(others[0])
        d1 = _delta(others[1])
        # If one leg is roughly opposite (within 60° of 180°), it's the
        # through; the other is the turn side. Otherwise both are turns
        # (T-junction with origin = stem).
        dist_180 = lambda d: min(abs(180 - d), abs(180 - d + 360), abs(180 - d - 360))
        if dist_180(d0) < dist_180(d1) and dist_180(d0) <= 60:
            return "through" if rank == 0 else ("left" if d1 < 180 else "right")
        if dist_180(d1) <= 60:
            return "through" if rank == 1 else ("left" if d0 < 180 else "right")
        # No through — pure T-junction with stem as origin.
        return "left" if rank == 0 else "right"

    if n == 3:
        # Canonical 4-leg intersection. Rank by CCW delta → left/through/right.
        return ("left", "through", "right")[rank]

    # 5+ legs: nearest-canonical fallback.
    d = _delta(destination_leg)
    def _angle_dist(a: float, b: float) -> float:
        diff = abs(a - b) % 360
        return min(diff, 360 - diff)
    candidates = [(90.0, "left"), (180.0, "through"), (270.0, "right")]
    return min(candidates, key=lambda t: _angle_dist(d, t[0]))[1]
