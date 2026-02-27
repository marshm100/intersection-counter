"""Main video processing pipeline.

Orchestrates: preprocess → detect → track → origin crossing →
trajectory building → finalization → database write.
"""

import json
import logging
import pickle
import threading
import time
from datetime import datetime, timedelta

import cv2

from backend.config import CHECKPOINT_INTERVAL_SECONDS
from backend.services.checkpoint import CheckpointManager
from backend.services.classifier import classify_vehicle
from backend.services.detector import VehicleDetector
from backend.services.origin_detector import crossing_direction, did_cross_line
from backend.services.preprocessor import AdaptivePreprocessor
from backend.services.tracker import VehicleTracker
from backend.services.trajectory_classifier import classify_trajectory

logger = logging.getLogger(__name__)


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
    ):
        self.project_id = project_id
        self.db_path = db_path
        self.video_path = video_path
        self.legs = legs
        self.fps = fps
        self.video_start_time = video_start_time

        # Parse origin zones from legs
        self.origin_zones: list[list[list[float]]] = []
        for leg in legs:
            zone = leg["origin_zone"]
            if isinstance(zone, str):
                zone = json.loads(zone)
            self.origin_zones.append(zone)

        # Components (lazy-loaded to avoid loading YOLO in tests)
        self._detector: VehicleDetector | None = None
        self._tracker: VehicleTracker | None = None
        self._preprocessor: AdaptivePreprocessor | None = None
        self._checkpoint_mgr = CheckpointManager(db_path)

        # Tracking state: track_id → vehicle info dict
        self.active_vehicles: dict[int, dict] = {}

        # Counters
        self.vehicle_count = 0
        self.pedestrian_count = 0
        self.error_count = 0

        # Control
        self.pause_requested = threading.Event()
        self.is_running = False

    # -- Lazy component properties -----------------------------------------

    @property
    def detector(self) -> VehicleDetector:
        if self._detector is None:
            self._detector = VehicleDetector()
        return self._detector

    @property
    def tracker(self) -> VehicleTracker:
        if self._tracker is None:
            self._tracker = VehicleTracker(frame_rate=int(self.fps))
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
        callback=None,
    ):
        """Process the video file frame by frame."""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.video_path}")

        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.is_running = True
            frame_number = 0
            last_checkpoint_video_time = 0.0
            frames_processed = 0
            start_time = time.time()

            if start_frame > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                frame_number = start_frame

            while self.is_running:
                if self.pause_requested.is_set():
                    self._save_checkpoint(frame_number, frame_number / self.fps)
                    self.is_running = False
                    break

                ret, frame = cap.read()
                if not ret:
                    break

                if frame_number % frame_skip == 0:
                    try:
                        self._process_single_frame(frame, frame_number)
                        frames_processed += 1
                    except Exception as e:
                        logger.error("Error processing frame %d: %s", frame_number, e)
                        self.error_count += 1

                    video_time = frame_number / self.fps
                    if video_time - last_checkpoint_video_time >= CHECKPOINT_INTERVAL_SECONDS:
                        self._save_checkpoint(frame_number, video_time)
                        last_checkpoint_video_time = video_time

                    if callback and frames_processed % 10 == 0:
                        elapsed = time.time() - start_time
                        fps_proc = frames_processed / elapsed if elapsed > 0 else 0
                        eta = (
                            (total_frames - frame_number) / (fps_proc * frame_skip)
                            if fps_proc > 0
                            else 0
                        )
                        callback({
                            "frame_number": frame_number,
                            "total_frames": total_frames,
                            "progress_pct": (
                                frame_number / total_frames * 100
                                if total_frames > 0
                                else 0
                            ),
                            "timestamp_video": frame_number / self.fps,
                            "vehicle_count": self.vehicle_count,
                            "pedestrian_count": self.pedestrian_count,
                            "fps_processing": fps_proc,
                            "error_count": self.error_count,
                            "eta_seconds": eta,
                        })

                frame_number += 1

            self._finalize_all_active()
            self._save_checkpoint(frame_number, frame_number / self.fps)

        finally:
            cap.release()
            self.is_running = False

    # -- Per-frame processing ----------------------------------------------

    def _process_single_frame(self, frame, frame_number: int):
        processed = self.preprocessor.preprocess(frame)
        detections = self.detector.detect(processed)
        tracked = self.tracker.update(detections, frame_number)

        current_track_ids = {t["track_id"] for t in tracked}

        for t in tracked:
            if t["is_vehicle"]:
                self._process_vehicle(t["track_id"], t, frame_number)

        lost_ids = set(self.active_vehicles.keys()) - current_track_ids
        for track_id in lost_ids:
            self._finalize_vehicle(track_id, frame_number)

    def _process_vehicle(self, track_id: int, detection: dict, frame_number: int):
        center = tuple(detection["center"])

        if track_id not in self.active_vehicles:
            self.active_vehicles[track_id] = {
                "origin_leg_id": None,
                "reference_heading": None,
                "origin_frame": None,
                "trajectory": [],
                "confidences": [],
                "last_center": None,
                "class_id": detection["class_id"],
                "class_name": detection["class_name"],
                "bbox_width": detection["bbox_width"],
                "bbox_height": detection["bbox_height"],
                "bbox_area": detection["bbox_area"],
            }

        vehicle = self.active_vehicles[track_id]
        prev_center = vehicle["last_center"]
        vehicle["last_center"] = center
        vehicle["confidences"].append(detection["confidence"])
        vehicle["bbox_width"] = detection["bbox_width"]
        vehicle["bbox_height"] = detection["bbox_height"]
        vehicle["bbox_area"] = detection["bbox_area"]

        if vehicle["origin_leg_id"] is None:
            if prev_center is not None:
                self._check_origin_crossing(
                    track_id, prev_center, center, frame_number
                )
        else:
            vehicle["trajectory"].append(center)

    def _check_origin_crossing(
        self,
        track_id: int,
        prev_center: tuple,
        curr_center: tuple,
        frame_number: int,
    ):
        for i, zone in enumerate(self.origin_zones):
            line_start = tuple(zone[0])
            line_end = tuple(zone[1])

            if did_cross_line(prev_center, curr_center, line_start, line_end):
                direction = crossing_direction(
                    prev_center, curr_center, line_start, line_end
                )
                if direction == "enter":
                    leg = self.legs[i]
                    vehicle = self.active_vehicles[track_id]
                    vehicle["origin_leg_id"] = leg["leg_id"]
                    vehicle["reference_heading"] = leg["reference_heading"]
                    vehicle["origin_frame"] = frame_number
                    vehicle["trajectory"].append(curr_center)
                    return

    # -- Finalization ------------------------------------------------------

    def _finalize_vehicle(self, track_id: int, frame_number: int):
        if track_id not in self.active_vehicles:
            return

        vehicle = self.active_vehicles.pop(track_id)

        if vehicle["origin_leg_id"] is None:
            return

        trajectory = vehicle["trajectory"]
        if not trajectory:
            return

        classification = classify_trajectory(
            trajectory, vehicle["reference_heading"]
        )

        if classification["movement"] == "insufficient_data":
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

        self._write_vehicle_event(
            track_id=track_id,
            origin_leg_id=vehicle["origin_leg_id"],
            movement=classification["movement"],
            trajectory_data=json.dumps(trajectory),
            trajectory_confidence=classification["confidence"],
            vehicle_class=vehicle_class["simplified_class"] or "unknown",
            fhwa_class=vehicle_class["fhwa_class"],
            detection_confidence=avg_conf,
            timestamp_video=timestamp_video,
            timestamp_real=timestamp_real,
            frame_number=frame_number,
        )

        self.vehicle_count += 1

    def _finalize_all_active(self):
        """Finalize all remaining active vehicles (end of video or pause)."""
        for track_id in list(self.active_vehicles.keys()):
            self._finalize_vehicle(track_id, -1)

    # -- Database writes ---------------------------------------------------

    def _write_vehicle_event(self, **kwargs):
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(
                """INSERT INTO vehicle_events
                   (vehicle_track_id, origin_leg_id, movement, trajectory_data,
                    trajectory_confidence, vehicle_class, fhwa_class,
                    detection_confidence, timestamp_video, timestamp_real,
                    frame_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
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
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # -- Checkpoint --------------------------------------------------------

    def _save_checkpoint(self, frame_number: int, video_time: float):
        try:
            tracker_state = self.tracker.get_state() if self._tracker else b""
            active_traj = pickle.dumps(self.active_vehicles)
            self._checkpoint_mgr.save_checkpoint(
                frame_number=frame_number,
                timestamp_video=video_time,
                tracker_state=tracker_state,
                active_trajectories=active_traj,
                vehicle_count=self.vehicle_count,
                pedestrian_count=self.pedestrian_count,
                error_count=self.error_count,
            )
        except Exception as e:
            logger.error("Checkpoint save failed: %s", e)

    def pause(self):
        """Signal the processing loop to pause."""
        self.pause_requested.set()

    def resume_from_checkpoint(self) -> int:
        """Load checkpoint and restore state. Returns start_frame or 0."""
        checkpoint = self._checkpoint_mgr.load_checkpoint()
        if checkpoint is None:
            return 0

        self.vehicle_count = checkpoint["vehicle_count"]
        self.pedestrian_count = checkpoint["pedestrian_count"]
        self.error_count = checkpoint["error_count"]

        if checkpoint["tracker_state"] and self._tracker is not None:
            try:
                self.tracker.load_state(checkpoint["tracker_state"])
            except Exception as e:
                logger.warning("Could not restore tracker state: %s", e)

        if checkpoint["active_trajectories"]:
            try:
                self.active_vehicles = pickle.loads(  # noqa: S301
                    checkpoint["active_trajectories"]
                )
            except Exception as e:
                logger.warning("Could not restore trajectories: %s", e)
                self.active_vehicles = {}

        overlap_frames = int(60 * self.fps)
        start_frame = max(0, checkpoint["frame_number"] - overlap_frames)
        return start_frame
