"""Auto-calibration service.

Runs a prescan over the first N seconds of a video, clusters trajectory entry
points to infer the intersection's approaches, and proposes one origin-line per
leg with cardinal labels derived from a user-supplied screen-orientation hint.

Decomposed for testability:
- `_prescan` does the cv2/YOLO/tracker work and returns per-track trajectories.
- `cluster_entry_points`, `compute_leg_geometry`, `assign_cardinals` are pure
  functions that accept synthetic trajectories — used by tests without YOLO.
- `auto_calibrate` is the orchestrator.
"""

import logging
import math
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np
from sklearn.cluster import DBSCAN

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ProposedLeg:
    label: str
    cardinal_direction: str
    sort_order: int
    origin_zone: list           # [[x1, y1], [x2, y2]]
    reference_heading: float    # degrees, 0=up
    trajectory_count: int


@dataclass
class CalibrationResult:
    success: bool
    legs: list = field(default_factory=list)
    intersection_center: list = field(default_factory=lambda: [0.0, 0.0])
    frame_jpeg: bytes = b""
    frame_number: int = 0
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "legs": [asdict(leg) for leg in self.legs],
            "intersection_center": self.intersection_center,
            "frame_number": self.frame_number,
            "frame_jpeg_size_bytes": len(self.frame_jpeg),
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

MIN_TRAJECTORY_POINTS = 8
MIN_TRAJECTORY_DISTANCE_PX = 100
DBSCAN_EPS_FRACTION = 0.06      # eps as fraction of min(width, height)
DBSCAN_MIN_SAMPLES = 5
MIN_TRAJECTORIES_PER_LEG = 30
MIN_LEGS_FOR_SUCCESS = 2
ORIGIN_LINE_LENGTH_FRACTION = 0.20

_CARDINALS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_SCREEN_NORTH_OFFSET = {"up": 0, "right": 90, "down": 180, "left": 270}


# ---------------------------------------------------------------------------
# Pure helpers (testable)
# ---------------------------------------------------------------------------

def filter_trajectories(
    raw: dict[int, list[tuple[float, float, int]]],
    min_points: int = MIN_TRAJECTORY_POINTS,
    min_distance: float = MIN_TRAJECTORY_DISTANCE_PX,
) -> dict[int, list[tuple[float, float, int]]]:
    """Drop short/stationary trajectories."""
    kept: dict[int, list[tuple[float, float, int]]] = {}
    for tid, points in raw.items():
        if len(points) < min_points:
            continue
        x0, y0, _ = points[0]
        x1, y1, _ = points[-1]
        if math.hypot(x1 - x0, y1 - y0) < min_distance:
            continue
        kept[tid] = points
    return kept


def cluster_entry_points(
    trajectories: dict[int, list[tuple[float, float, int]]],
    image_size: tuple[int, int],            # (width, height)
    num_legs_hint: int | None = None,
) -> dict[int, list[int]]:
    """Cluster entry points (first point of each trajectory) with DBSCAN.

    Returns a dict mapping cluster_label → list of track_ids.
    Noise points (label = -1) are excluded.

    If `num_legs_hint` is set and clustering produces too many clusters,
    keep only the top-N by support.
    """
    if not trajectories:
        return {}

    tids = list(trajectories.keys())
    entries = np.array([
        [trajectories[t][0][0], trajectories[t][0][1]] for t in tids
    ])

    eps = max(20, int(min(image_size) * DBSCAN_EPS_FRACTION))
    labels = DBSCAN(eps=eps, min_samples=DBSCAN_MIN_SAMPLES).fit_predict(entries)

    clusters: dict[int, list[int]] = {}
    for tid, label in zip(tids, labels):
        if label == -1:
            continue
        clusters.setdefault(int(label), []).append(tid)

    if num_legs_hint is not None and len(clusters) > num_legs_hint:
        # Keep the top-K by support
        top = sorted(clusters.items(), key=lambda kv: len(kv[1]), reverse=True)
        clusters = dict(top[:num_legs_hint])

    return clusters


def compute_leg_geometry(
    cluster: list[int],
    trajectories: dict[int, list[tuple[float, float, int]]],
    image_size: tuple[int, int],
) -> dict:
    """Compute centroid + dominant flow direction for one cluster.

    Returns dict with: centroid, flow_unit, trajectory_count.
    """
    entries = np.array([
        [trajectories[t][0][0], trajectories[t][0][1]] for t in cluster
    ])
    centroid = entries.mean(axis=0)

    # Flow direction = unit vector from entry to a point 10 frames in.
    flow_vectors = []
    for tid in cluster:
        points = trajectories[tid]
        x0, y0, _ = points[0]
        end_idx = min(10, len(points) - 1)
        x1, y1, _ = points[end_idx]
        dx, dy = x1 - x0, y1 - y0
        n = math.hypot(dx, dy)
        if n > 0:
            flow_vectors.append([dx / n, dy / n])

    if flow_vectors:
        flows = np.array(flow_vectors)
        mean = flows.mean(axis=0)
        norm = np.linalg.norm(mean)
        flow_unit = (mean / norm).tolist() if norm > 0 else [0.0, 0.0]
    else:
        flow_unit = [0.0, 0.0]

    return {
        "centroid": centroid.tolist(),
        "flow_unit": flow_unit,
        "trajectory_count": len(cluster),
    }


def screen_bearing_to_cardinal(
    bearing_deg: float, screen_north_direction: str
) -> str:
    """Convert a screen-space bearing (0=up, 90=right, image y-down) to a cardinal.

    `screen_north_direction` says which way on the screen corresponds to real
    north: 'up' is the obvious case; 'right' means turning the video 90° CCW
    aligns north with up.
    """
    offset = _SCREEN_NORTH_OFFSET.get(screen_north_direction.lower(), 0)
    world_bearing = (bearing_deg - offset) % 360
    idx = int(round(world_bearing / 45)) % 8
    return _CARDINALS[idx]


def compute_origin_line(
    centroid: list[float],
    flow_unit: list[float],
    image_size: tuple[int, int],
    length_fraction: float = ORIGIN_LINE_LENGTH_FRACTION,
) -> list[list[float]]:
    """Place an origin line perpendicular to flow_unit, centered on centroid.

    Length = length_fraction * min(width, height).
    """
    width, height = image_size
    length = length_fraction * min(width, height)

    # Perpendicular unit vector (rotate flow_unit by 90°)
    perp = [-flow_unit[1], flow_unit[0]]

    half = length / 2
    x1 = centroid[0] - perp[0] * half
    y1 = centroid[1] - perp[1] * half
    x2 = centroid[0] + perp[0] * half
    y2 = centroid[1] + perp[1] * half

    # Clamp to image bounds
    x1 = max(0.0, min(float(width), x1))
    y1 = max(0.0, min(float(height), y1))
    x2 = max(0.0, min(float(width), x2))
    y2 = max(0.0, min(float(height), y2))

    return [[x1, y1], [x2, y2]]


def compute_reference_heading(
    origin_line: list[list[float]], intersection_center: list[float]
) -> float:
    """Heading from origin line midpoint toward intersection center.

    Image coords: 0°=N(up), 90°=E(right), y increases downward.
    """
    mx = (origin_line[0][0] + origin_line[1][0]) / 2
    my = (origin_line[0][1] + origin_line[1][1]) / 2
    dx = intersection_center[0] - mx
    dy = intersection_center[1] - my
    return math.degrees(math.atan2(dx, -dy)) % 360


def assemble_legs(
    cluster_info: list[dict],
    intersection_center: list[float],
    image_size: tuple[int, int],
    screen_north_direction: str,
) -> list[ProposedLeg]:
    """Build the final ProposedLeg list, sorted clockwise from N."""
    legs_with_bearing = []
    for info in cluster_info:
        # Bearing from intersection center to this leg's centroid (screen space).
        dx = info["centroid"][0] - intersection_center[0]
        dy = info["centroid"][1] - intersection_center[1]
        screen_bearing = math.degrees(math.atan2(dx, -dy)) % 360
        cardinal = screen_bearing_to_cardinal(screen_bearing, screen_north_direction)
        origin_line = compute_origin_line(
            info["centroid"], info["flow_unit"], image_size
        )
        reference_heading = compute_reference_heading(origin_line, intersection_center)
        legs_with_bearing.append({
            "screen_bearing": screen_bearing,
            "cardinal": cardinal,
            "origin_line": origin_line,
            "reference_heading": reference_heading,
            "trajectory_count": info["trajectory_count"],
        })

    # Sort by world bearing (i.e., sort by cardinal index)
    legs_with_bearing.sort(
        key=lambda d: _CARDINALS.index(d["cardinal"])
    )

    result = []
    for i, d in enumerate(legs_with_bearing):
        result.append(ProposedLeg(
            label=f"{d['cardinal']} Approach",
            cardinal_direction=d["cardinal"],
            sort_order=i,
            origin_zone=d["origin_line"],
            reference_heading=d["reference_heading"],
            trajectory_count=d["trajectory_count"],
        ))
    return result


# ---------------------------------------------------------------------------
# Prescan
# ---------------------------------------------------------------------------

def _prescan(
    video_path: str,
    prescan_seconds: int,
    frame_skip: int,
    detector,
    tracker,
    preprocessor,
    progress_callback=None,
) -> tuple[dict[int, list[tuple[float, float, int]]], bytes, int, tuple[int, int]]:
    """Run preprocess→detect→track on the first prescan_seconds.

    Returns (raw_trajectories, sample_frame_jpeg, sample_frame_number, image_size).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        max_frames = int(prescan_seconds * fps)

        raw: dict[int, list[tuple[float, float, int]]] = {}
        sample_jpeg = b""
        sample_frame_number = 0
        frame_number = 0

        while frame_number < max_frames:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_number == 0:
                ok, buf = cv2.imencode(".jpg", frame)
                if ok:
                    sample_jpeg = buf.tobytes()
                    sample_frame_number = 0

            if frame_number % frame_skip == 0:
                try:
                    processed = preprocessor.preprocess(frame)
                    detections = detector.detect(processed)
                    tracked = tracker.update(detections, frame_number)
                    for t in tracked:
                        if not t.get("is_vehicle", False):
                            continue
                        tid = t["track_id"]
                        cx, cy = t["center"][0], t["center"][1]
                        raw.setdefault(tid, []).append((float(cx), float(cy), frame_number))
                except Exception as e:
                    logger.warning("Prescan frame %d failed: %s", frame_number, e)

                if progress_callback and frame_number % (10 * frame_skip) == 0:
                    progress_callback({
                        "frame_number": frame_number,
                        "total_frames": max_frames,
                        "progress_pct": frame_number / max_frames * 100,
                    })

            frame_number += 1
    finally:
        cap.release()

    return raw, sample_jpeg, sample_frame_number, (width, height)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def auto_calibrate(
    video_path: str,
    prescan_seconds: int = 300,
    frame_skip: int = 3,
    screen_north_direction: str = "up",
    num_legs_hint: int | None = None,
    device: str = "cpu",
    progress_callback=None,
    detector_factory=None,    # () -> VehicleDetector — for tests
    tracker_factory=None,     # (fps:int) -> VehicleTracker — for tests
    preprocessor_factory=None,  # () -> AdaptivePreprocessor — for tests
) -> CalibrationResult:
    """Run auto-calibration end-to-end.

    Returns CalibrationResult. `success=False` means too few legs were
    detected; the caller should let the user try a longer prescan or fall
    back to manual mode.
    """
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()

    if detector_factory is None:
        from backend.services.detector import VehicleDetector
        detector = VehicleDetector()
    else:
        detector = detector_factory()

    if tracker_factory is None:
        from backend.services.tracker import VehicleTracker
        tracker = VehicleTracker(frame_rate=int(fps))
    else:
        tracker = tracker_factory(int(fps))

    if preprocessor_factory is None:
        from backend.services.preprocessor import AdaptivePreprocessor
        preprocessor = AdaptivePreprocessor()
    else:
        preprocessor = preprocessor_factory()

    raw, sample_jpeg, sample_frame_number, image_size = _prescan(
        video_path, prescan_seconds, frame_skip,
        detector, tracker, preprocessor, progress_callback,
    )

    filtered = filter_trajectories(raw)

    if len(filtered) < MIN_TRAJECTORIES_PER_LEG * MIN_LEGS_FOR_SUCCESS:
        return CalibrationResult(
            success=False,
            frame_jpeg=sample_jpeg,
            frame_number=sample_frame_number,
            intersection_center=[image_size[0] / 2, image_size[1] / 2],
            reason=(
                f"Only {len(filtered)} usable trajectories — need at least "
                f"{MIN_TRAJECTORIES_PER_LEG * MIN_LEGS_FOR_SUCCESS}. "
                "Try a longer prescan or check if the video has enough traffic."
            ),
        )

    clusters = cluster_entry_points(filtered, image_size, num_legs_hint)

    qualifying = {
        label: tids for label, tids in clusters.items()
        if len(tids) >= MIN_TRAJECTORIES_PER_LEG
    }

    if len(qualifying) < MIN_LEGS_FOR_SUCCESS:
        return CalibrationResult(
            success=False,
            frame_jpeg=sample_jpeg,
            frame_number=sample_frame_number,
            intersection_center=[image_size[0] / 2, image_size[1] / 2],
            reason=(
                f"Only {len(qualifying)} cluster(s) had ≥{MIN_TRAJECTORIES_PER_LEG} "
                "trajectories. Try a longer prescan or use manual mode."
            ),
        )

    leg_infos = [
        compute_leg_geometry(tids, filtered, image_size)
        for tids in qualifying.values()
    ]

    # Intersection center: trajectory-count-weighted average of cluster centroids.
    total = sum(info["trajectory_count"] for info in leg_infos)
    cx = sum(info["centroid"][0] * info["trajectory_count"] for info in leg_infos) / total
    cy = sum(info["centroid"][1] * info["trajectory_count"] for info in leg_infos) / total
    intersection_center = [cx, cy]

    legs = assemble_legs(leg_infos, intersection_center, image_size, screen_north_direction)

    return CalibrationResult(
        success=True,
        legs=legs,
        intersection_center=intersection_center,
        frame_jpeg=sample_jpeg,
        frame_number=sample_frame_number,
    )
