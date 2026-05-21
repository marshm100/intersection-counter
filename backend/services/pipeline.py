"""Main video processing pipeline.

Orchestrates: preprocess → detect → track → origin assignment →
trajectory building → finalization → database write.
"""

import json
import logging
import math
import pickle
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import cv2

from backend.config import (
    CHECKPOINT_INTERVAL_SECONDS,
    ORIGIN_ASSIGN_MIN_FRAMES,
    TRACK_FINALIZE_GAP_FRAMES,
    TRAJECTORY_MIN_DISTANCE_PX,
)
from backend.services.checkpoint import CheckpointManager
from backend.services.classifier import classify_vehicle
from backend.services.detector import VehicleDetector
from backend.services.origin_detector import (
    closest_zone, crossing_direction, did_cross_line, tripwire_from_point,
)
from backend.services.preprocessor import AdaptivePreprocessor
from backend.services.tracker import VehicleTracker
from backend.services.trajectory_classifier import (
    classify_trajectory, derive_movement, score_destination_leg,
)

logger = logging.getLogger(__name__)

# Exceptions that indicate unrecoverable system-level failures.
# These must NOT be swallowed by the per-frame error handler.
_FATAL_ERRORS = (MemoryError, OSError, SystemExit)

MAX_CONSECUTIVE_ERRORS = 50


class ProcessingPipeline:
    """Orchestrates video processing from frames to vehicle events."""

    def __init__(
        self,
        project_id: str,
        db_path: str,
        video_path: str,
        legs: list[dict],
        fps: float,
        video_start_time: str | None = None,
        video_id: int | None = None,
        # Per-mode detector overrides. None = use config defaults (accurate).
        yolo_model: str | None = None,
        yolo_imgsz: int | None = None,
        yolo_confidence: float | None = None,
        # Detect on every Nth frame. detection_skip=1 = current behavior
        # (every frame); detection_skip=3 = fast mode (Kalman in between).
        detection_skip: int = 1,
        # Per-mode tracker overrides. None = use config defaults
        # (strict ByteTrack). Fast mode loosens these because Kalman
        # under-predicts motion when detection_skip>1.
        tracker_match_threshold: float | None = None,
        tracker_activation_threshold: float | None = None,
    ):
        self.project_id = project_id
        self.db_path = db_path
        self.video_path = video_path
        self.legs = legs
        self.fps = fps
        self.video_start_time = video_start_time
        # video_id is set when the pipeline is part of a multi-video run;
        # None means single-video legacy mode (events written with NULL video_id).
        self.video_id = video_id
        # Mode-driven detector config. The factory pulls defaults from
        # config.py when these are None, so accurate mode keeps current
        # behavior even without passing the args.
        self._yolo_model = yolo_model
        self._yolo_imgsz = yolo_imgsz
        self._yolo_confidence = yolo_confidence
        self.detection_skip = max(1, int(detection_skip))
        self._tracker_match_threshold = tracker_match_threshold
        self._tracker_activation_threshold = tracker_activation_threshold

        # Components (lazy-loaded to avoid loading YOLO in tests)
        self._detector: VehicleDetector | None = None
        self._tracker: VehicleTracker | None = None
        self._preprocessor: AdaptivePreprocessor | None = None
        self._checkpoint_mgr = CheckpointManager(db_path)

        # Tracking state: track_id → vehicle info dict
        self.active_vehicles: dict[int, dict] = {}

        # Latest tracked detections for frame preview
        self._latest_tracks: list[dict] = []

        # Recently finalized vehicles for trajectory visualization
        self._recently_finalized: list[dict] = []

        # Counters
        self.vehicle_count = 0
        self.error_count = 0
        self.turn_counts: dict[int, dict[str, int]] = {
            leg["leg_id"]: {"through": 0, "left": 0, "right": 0, "uturn": 0}
            for leg in self.legs
        }
        self.n_tracks_total: int = 0
        self.n_crossed_enter: int = 0    # vehicles assigned to a node
        self.n_crossed_exit: int = 0     # no node matched (diff > 90°)
        self.n_insufficient_data: int = 0

        # Frame skip used during current process_video call (updates tracker frame_rate)
        self._frame_skip: int = 1

        # Control
        self.pause_requested = threading.Event()
        self.is_running = False

    # -- Lazy component properties -----------------------------------------

    @property
    def detector(self) -> VehicleDetector:
        if self._detector is None:
            self._detector = VehicleDetector(
                model_path=self._yolo_model,
                imgsz=self._yolo_imgsz,
                confidence=self._yolo_confidence,
            )
        return self._detector

    @property
    def tracker(self) -> VehicleTracker:
        if self._tracker is None:
            # Tracker's frame_rate should reflect how often it actually
            # receives detections — not the source video's fps. In fast
            # mode we detect every 3rd frame, so the tracker sees an
            # effective 10 fps when the source is 30.
            effective_fps = max(1, int(self.fps / self.detection_skip))
            kw: dict = {"frame_rate": effective_fps}
            if self._tracker_match_threshold is not None:
                kw["minimum_matching_threshold"] = self._tracker_match_threshold
            if self._tracker_activation_threshold is not None:
                kw["track_activation_threshold"] = self._tracker_activation_threshold
            self._tracker = VehicleTracker(**kw)
        return self._tracker

    @property
    def preprocessor(self) -> AdaptivePreprocessor:
        if self._preprocessor is None:
            self._preprocessor = AdaptivePreprocessor()
        return self._preprocessor

    # -- Main processing loop ----------------------------------------------

    def process_video(
        self,
        frame_skip: int = 3,
        start_frame: int = 0,
        end_frame: int | None = None,
        callback=None,
    ):
        """Process the video file frame by frame.

        end_frame: stop before this frame number (exclusive). None = process to end.
        """
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.video_path}")

        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            effective_end = end_frame if end_frame is not None else total_frames
            range_total = max(1, effective_end - start_frame)
            self._frame_skip = frame_skip

            self.is_running = True
            frame_number = 0
            last_checkpoint_video_time = 0.0
            frames_processed = 0
            consecutive_errors = 0
            start_time = time.time()

            if start_frame > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                frame_number = start_frame

            while self.is_running:
                if self.pause_requested.is_set():
                    self._save_checkpoint(frame_number, frame_number / self.fps)
                    self.is_running = False
                    break

                if end_frame is not None and frame_number >= end_frame:
                    break

                ret, frame = cap.read()
                if not ret:
                    break

                # detection_skip=1 → run detection on every frame (accurate
                # mode, current behavior). detection_skip>1 → only every
                # Nth frame goes through YOLO + tracker; the tracker's
                # Kalman filter handles interpolation on the others.
                # We still cap.read() every frame so the video reader
                # doesn't drift relative to wall-clock progress reporting.
                run_detection = (frame_number % self.detection_skip == 0)
                if run_detection:
                    try:
                        self._process_single_frame(frame, frame_number)
                        frames_processed += 1
                        consecutive_errors = 0
                    except Exception as e:
                        if isinstance(e, _FATAL_ERRORS):
                            raise
                        if "CUDA out of memory" in str(e):
                            raise
                        logger.error("Error processing frame %d: %s", frame_number, e)
                        self.error_count += 1
                        consecutive_errors += 1
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            raise RuntimeError(
                                f"Pipeline aborted: {MAX_CONSECUTIVE_ERRORS} consecutive "
                                f"frame errors. Last error: {e}"
                            ) from e

                # Preview updates, checkpoints, and progress at preview_skip interval
                if frame_number % frame_skip == 0:
                    video_time = frame_number / self.fps
                    if video_time - last_checkpoint_video_time >= CHECKPOINT_INTERVAL_SECONDS:
                        self._save_checkpoint(frame_number, video_time)
                        last_checkpoint_video_time = video_time

                    if callback:
                        elapsed = time.time() - start_time
                        fps_proc = frames_processed / elapsed if elapsed > 0 else 0
                        remaining = effective_end - frame_number
                        eta = (
                            remaining / fps_proc
                            if fps_proc > 0
                            else 0
                        )
                        origin_zones = [leg.get("origin_zone", []) for leg in self.legs]
                        callback({
                            "frame_number": frame_number,
                            "total_frames": effective_end,
                            "progress_pct": (
                                (frame_number - start_frame) / range_total * 100
                            ),
                            "timestamp_video": frame_number / self.fps,
                            "vehicle_count": self.vehicle_count,
                            "fps_processing": fps_proc,
                            "error_count": self.error_count,
                            "eta_seconds": eta,
                            "turn_counts": {
                                str(leg["leg_id"]): {
                                    "label": leg["label"],
                                    "cardinal": leg.get("cardinal_direction", ""),
                                    "counts": dict(self.turn_counts[leg["leg_id"]])
                                }
                                for leg in self.legs
                            },
                            "n_tracks_total": self.n_tracks_total,
                            "n_crossed_enter": self.n_crossed_enter,
                            "n_crossed_exit": self.n_crossed_exit,
                            "n_insufficient_data": self.n_insufficient_data,
                            "raw_frame": frame.copy(),
                            "tracks": list(self._latest_tracks),
                            "origin_zones": origin_zones,
                            "active_trajectories": {
                                tid: {
                                    "trajectory": v["trajectory"],
                                    "origin_leg_id": v["origin_leg_id"],
                                    "tentative_movement": v.get("tentative_classification", {}).get("movement"),
                                    "tentative_confidence": v.get("tentative_classification", {}).get("confidence"),
                                }
                                for tid, v in self.active_vehicles.items()
                                if len(v["trajectory"]) >= 2
                            },
                            "finalized_trajectories": [
                                f for f in self._recently_finalized
                                if frame_number - f["finalized_frame"] < 60
                            ],
                        })

                frame_number += 1

            self._finalize_all_active(frame_number)
            self._save_checkpoint(frame_number, frame_number / self.fps)

        finally:
            cap.release()
            self.is_running = False

    # -- Per-frame processing ----------------------------------------------

    def _process_single_frame(self, frame, frame_number: int):
        processed = self.preprocessor.preprocess(frame)
        detections = self.detector.detect(processed)
        tracked = self.tracker.update(detections, frame_number)
        self._latest_tracks = tracked

        current_track_ids = {t["track_id"] for t in tracked}

        for t in tracked:
            if t["is_vehicle"]:
                self._process_vehicle(t["track_id"], t, frame_number)

        # Finalize only after a grace window of consecutive missed frames.
        # YOLO detection flickers (especially at imgsz=1280 with marginal
        # vehicles); bytetrack's lost_buffer can re-associate the same
        # track_id across the gap. If we finalize on the first missed
        # frame we fragment one real vehicle into many one-point "tracks"
        # that get silently dropped as insufficient_data.
        for track_id in list(self.active_vehicles.keys()):
            if track_id in current_track_ids:
                self.active_vehicles[track_id]["last_seen_frame"] = frame_number
                continue
            last = self.active_vehicles[track_id].get("last_seen_frame")
            if last is None:
                # First frame absence after creation — start the grace timer.
                self.active_vehicles[track_id]["last_seen_frame"] = frame_number
                continue
            if frame_number - last > TRACK_FINALIZE_GAP_FRAMES:
                self._finalize_vehicle(track_id, frame_number)

    def _process_vehicle(self, track_id: int, detection: dict, frame_number: int):
        center = tuple(detection["center"])

        if track_id not in self.active_vehicles:
            self.active_vehicles[track_id] = {
                "origin_leg_id": None,
                "reference_heading": None,
                "origin_frame": None,
                "origin_attempt_failed": False,
                "start_frame": frame_number,
                "last_seen_frame": frame_number,
                "trajectory": [],
                "confidences": [],
                "class_id": detection["class_id"],
                "class_name": detection["class_name"],
                "bbox_width": detection["bbox_width"],
                "bbox_height": detection["bbox_height"],
                "bbox_area": detection["bbox_area"],
                "initial_bbox_ratio": detection["bbox_width"] / max(detection["bbox_height"], 1),
            }
            self.n_tracks_total += 1

        vehicle = self.active_vehicles[track_id]
        vehicle["trajectory"].append(center)
        vehicle["confidences"].append(detection["confidence"])
        vehicle["bbox_width"] = detection["bbox_width"]
        vehicle["bbox_height"] = detection["bbox_height"]
        vehicle["bbox_area"] = detection["bbox_area"]

        if vehicle["origin_leg_id"] is None:
            n_pts = len(vehicle["trajectory"])
            # Attempt origin assignment on every frame once we have enough
            # trajectory points. Previously throttled to n_pts % 3 == 0,
            # which meant 2-point trajectories (vehicle detected once,
            # missed, redetected once) never even attempted assignment —
            # the vehicle got silently dropped as insufficient_data.
            if n_pts >= ORIGIN_ASSIGN_MIN_FRAMES:
                self._assign_origin(track_id, frame_number)

    def _assign_origin(self, track_id: int, frame_number: int):
        vehicle = self.active_vehicles[track_id]
        traj = vehicle["trajectory"]

        # --- Spatial check: did the trajectory cross any origin zone line? ---
        # v3 calibration stores a single origin point per leg; we synthesize a
        # perpendicular tripwire through it on the fly so the line-crossing
        # logic still works. Legacy v2 zones (2-point lines) pass through unchanged.
        for leg in self.legs:
            zone = leg.get("origin_zone")
            if not zone:
                continue
            if len(zone) == 1:
                ref = leg.get("reference_heading")
                if ref is None:
                    continue
                line_start, line_end = tripwire_from_point(zone[0], ref)
            elif len(zone) >= 2:
                line_start = tuple(zone[0])
                line_end = tuple(zone[1])
            else:
                continue
            for i in range(1, len(traj)):
                if did_cross_line(traj[i - 1], traj[i], line_start, line_end):
                    direction = crossing_direction(
                        traj[i - 1], traj[i], line_start, line_end,
                        reference_heading=leg.get("reference_heading"),
                    )
                    if direction == "enter":
                        vehicle["origin_leg_id"] = leg["leg_id"]
                        vehicle["reference_heading"] = leg["reference_heading"]
                        vehicle["origin_frame"] = frame_number
                        self.n_crossed_enter += 1
                        return

        # --- Fallback: heading-based matching ---
        # Use the FULL trajectory so far, not just the first 2 points: a
        # slow-starting vehicle (turner pulling away from a stop) may have
        # <8 px between the first two centers but plenty of displacement
        # by the time we re-attempt assignment.
        start = traj[0]
        end = traj[-1]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        displacement = math.sqrt(dx * dx + dy * dy)
        if displacement < TRAJECTORY_MIN_DISTANCE_PX:
            return  # Too close — heading would be noise

        movement_heading = math.degrees(math.atan2(dx, -dy)) % 360

        best_idx = None
        best_diff = float("inf")
        for i, leg in enumerate(self.legs):
            ref = leg.get("reference_heading")
            if ref is None:
                continue
            diff = abs((movement_heading - ref + 180) % 360 - 180)
            if diff < best_diff:
                best_diff = diff
                best_idx = i

        if best_idx is not None and best_diff <= 90:
            leg = self.legs[best_idx]
            vehicle["origin_leg_id"] = leg["leg_id"]
            vehicle["reference_heading"] = leg["reference_heading"]
            vehicle["origin_frame"] = frame_number
            self.n_crossed_enter += 1
        else:
            if not vehicle.get("origin_attempt_failed"):
                self.n_crossed_exit += 1
                vehicle["origin_attempt_failed"] = True

    # -- Finalization ------------------------------------------------------

    def _finalize_vehicle(self, track_id: int, frame_number: int):
        if track_id not in self.active_vehicles:
            return
        vehicle = self.active_vehicles.pop(track_id)
        self._finalize_vehicle_data(track_id, vehicle, frame_number)

    def _finalize_vehicle_data(self, track_id: int, vehicle: dict, frame_number: int):
        """Finalize a vehicle dict (from active_vehicles or recently_lost)."""
        if vehicle["origin_leg_id"] is None:
            n_pts = len(vehicle.get("trajectory", []))
            if n_pts >= ORIGIN_ASSIGN_MIN_FRAMES:
                self.n_insufficient_data += 1
                logger.debug(
                    "Track %d discarded: no origin assigned (%d points)",
                    track_id, n_pts,
                )
            return

        trajectory = vehicle["trajectory"]
        if not trajectory:
            return

        classification = classify_trajectory(
            trajectory, vehicle["reference_heading"]
        )

        logger.debug(
            "Track %d classification: %s (heading_change=%.1f, straightness=%.2f, "
            "distance=%.1f, points=%d, ref_heading=%.1f)",
            track_id, classification["movement"],
            classification["net_heading_change"],
            classification["path_straightness"],
            classification["path_distance"],
            classification["num_points"],
            vehicle.get("reference_heading", 0) or 0,
        )

        if classification["movement"] == "insufficient_data":
            self.n_insufficient_data += 1
            return

        origin_leg_id = vehicle["origin_leg_id"]
        # Destination-based classification (bug #5 fix). Score every leg —
        # including the origin (for u-turn detection) — by how well the
        # trajectory's exit heading + exit position align with the
        # leg-from-center direction. Movement type is derived from the
        # (origin, destination) reference-heading geometry — no hardcoded
        # turn matrix, just a delta-angle bucket.
        origin_leg = next(
            (lg for lg in self.legs if lg["leg_id"] == origin_leg_id), None,
        )
        dest_result = score_destination_leg(
            trajectory, origin_leg_id, self.legs,
        )
        destination_leg_id = dest_result["destination_leg_id"]
        destination_leg = next(
            (lg for lg in self.legs if lg["leg_id"] == destination_leg_id), None,
        )
        movement = (
            derive_movement(origin_leg, destination_leg, all_legs=self.legs)
            if origin_leg else "insufficient_data"
        )
        # Fall through to insufficient_data path if derivation couldn't
        # produce a turn label (no origin leg found, no destination, etc.).
        if movement == "insufficient_data":
            self.n_insufficient_data += 1
            return

        avg_conf = (
            sum(vehicle["confidences"]) / len(vehicle["confidences"])
            if vehicle["confidences"]
            else 0
        )

        vehicle_class = classify_vehicle(
            vehicle["class_id"],
            vehicle["bbox_width"],
            vehicle["bbox_height"],
            vehicle["bbox_area"],
            avg_conf,
        )

        timestamp_video = frame_number / self.fps

        timestamp_real = None
        if self.video_start_time:
            try:
                start = datetime.fromisoformat(self.video_start_time)
                timestamp_real = (
                    start + timedelta(seconds=timestamp_video)
                ).isoformat()
            except (ValueError, TypeError):
                pass
        if origin_leg_id in self.turn_counts:
            leg_counts = self.turn_counts[origin_leg_id]
            if movement in leg_counts:
                leg_counts[movement] += 1

        # Posterior over all candidate legs — serialised JSON so review
        # tools can re-pick a destination without re-running the pipeline.
        # Keys are stringified ints since JSON object keys must be strings.
        posterior_json = json.dumps({
            str(lid): round(p, 4)
            for lid, p in dest_result.get("posterior", {}).items()
        }) if dest_result.get("posterior") else None

        self._write_vehicle_event(
            track_id=track_id,
            origin_leg_id=vehicle["origin_leg_id"],
            movement=movement,
            trajectory_data=json.dumps(trajectory),
            trajectory_confidence=classification["confidence"],
            vehicle_class=vehicle_class["simplified_class"] or "unknown",
            fhwa_class=vehicle_class["fhwa_class"],
            detection_confidence=avg_conf,
            timestamp_video=timestamp_video,
            timestamp_real=timestamp_real,
            frame_number=frame_number,
            start_frame=vehicle.get("start_frame", 0),
            # Persist the classifier's decision factors so a misclassified
            # turn can be audited (and the classifier retuned) without
            # re-running detection. See backend/database.py classifier_*
            # columns and bug #5 Phase A.
            classifier_net_heading_change=classification.get("net_heading_change"),
            classifier_cumulative_curvature=classification.get("cumulative_curvature"),
            classifier_path_straightness=classification.get("path_straightness"),
            classifier_path_distance=classification.get("path_distance"),
            classifier_num_points=classification.get("num_points"),
            # Phase B: destination-leg + posterior.
            destination_leg_id=destination_leg_id,
            destination_confidence=dest_result.get("confidence"),
            destination_posterior_json=posterior_json,
        )

        self.vehicle_count += 1

        # Buffer for trajectory visualization
        self._recently_finalized.append({
            "trajectory": trajectory,
            "movement": movement,
            "origin_leg_id": origin_leg_id,
            "finalized_frame": frame_number,
        })
        if len(self._recently_finalized) > 20:
            self._recently_finalized = self._recently_finalized[-20:]

    def _finalize_all_active(self, frame_number: int):
        """Finalize all remaining active vehicles."""
        for track_id in list(self.active_vehicles.keys()):
            self._finalize_vehicle(track_id, frame_number)

    # -- Database writes ---------------------------------------------------

    def _write_vehicle_event(self, **kwargs):
        # When the v3 orchestrator drives this pipeline it pre-stashes the
        # owning camera + trim on the instance so we can persist them
        # inline. Writing the IDs at insert time (rather than backfilling
        # at end of segment) is what makes events visible to the live
        # aggregator while processing is still running.
        camera_id = getattr(self, "_v3_camera_id", None)
        trim_id = getattr(self, "_v3_trim_id", None)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(
                """INSERT INTO vehicle_events
                   (video_id, camera_id, trim_id,
                    vehicle_track_id, origin_leg_id, movement,
                    trajectory_data, trajectory_confidence, vehicle_class,
                    fhwa_class, detection_confidence, timestamp_video,
                    timestamp_real, frame_number, start_frame,
                    classifier_net_heading_change,
                    classifier_cumulative_curvature,
                    classifier_path_straightness,
                    classifier_path_distance,
                    classifier_num_points,
                    destination_leg_id,
                    destination_confidence,
                    destination_posterior_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?,
                           ?, ?, ?)""",
                (
                    self.video_id,
                    camera_id,
                    trim_id,
                    kwargs["track_id"],
                    kwargs["origin_leg_id"],
                    kwargs["movement"],
                    kwargs["trajectory_data"],
                    kwargs["trajectory_confidence"],
                    kwargs["vehicle_class"],
                    kwargs["fhwa_class"],
                    kwargs["detection_confidence"],
                    kwargs["timestamp_video"],
                    kwargs["timestamp_real"],
                    kwargs["frame_number"],
                    kwargs.get("start_frame", 0),
                    kwargs.get("classifier_net_heading_change"),
                    kwargs.get("classifier_cumulative_curvature"),
                    kwargs.get("classifier_path_straightness"),
                    kwargs.get("classifier_path_distance"),
                    kwargs.get("classifier_num_points"),
                    kwargs.get("destination_leg_id"),
                    kwargs.get("destination_confidence"),
                    kwargs.get("destination_posterior_json"),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # -- Checkpoint --------------------------------------------------------

    def _save_checkpoint(self, frame_number: int, video_time: float):
        try:
            tracker_state = self.tracker.get_state() if self._tracker else b""
            active_traj = pickle.dumps({
                "active_vehicles": self.active_vehicles,
            })
            self._checkpoint_mgr.save_checkpoint(
                frame_number=frame_number,
                timestamp_video=video_time,
                tracker_state=tracker_state,
                active_trajectories=active_traj,
                vehicle_count=self.vehicle_count,
                error_count=self.error_count,
                current_video_id=self.video_id,
                current_camera_id=getattr(self, "_v3_camera_id", None),
                current_trim_id=getattr(self, "_v3_trim_id", None),
            )
        except Exception as e:
            logger.error("Checkpoint save failed: %s", e)

    def pause(self):
        """Signal the processing loop to pause."""
        self.pause_requested.set()

    def resume_from_checkpoint(self, start_frame_floor: int = 0) -> int:
        """Load checkpoint and restore state. Returns start_frame.

        start_frame_floor: minimum frame to resume from. The 60-second
        rewind that prevents losing in-flight tracks can otherwise dip
        below the current segment's start_frame — in v3 a single video
        can host multiple segments, and rewinding past the segment
        boundary would (a) reprocess and double-count the prior segment
        and (b) make the overlap DELETE wipe that prior segment's events.
        """
        checkpoint = self._checkpoint_mgr.load_checkpoint()
        if checkpoint is None:
            return max(0, start_frame_floor)

        self.vehicle_count = checkpoint["vehicle_count"]
        self.error_count = checkpoint["error_count"]

        if checkpoint["tracker_state"]:
            try:
                self.tracker.load_state(checkpoint["tracker_state"])
            except Exception as e:
                logger.warning("Could not restore tracker state: %s", e)

        if checkpoint["active_trajectories"]:
            try:
                data = pickle.loads(  # noqa: S301
                    checkpoint["active_trajectories"]
                )
                if isinstance(data, dict) and "active_vehicles" in data:
                    self.active_vehicles = data["active_vehicles"]
                else:
                    # Legacy format: plain active_vehicles dict
                    self.active_vehicles = data
            except Exception as e:
                logger.warning("Could not restore trajectories: %s", e)
                self.active_vehicles = {}

        overlap_frames = int(60 * self.fps)
        raw_start = max(0, checkpoint["frame_number"] - overlap_frames)
        start_frame = max(start_frame_floor, raw_start)

        # Delete events in the overlap region to prevent duplicates on resume.
        # Scoped to the current video AND >= start_frame (which honours the
        # floor) so resuming segment N doesn't wipe segment N-1's events.
        conn = sqlite3.connect(self.db_path)
        if self.video_id is not None:
            conn.execute(
                "DELETE FROM vehicle_events WHERE video_id = ? AND frame_number >= ?",
                (self.video_id, start_frame),
            )
        else:
            conn.execute(
                "DELETE FROM vehicle_events WHERE video_id IS NULL AND frame_number >= ?",
                (start_frame,),
            )
        conn.commit()
        conn.close()

        return start_frame
