"""Phase-0 auto-calibration prototype.

Watches a sample window of a video, collects vehicle trajectories via the
production detector + tracker, then clusters trajectory starts/ends into
leg zones and fits per-(origin, destination) polylines through the mean
trajectory of each pair. Output is a JSON suggestion that the engineer
will eventually review in the calibration UI — for now it's just
inspected via scripts/auto_calibrate_viz.py.

No production code is touched by this script. It exists to validate the
clustering approach on Sunnyvale before we commit to Phases 1-3.

Usage:
  py scripts/auto_calibrate.py --video PATH [--sample-start S] [--sample-end S] [--out PATH]
  # Defaults: 15-minute sample from t=0; output to evaluations/auto_cal_<basename>.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.signal import savgol_filter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detector import VehicleDetector
from backend.services.tracker import VehicleTracker


class AutoCalCancelled(Exception):
    """Raised when a caller-supplied should_cancel() asks the trajectory
    collection to stop early. Callers catch this to mark the job cancelled
    rather than errored."""


# --- Tunables (exposed via CLI; defaults chosen for Sunnyvale geometry) ---

DEFAULT_SAMPLE_SECONDS = 15 * 60          # 15-min window
DEFAULT_YOLO_MODEL     = "yolo26s.pt"     # Balanced mode model
DEFAULT_YOLO_IMGSZ     = 960
DEFAULT_YOLO_CONF      = 0.10

MIN_TRAJECTORY_POINTS  = 8                # filter: too-short tracks discarded
MIN_TRAJECTORY_PATH_PX = 80               # filter: stalled/jitter tracks discarded

DBSCAN_EPS_PX          = 40.0             # zone cluster radius (single-link)
DBSCAN_MIN_SAMPLES     = 10               # min trajectories to form a zone

PATH_MIN_SUPPORT       = 8                # (entry, exit) pairs need this many trajectories
POLYLINE_CONTROL_POINTS = 15              # resample each trajectory to this many points
POLYLINE_SMOOTHING_WINDOW = 5             # Savitzky-Golay window (odd)
POLYLINE_SMOOTHING_POLY = 2

ZONE_MEMBERSHIP_PX     = 60.0             # trajectory start/end within this of zone centroid
THROUGH_ANGLE_DEG      = 30.0             # |delta tangent| < this -> through
CONFIDENCE_HIGH        = 100              # supporting_count thresholds for confidence label
CONFIDENCE_MEDIUM      = 25


# --- Trajectory collection ----------------------------------------------

def collect_trajectories(
    video_path: str,
    sample_start_sec: float,
    sample_end_sec: float,
    yolo_model: str = DEFAULT_YOLO_MODEL,
    yolo_imgsz: int = DEFAULT_YOLO_IMGSZ,
    yolo_confidence: float = DEFAULT_YOLO_CONF,
    progress_every_sec: float = 30.0,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[dict], None] | None = None,
    on_progress_every_sec: float = 1.0,
) -> tuple[list[list[tuple[float, float]]], tuple[int, int], dict]:
    """Run detector + tracker on the sample window. Return:
      ( list of trajectories, each = [(x, y), ...] in image coords ,
        (frame_w, frame_h) ,
        stats dict )

    Filters: trajectory must have >= MIN_TRAJECTORY_POINTS and a path
    distance >= MIN_TRAJECTORY_PATH_PX. Vehicle classes only (cars,
    motorcycles, buses, trucks — same set the pipeline uses)."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        start_frame = int(round(sample_start_sec * fps))
        end_frame   = int(round(sample_end_sec   * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        detector = VehicleDetector(model_path=yolo_model, imgsz=yolo_imgsz,
                                   confidence=yolo_confidence)
        tracker  = VehicleTracker(frame_rate=int(round(fps)))

        active: dict[int, list[tuple[float, float]]] = defaultdict(list)
        finished: list[list[tuple[float, float]]] = []
        # Parallel frame stamps for the F3 hook payload only — clustering
        # consumes `active`/`finished` (x,y) exactly as before.
        active_f: dict[int, list[int]] = defaultdict(list)

        frame_no = start_frame
        last_log = time.time()
        last_progress = 0.0
        n_detections = 0

        while frame_no < end_frame:
            # Honor cancellation mid-pass (every ~30 frames keeps the flag
            # check cheap relative to detection cost). Without this the whole
            # window runs to completion before the caller's cancel is seen.
            if should_cancel and (frame_no - start_frame) % 30 == 0 \
                    and should_cancel():
                raise AutoCalCancelled()
            ok, frame = cap.read()
            if not ok:
                break
            detections = [d for d in detector.detect(frame) if d["is_vehicle"]]
            n_detections += len(detections)
            tracked = tracker.update(detections, frame_no)

            present_ids = {t["track_id"] for t in tracked}
            for t in tracked:
                active[t["track_id"]].append(
                    (float(t["center"][0]), float(t["center"][1])),
                )
                active_f[t["track_id"]].append(frame_no)
            # Drop tracks the tracker stopped emitting — they're done.
            for tid in list(active.keys()):
                if tid not in present_ids:
                    finished.append(active.pop(tid))
                    active_f.pop(tid, None)

            now = time.time()
            if now - last_log >= progress_every_sec:
                progress = (frame_no - start_frame) / max(1, end_frame - start_frame)
                print(f"  [auto-cal] frame {frame_no}/{end_frame}  "
                      f"({progress*100:.1f}%)  active_tracks={len(active)}  "
                      f"finished={len(finished)}", file=sys.stderr)
                last_log = now
            # Live-perception hook (F2, plan_f2_livecal_2026-07-28):
            # OBSERVATIONAL ONLY — the callback sees the loop's state and
            # must not mutate it; on_progress=None is byte-identical to
            # the legacy path. Throttled independently of the log cadence.
            if on_progress is not None and now - last_progress >= on_progress_every_sec:
                try:
                    on_progress({
                        "frame_no": frame_no,
                        "start_frame": start_frame,
                        "end_frame": end_frame,
                        "progress": (frame_no - start_frame)
                        / max(1, end_frame - start_frame),
                        "active": len(active),
                        "finished": len(finished),
                        "frame": frame,
                        "tracked": tracked,
                        "trails": {tid: pts[-30:]
                                   for tid, pts in active.items()},
                        "trails_f": {tid: fs[-30:]
                                     for tid, fs in active_f.items()},
                    })
                except Exception:
                    # A preview failure must never kill calibration.
                    pass
                last_progress = now
            frame_no += 1

        # Flush still-active tracks at the end of the window.
        for tid in list(active.keys()):
            finished.append(active.pop(tid))

        # Filter.
        kept: list[list[tuple[float, float]]] = []
        for traj in finished:
            if len(traj) < MIN_TRAJECTORY_POINTS:
                continue
            if _path_distance(traj) < MIN_TRAJECTORY_PATH_PX:
                continue
            kept.append(traj)

        stats = {
            "frames_processed": frame_no - start_frame,
            "detections_total": n_detections,
            "trajectories_raw": len(finished),
            "trajectories_kept": len(kept),
            "fps_source": fps,
        }
        return kept, (frame_w, frame_h), stats
    finally:
        cap.release()


def _path_distance(traj: list[tuple[float, float]]) -> float:
    return sum(math.hypot(traj[i][0] - traj[i-1][0], traj[i][1] - traj[i-1][1])
               for i in range(1, len(traj)))


# --- Clustering ---------------------------------------------------------

def dbscan_like(
    points: np.ndarray, eps_px: float, min_samples: int,
) -> np.ndarray:
    """DBSCAN-semantics clustering: single linkage over CORE points
    (>= min_samples neighbors within eps), border points attached to
    the nearest core cluster within eps, everything else noise (-1).

    2026-08-18: the original pure single-linkage-at-cut claimed DBSCAN
    equivalence, which held only for SPARSE samples — it lacks the
    density (core-point) rule, so at busy-window density the sparse
    endpoint bridges between real zones CHAINED everything into one
    mega-cluster (the 19k-trajectory cam2 17:00 sample collapsed to
    1 zone / 1 path). The core rule dissolves sparse bridges; compact
    small-sample zones keep their cores and their border members
    attach exactly as DBSCAN's border rule attaches them. A KDTree
    keeps neighbor counts O(n log n), and the linkage input is capped
    (O(n^2) memory) with the overflow attached by proximity."""
    n = len(points)
    if n < 2:
        return np.full(n, -1, dtype=int)
    from scipy.spatial import cKDTree
    tree = cKDTree(points)
    n_nbrs = np.asarray(
        tree.query_ball_point(points, r=eps_px, return_length=True))
    core = n_nbrs >= min_samples
    labels = np.full(n, -1, dtype=int)
    if not core.any():
        # Legacy sparse regime (nothing reaches core density): original
        # behavior so low-volume samples still form their zones.
        Z = linkage(points, method="single")
        labels = fcluster(Z, t=eps_px, criterion="distance")
    else:
        core_idx = np.where(core)[0]
        if len(core_idx) > 6000:
            rng = np.random.default_rng(0)
            core_idx = np.sort(rng.choice(core_idx, 6000, replace=False))
        cpts = points[core_idx]
        if len(cpts) == 1:
            raw = np.array([1])
        else:
            Z = linkage(cpts, method="single")
            raw = fcluster(Z, t=eps_px, criterion="distance")
        labels[core_idx] = raw
        rest = np.where(labels == -1)[0]
        if len(rest):
            ctree = cKDTree(cpts)
            d, j = ctree.query(points[rest], k=1)
            ok = d <= eps_px
            labels[rest[ok]] = raw[j[ok]]
    pos_mask = labels >= 0
    if not pos_mask.any():
        return np.full(n, -1, dtype=int)
    counts = np.bincount(labels[pos_mask])
    keep_mask = counts >= min_samples
    labels = np.where(pos_mask & keep_mask[np.clip(labels, 0, None)],
                      labels, -1)
    # Relabel kept clusters to dense 0..K-1 ordering by size desc.
    kept_ids = sorted({l for l in labels if l != -1},
                      key=lambda l: -(labels == l).sum())
    remap = {old: new for new, old in enumerate(kept_ids)}
    return np.array([remap.get(l, -1) for l in labels])


def cluster_zones(
    trajectories: list[list[tuple[float, float]]],
    which_end: str,
    eps_px: float = DBSCAN_EPS_PX,
    min_samples: int = DBSCAN_MIN_SAMPLES,
) -> list[dict]:
    """Cluster trajectory START (which_end='start') or END points into zones.

    Returns list of dicts:
      [{"zone_id": int, "centroid": (x, y), "supporting_count": int,
        "trajectory_indices": [int, ...]}, ...]
    Sorted by supporting_count desc."""
    if not trajectories:
        return []
    pts = np.array(
        [traj[0] if which_end == "start" else traj[-1] for traj in trajectories],
        dtype=np.float64,
    )
    labels = dbscan_like(pts, eps_px, min_samples)
    out = []
    for zid in sorted(set(labels)):
        if zid == -1:
            continue
        idx = np.where(labels == zid)[0]
        centroid = pts[idx].mean(axis=0)
        out.append({
            "zone_id": int(zid),
            "centroid": (float(centroid[0]), float(centroid[1])),
            "supporting_count": int(len(idx)),
            "trajectory_indices": [int(i) for i in idx],
        })
    return out


# --- Path discovery -----------------------------------------------------

def _classify_zone(point: tuple[float, float], zones: list[dict],
                   radius_px: float) -> int | None:
    """Which zone's centroid is `point` closest to, within radius_px?"""
    best, best_d = None, float("inf")
    for z in zones:
        d = math.hypot(point[0] - z["centroid"][0], point[1] - z["centroid"][1])
        if d < best_d:
            best_d, best = d, z["zone_id"]
    return best if best is not None and best_d <= radius_px else None


def discover_paths(
    trajectories: list[list[tuple[float, float]]],
    entry_zones: list[dict],
    exit_zones: list[dict],
    membership_radius_px: float = ZONE_MEMBERSHIP_PX,
    min_support: int = PATH_MIN_SUPPORT,
) -> list[dict]:
    """For each trajectory, look up which entry zone and exit zone its
    first/last point belongs to. Group trajectories by (entry_id, exit_id).
    Pairs with >= min_support trajectories become candidate paths; fit a
    smoothed polyline through their mean trajectory.

    Returns:
      [{"entry_zone_id": int, "exit_zone_id": int,
        "polyline": [(x, y), ...],
        "supporting_count": int}, ...]
    """
    buckets: dict[tuple[int, int], list[list[tuple[float, float]]]] = defaultdict(list)
    for traj in trajectories:
        ein = _classify_zone(traj[0],  entry_zones, membership_radius_px)
        eout = _classify_zone(traj[-1], exit_zones,  membership_radius_px)
        if ein is None or eout is None:
            continue
        buckets[(ein, eout)].append(traj)

    paths = []
    for (ein, eout), group in buckets.items():
        if len(group) < min_support:
            continue
        polyline = _fit_mean_polyline(group, POLYLINE_CONTROL_POINTS)
        if polyline is None:
            continue
        paths.append({
            "entry_zone_id": ein,
            "exit_zone_id": eout,
            "polyline": polyline,
            "supporting_count": len(group),
        })
    # Sort by support desc for readable output.
    paths.sort(key=lambda p: -p["supporting_count"])
    return paths


def _resample_by_arclength(
    traj: list[tuple[float, float]], n_points: int,
) -> list[tuple[float, float]]:
    """Resample a trajectory to n_points equally spaced along its arc length."""
    if len(traj) < 2 or n_points < 2:
        return list(traj)
    arr = np.asarray(traj, dtype=np.float64)
    deltas = np.linalg.norm(np.diff(arr, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(deltas)])
    total = cum[-1]
    if total == 0:
        return [tuple(arr[0])] * n_points
    targets = np.linspace(0.0, total, n_points)
    xs = np.interp(targets, cum, arr[:, 0])
    ys = np.interp(targets, cum, arr[:, 1])
    return [(float(x), float(y)) for x, y in zip(xs, ys)]


def _fit_mean_polyline(
    trajectories: list[list[tuple[float, float]]],
    n_points: int,
) -> list[tuple[float, float]] | None:
    """Resample each trajectory to n_points, take the median at each
    position, then smooth. Median (not mean) for robustness to outlier
    paths (e.g., a single lane-change weaving trajectory)."""
    if not trajectories:
        return None
    grid = np.zeros((len(trajectories), n_points, 2), dtype=np.float64)
    for i, t in enumerate(trajectories):
        rs = _resample_by_arclength(t, n_points)
        grid[i] = np.asarray(rs, dtype=np.float64)
    med = np.median(grid, axis=0)  # shape (n_points, 2)
    # Smooth if we have enough points for the SG window.
    if n_points >= POLYLINE_SMOOTHING_WINDOW:
        med[:, 0] = savgol_filter(med[:, 0], POLYLINE_SMOOTHING_WINDOW,
                                   POLYLINE_SMOOTHING_POLY)
        med[:, 1] = savgol_filter(med[:, 1], POLYLINE_SMOOTHING_WINDOW,
                                   POLYLINE_SMOOTHING_POLY)
    return [(float(x), float(y)) for x, y in med]


# --- Movement label + heading derivation --------------------------------

def _segment_heading_deg(
    p1: tuple[float, float], p2: tuple[float, float],
) -> float:
    """Heading from p1 to p2 in degrees, 0=N (up), 90=E (right).
    Image coords (y down)."""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return math.degrees(math.atan2(dx, -dy)) % 360


def derive_path_movement(path: dict, n_tangent_segments: int = 3) -> str:
    """Label the path by comparing the tangent of its entry segment vs
    its exit segment. Uses polyline tangents so curving roads (where
    entry direction differs from exit direction by the natural road
    curve) still get the right label."""
    poly = path["polyline"]
    if len(poly) < 2:
        return "insufficient_data"
    # Same entry+exit zone — u-turn by construction.
    if path["entry_zone_id"] == path["exit_zone_id"]:
        return "u_turn"
    # Use first/last n_tangent_segments segments for stable tangent estimate.
    k = max(1, min(n_tangent_segments, len(poly) // 3))
    entry_heading = _segment_heading_deg(poly[0], poly[k])
    exit_heading  = _segment_heading_deg(poly[-(k+1)], poly[-1])
    delta = (exit_heading - entry_heading + 180) % 360 - 180
    abs_delta = abs(delta)
    if abs_delta < THROUGH_ANGLE_DEG:
        return "through"
    if abs_delta >= 180 - THROUGH_ANGLE_DEG:
        return "u_turn"
    return "left" if delta < 0 else "right"


def derive_zone_reference_heading(
    zone: dict,
    trajectories: list[list[tuple[float, float]]],
    n_first_points: int = 5,
) -> float:
    """Median initial-motion heading of the trajectories starting in this
    zone. Direction the vehicle MOVES on approach."""
    headings = []
    for idx in zone["trajectory_indices"]:
        t = trajectories[idx]
        end = t[min(n_first_points, len(t) - 1)]
        headings.append(_segment_heading_deg(t[0], end))
    # Circular median via sin/cos averaging.
    rads = np.deg2rad(headings)
    mean_sin = float(np.median(np.sin(rads)))
    mean_cos = float(np.median(np.cos(rads)))
    return float(math.degrees(math.atan2(mean_sin, mean_cos)) % 360)


# --- Top-level orchestrator + CLI ---------------------------------------

def _label_confidence(supporting_count: int) -> str:
    if supporting_count >= CONFIDENCE_HIGH:    return "high"
    if supporting_count >= CONFIDENCE_MEDIUM:  return "medium"
    return "low"


def run(video_path: str, sample_start_sec: float, sample_end_sec: float,
        yolo_model: str = DEFAULT_YOLO_MODEL,
        yolo_imgsz: int = DEFAULT_YOLO_IMGSZ,
        yolo_confidence: float = DEFAULT_YOLO_CONF,
        eps_px: float = DBSCAN_EPS_PX,
        min_samples: int = DBSCAN_MIN_SAMPLES,
        should_cancel: Callable[[], bool] | None = None,
        on_progress: Callable[[dict], None] | None = None,
        save_trajectories_to: str | None = None) -> dict:
    """End-to-end: collect → cluster → discover paths → label movements."""
    t0 = time.time()
    trajectories, (fw, fh), stats = collect_trajectories(
        video_path, sample_start_sec, sample_end_sec,
        yolo_model=yolo_model, yolo_imgsz=yolo_imgsz,
        yolo_confidence=yolo_confidence,
        should_cancel=should_cancel,
        on_progress=on_progress,
    )
    if save_trajectories_to:
        # Persist the (expensive) collection so clustering can be
        # re-run without re-decoding hours of video. Best-effort.
        try:
            arrs = {f"t{i}": np.asarray(t, dtype=np.float32)
                    for i, t in enumerate(trajectories)}
            np.savez_compressed(
                save_trajectories_to,
                frame_size=np.array([fw, fh]),
                window=np.array([sample_start_sec, sample_end_sec]),
                **arrs)
        except Exception:
            pass

    # Cluster entry zones (start positions) and exit zones (end positions).
    # The entry-zone set is the "leg origin" candidates. At busy-window
    # density, queue fragmentation scatters endpoints mid-frame; if the
    # full-set clustering degenerates (< 3 zones — the chained case),
    # retry on the frame-border band where real leg mouths live, and
    # keep the better result (2026-08-18; the 1-zone collapse).
    def _cluster_with_fallback(which: str):
        zones = cluster_zones(trajectories, which,
                              eps_px=eps_px, min_samples=min_samples)
        fallback = None
        if len(zones) < 3:
            band = 0.18 * min(fw, fh)
            idxs = []
            for i, t in enumerate(trajectories):
                x, y = t[0] if which == "start" else t[-1]
                if (x < band or y < band
                        or x > fw - band or y > fh - band):
                    idxs.append(i)
            if len(idxs) >= min_samples:
                sub = [trajectories[i] for i in idxs]
                alt = cluster_zones(sub, which,
                                    eps_px=eps_px, min_samples=min_samples)
                if len(alt) > len(zones):
                    for z in alt:
                        z["trajectory_indices"] = [
                            idxs[i] for i in z["trajectory_indices"]]
                    zones, fallback = alt, "border_band"
        return zones, fallback

    entry_zones, zone_fb_in = _cluster_with_fallback("start")
    exit_zones, zone_fb_out = _cluster_with_fallback("end")
    # Reference heading per entry zone.
    for z in entry_zones:
        z["reference_heading"] = derive_zone_reference_heading(z, trajectories)

    # Discover paths and label their movements.
    paths = discover_paths(trajectories, entry_zones, exit_zones)
    for p in paths:
        p["movement_label"] = derive_path_movement(p)

    return {
        "video_path": video_path,
        "sample_window": [sample_start_sec, sample_end_sec],
        "frame_size": [fw, fh],
        "stats": {
            **stats,
            "wall_seconds": round(time.time() - t0, 1),
            "zone_fallback": {"entry": zone_fb_in, "exit": zone_fb_out},
        },
        "leg_zones": [
            {
                "zone_id": z["zone_id"],
                "origin_point": list(z["centroid"]),
                "reference_heading": round(z["reference_heading"], 1),
                "supporting_count": z["supporting_count"],
                "confidence": _label_confidence(z["supporting_count"]),
            }
            for z in entry_zones
        ],
        "exit_zones": [
            {
                "zone_id": z["zone_id"],
                "centroid": list(z["centroid"]),
                "supporting_count": z["supporting_count"],
            }
            for z in exit_zones
        ],
        "paths": [
            {
                "origin_zone_id": p["entry_zone_id"],
                "destination_zone_id": p["exit_zone_id"],
                "polyline": [list(pt) for pt in p["polyline"]],
                "supporting_count": p["supporting_count"],
                "movement_label": p["movement_label"],
            }
            for p in paths
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="path to video file")
    parser.add_argument("--sample-start", type=float, default=0.0,
                        help="sample window start, seconds into video")
    parser.add_argument("--sample-end", type=float, default=None,
                        help="sample window end (default = start + 15 min)")
    parser.add_argument("--out", default=None,
                        help="output JSON path (default: evaluations/auto_cal_<basename>.json)")
    parser.add_argument("--yolo-model", default=DEFAULT_YOLO_MODEL)
    parser.add_argument("--yolo-imgsz", type=int, default=DEFAULT_YOLO_IMGSZ)
    parser.add_argument("--yolo-conf",  type=float, default=DEFAULT_YOLO_CONF)
    parser.add_argument("--eps-px",     type=float, default=DBSCAN_EPS_PX)
    parser.add_argument("--min-samples", type=int, default=DBSCAN_MIN_SAMPLES)
    args = parser.parse_args()

    sample_end = (args.sample_end if args.sample_end is not None
                  else args.sample_start + DEFAULT_SAMPLE_SECONDS)
    out_path = Path(args.out) if args.out else (
        Path("evaluations") / f"auto_cal_{Path(args.video).stem}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result = run(
        args.video, args.sample_start, sample_end,
        yolo_model=args.yolo_model, yolo_imgsz=args.yolo_imgsz,
        yolo_confidence=args.yolo_conf,
        eps_px=args.eps_px, min_samples=args.min_samples,
    )
    out_path.write_text(json.dumps(result, indent=2))
    print(f"wrote {out_path}")
    print(f"  trajectories kept: {result['stats']['trajectories_kept']} / "
          f"{result['stats']['trajectories_raw']}")
    print(f"  leg zones: {len(result['leg_zones'])}, "
          f"exit zones: {len(result['exit_zones'])}, "
          f"paths: {len(result['paths'])}")
    print(f"  wall time: {result['stats']['wall_seconds']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
