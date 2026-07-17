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
    ENTRY_TIEBREAK_COLLINEAR_PX,
    ENTRY_TIEBREAK_DECISIVE_PX,
    NATIVE_ARTICULATED_CLASS_ID,
    NATIVE_ARTICULATED_MIN_FRAMES,
    ENTRY_TIEBREAK_ENABLED,
    ENTRY_TIEBREAK_EXIT_PX,
    ENTRY_TIEBREAK_MIN_ENTRY_SEP_PX,
    HEADING_FALLBACK_EXCLUDE_LABEL_KEYWORDS,
    JOINT_SCORER_COST_METRIC,
    JOINT_SCORER_COVERAGE_WEIGHT,
    JOINT_SCORER_MAX_COST_PX,
    JOINT_SCORER_MIN_COVERAGE_FRAC,
    JOINT_SCORER_TAIL_WEIGHT,
    JOINT_SCORER_TAIL_WINDOW,
    JOINT_SCORER_TURN_MIN_COVERAGE,
    JOINT_SCORER_TURN_TAIL_PRIOR_FLOOR,
    ORIGIN_ASSIGN_MIN_FRAMES,
    ORIGIN_REWRITE_GATE_ENABLED,
    ORIGIN_REWRITE_GATE_STRAIGHTNESS,
    PRE_TRACK_NMS_IOU,
    SPEED_TIEBREAK_DECISIVE,
    SPEED_TIEBREAK_ENABLED,
    SPEED_TIEBREAK_MIN_SEP,
    TRACK_FINALIZE_GAP_FRAMES,
    TRAJECTORY_MIN_DISTANCE_PX,
    ORIGIN_EVIDENCE_GATE_ENABLED,
    ORIGIN_POSTERIOR_ENABLED,
    ORIGIN_POSTERIOR_MARGIN_FLOOR,
    DEST_TIE_BAND,
    USE_JOINT_PARTIAL_FRECHET_SCORER,
)
from backend.services.checkpoint import CheckpointManager
from backend.services.classifier import classify_vehicle
from backend.services.detector import VehicleDetector
from backend.services.origin_detector import (
    closest_zone, crossing_direction, did_cross_line,
    score_origin_by_polyline, tripwire_from_point,
)
from backend.services.posterior import margin_from_json, posterior_margin
from backend.services import partial_evidence
from backend.services.preprocessor import AdaptivePreprocessor
from backend.services.track_filter import track_quality
from backend.services.tracker import VehicleTracker
from backend.services.trajectory_classifier import (
    classify_trajectory, derive_movement, score_destination_by_polyline,
    score_destination_leg, score_path_joint,
)

logger = logging.getLogger(__name__)

# Exceptions that indicate unrecoverable system-level failures.
# These must NOT be swallowed by the per-frame error handler.
_FATAL_ERRORS = (MemoryError, OSError, SystemExit)

MAX_CONSECUTIVE_ERRORS = 50


def _buffer_detection_bbox(d: dict, scale: float) -> dict:
    """Scale a detection's bbox by `scale` around its center (buffered-IoU,
    Phase 1.3). Inflating BOTH detections and (transitively) the tracks built
    from them widens the IoU association basin so fast vehicles whose
    consecutive boxes don't overlap at 10 fps still match — the C-BIoU idea
    (arXiv 2211.14317) without patching tracker internals. Centers are
    unchanged, so trajectories (built from centers) are unaffected; stored
    bbox_width/height/area are inflated by `scale` for these runs."""
    x1, y1, x2, y2 = d["bbox"]
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    hw, hh = (x2 - x1) * scale / 2.0, (y2 - y1) * scale / 2.0
    out = dict(d)
    out["bbox"] = [cx - hw, cy - hh, cx + hw, cy + hh]
    out["bbox_width"] = hw * 2.0
    out["bbox_height"] = hh * 2.0
    out["bbox_area"] = hw * hh * 4.0
    return out


def _class_agnostic_nms(detections: list[dict], iou_thresh: float) -> list[dict]:
    """Greedy class-agnostic NMS: drop a lower-confidence detection that overlaps
    a kept one at IoU > iou_thresh, IGNORING class. The detector double-boxes one
    vehicle across classes (e.g. 'car' + 'truck'); YOLO's per-class NMS leaves
    those, and the tracker then assigns each box its own ID (parallel duplicate
    tracks). Collapsing them here, at the tracking input only, removes the
    duplicate IDs without touching the raw detection cache. See config
    PRE_TRACK_NMS_IOU."""
    order = sorted(detections, key=lambda d: -d.get("confidence", 0.0))
    kept: list[dict] = []
    for d in order:
        bx = d["bbox"]
        dup = False
        for k in kept:
            kb = k["bbox"]
            ix1, iy1 = max(bx[0], kb[0]), max(bx[1], kb[1])
            ix2, iy2 = min(bx[2], kb[2]), min(bx[3], kb[3])
            iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
            inter = iw * ih
            if inter <= 0:
                continue
            ua = ((bx[2]-bx[0])*(bx[3]-bx[1]) + (kb[2]-kb[0])*(kb[3]-kb[1]) - inter)
            if ua > 0 and inter / ua > iou_thresh:
                dup = True
                break
        if not dup:
            kept.append(d)
    return kept


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
        yolo_class_scheme: str = "coco",
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
        # Per-intersection calibration overrides. dict with keys
        # tripwire_half_length_px, trajectory_through_max_angle,
        # trajectory_turn_min_angle, trajectory_uturn_min_angle.
        # When None, the pipeline falls back to global config constants.
        # The router gets the effective values from database.get_calibration_params.
        calibration_params: dict | None = None,
        # Per-(origin,destination) road polylines for this camera. When
        # present, the pipeline tries polyline-based origin attribution
        # and destination scoring BEFORE the tripwire/heading/softmax
        # fallback paths. Each path is a dict with origin_leg_id,
        # destination_leg_id, polyline (list of [x,y]), movement_label,
        # supporting_count. List comes from
        # backend.database.list_paths_for_camera.
        paths: list[dict] | None = None,
        # Tracker backend: "bytetrack" (default, IoU-only) or "ocsort" (motion-
        # based, sustains turning vehicles through aspect change + short
        # detection gaps; needs boxmot). See backend/services/tracker.py.
        tracker_backend: str = "bytetrack",
        # Extra backend-specific constructor kwargs (e.g. OC-SORT use_byte,
        # det_thresh, inertia, min_hits). None = backend defaults. Threaded
        # verbatim to the backend so tracker behaviour can be tuned without
        # touching the call sites; ignored by backends that don't accept them.
        tracker_kwargs: dict | None = None,
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
        self._yolo_class_scheme = yolo_class_scheme
        self._yolo_imgsz = yolo_imgsz
        self._yolo_confidence = yolo_confidence
        self.detection_skip = max(1, int(detection_skip))
        self._tracker_match_threshold = tracker_match_threshold
        self._tracker_activation_threshold = tracker_activation_threshold
        self._calibration_params = calibration_params or {}
        self._paths: list[dict] = list(paths) if paths else []
        self._tracker_backend = tracker_backend
        self._tracker_kwargs = dict(tracker_kwargs) if tracker_kwargs else {}

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
        # Polyline-path tier counters (Phase 1). Track how often the new
        # polyline tier successfully attributes vs how often we fall
        # through to the legacy tripwire/heading/softmax tiers.
        self.n_origin_via_polyline: int = 0
        self.n_destination_via_polyline: int = 0
        # Snap-magnet defence: turn matches rejected because a straight (through)
        # track's origin was being rewritten to a non-nearest leg.
        self.n_origin_rewrite_gated: int = 0
        # Entry-tiebreak: shared-exit collinear matches whose origin was re-picked
        # by entry proximity (the cam2 SB<->EB swap fix). mdh cameras only.
        self.n_entry_tiebreak: int = 0
        # Speed-tiebreak: same cluster, re-picked by pixel-speed signature vs
        # each path's expected_speed (the entry retry). mdh cameras only.
        self.n_speed_tiebreak: int = 0
        # Low-confidence births rejected by the track-quality gate (Phase 1.1;
        # only counts when calibration_params["track_quality_filter"] is set).
        self.n_quality_filtered: int = 0
        # Origin-evidence gate (item-8 mechanism 1): entry-gate crossings bind
        # origin and filter the joint scorer's candidates. Counters instrument
        # the ablation (plan_origin_evidence_gate stage 3): how many tracks had
        # entry evidence vs not, and how often the evidence CORRECTED the early
        # entry-tangent origin (each correction is a prevented flip).
        self._entry_gates = None          # built lazily on first finalize
        self.n_origin_evidenced: int = 0
        self.n_origin_unevidenced: int = 0
        self.n_origin_corrected: int = 0
        # Partial-evidence posterior (mechanism 1, posterior half —
        # plan_posterior_half_2026-07-15): branch applications + how many
        # origin posteriors fell below the ambiguity floor (flag-bound).
        self.n_posterior_origin: int = 0     # branch 1: unevidenced origin
        self.n_posterior_dest: int = 0       # branch 2: truncated dest tie
        self.n_posterior_rescued: int = 0    # evidenced insufficient-rescue
        self.n_origin_ambiguous: int = 0     # origin margin < floor
        self.n_posterior_vetoed: int = 0     # branch-1 pools trimmed by the
                                             # straight-track turn veto
        # Inline track stitching (Phase 1.5, calibration_params["track_stitch"]):
        # new tracker IDs remapped onto a coasting prior track (ID-switch repair).
        self._stitch_alias: dict[int, int] = {}
        self.n_stitched: int = 0

        # Optional detection-cache write-through (Attribution v2, Step 1). When
        # set (a DetectionCacheWriter), every live detection frame is persisted
        # so later tracker/attribution experiments can retrack from cache in
        # minutes instead of re-decoding + re-inferring the whole video. None =
        # no caching (default; live behaviour unchanged).
        self._detection_cache_writer = None

        # Optional Step-0 detection audit (Attribution v2 P2.C). When _audit_mode
        # is True, _ingest_detections does a per-frame greedy IoU match between
        # the INPUT detections and the tracker's OUTPUT tracks so we can tell a
        # real YOLO hit from a Kalman-coasted track (supervision exposes no such
        # flag). Per-track stats land in _audit_records at finalization; a driver
        # collects them. Zero cost when off.
        self._audit_mode = False
        self._audit_tracks: dict[int, dict] = {}
        self._audit_records: list[dict] = []

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
                class_scheme=self._yolo_class_scheme,
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
            kw: dict = {"frame_rate": effective_fps, "backend": self._tracker_backend}
            # Standard tracker knobs (match/activation/lost-buffer) go through
            # VehicleTracker's EXPLICIT params, never backend_kwargs — passing
            # them in backend_kwargs collides with the forwarded explicit args
            # (duplicate keyword). Precedence: per-camera CALIBRATION OVERRIDE >
            # explicit constructor arg (mode default or a deliberate sweep) >
            # backend/config default. The override wins because callers routinely
            # pass the MODE DEFAULT as the explicit arg (mode_cfg's match=0.8); a
            # real per-camera tune must beat that. calibration_params carries the
            # raw override (None when unset), so an unset knob falls through to
            # the explicit arg and a sweep's deliberate value still applies.
            match_thr = self._calibration_params.get("tracker_match_threshold")
            if match_thr is None:
                match_thr = self._tracker_match_threshold
            if match_thr is not None:
                kw["minimum_matching_threshold"] = match_thr
            activation_thr = self._calibration_params.get("tracker_activation_threshold")
            if activation_thr is None:
                activation_thr = self._tracker_activation_threshold
            if activation_thr is not None:
                kw["track_activation_threshold"] = activation_thr
            lost_buffer = self._calibration_params.get("tracker_lost_buffer")
            if lost_buffer is not None:
                kw["lost_track_buffer"] = int(lost_buffer)
            backend_kwargs = dict(self._tracker_kwargs) if self._tracker_kwargs else {}
            # BoT-SORT's separate birth gate (Phase 1.1). Only botsort's ctor
            # accepts it; other backends use activation as their birth gate.
            ntt = self._calibration_params.get("new_track_thresh")
            if ntt is not None and self._tracker_backend == "botsort":
                backend_kwargs.setdefault("new_track_thresh", float(ntt))
            if backend_kwargs:
                kw["backend_kwargs"] = backend_kwargs
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
        # Write-through to the detection cache when enabled (records the raw
        # YOLO output for this frame before tracking consumes it).
        if self._detection_cache_writer is not None:
            self._detection_cache_writer.add(frame_number, detections)
        self._ingest_detections(detections, frame_number)

    def _ingest_detections(self, detections: list[dict], frame_number: int):
        """Feed a frame's detections through tracking + attribution.

        Split out from _process_single_frame so the identical logic can be
        driven from cached detections (process_cached) without re-decoding or
        re-inferring the video — the tracker/attribution path is agnostic to
        whether detections came live or from the Parquet cache.
        """
        # Per-camera NMS override (calibration) wins over the global default;
        # NULL/absent override falls back to the process-global PRE_TRACK_NMS_IOU.
        nms_iou = self._calibration_params.get("pre_track_nms_iou")
        if nms_iou is None:
            nms_iou = PRE_TRACK_NMS_IOU
        if nms_iou is not None and len(detections) > 1:
            detections = _class_agnostic_nms(detections, nms_iou)
        # Buffered-IoU (Phase 1.3): inflate boxes AFTER NMS (NMS must see real
        # geometry) and AFTER the cache write upstream (cache stays raw).
        buf_scale = self._calibration_params.get("bbox_buffer_scale")
        if buf_scale and float(buf_scale) != 1.0 and detections:
            detections = [_buffer_detection_bbox(d, float(buf_scale)) for d in detections]
        tracked = self.tracker.update(detections, frame_number)
        # Inline ID-switch repair (Phase 1.5): remap a NEW tracker ID onto a
        # track that has been coasting (unseen 2..gap frames) when the old
        # track's extrapolated motion predicts the new ID's position. The
        # trackers re-associate within their own lost buffers; this catches the
        # drop-and-respawn case where they hand out a fresh ID instead — which
        # the pipeline would otherwise count twice (one fragment each).
        if self._calibration_params.get("track_stitch"):
            tracked = self._stitch_remap(tracked, frame_number)
        self._latest_tracks = tracked

        if self._audit_mode:
            self._audit_update(detections, tracked, frame_number)

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

    # Stitching gates (Phase 1.5). A candidate prior track must have been
    # unseen for at least 2 frames (1-frame absence is normal flicker the
    # grace window already rides out) and at most the finalize gap (after
    # which it is already finalized). The position gate scales with how far
    # the prior track was moving — fast movers earn a wider basin.
    _STITCH_MIN_GAP = 2
    _STITCH_BASE_RADIUS_PX = 60.0
    _STITCH_SPEED_SLACK = 0.35   # + this fraction of (speed * gap)

    def _stitch_remap(self, tracked: list[dict], frame_number: int) -> list[dict]:
        from backend.config import TRACK_FINALIZE_GAP_FRAMES
        # 1) Apply existing aliases so a remapped ID stays remapped for life.
        for t in tracked:
            alias = self._stitch_alias.get(t["track_id"])
            if alias is not None:
                t["track_id"] = alias
        present = {t["track_id"] for t in tracked}
        # 2) For each genuinely NEW ID, look for a coasting prior track whose
        #    extrapolated position lands on it.
        for t in tracked:
            tid = t["track_id"]
            if tid in self.active_vehicles or not t["is_vehicle"]:
                continue
            cx, cy = t["center"]
            best_id, best_dist = None, None
            for vid, v in self.active_vehicles.items():
                if vid in present:
                    continue  # prior track still alive this frame
                last = v.get("last_seen_frame")
                traj = v["trajectory"]
                if last is None or len(traj) < 3:
                    continue
                gap = frame_number - last
                if not (self._STITCH_MIN_GAP <= gap <= TRACK_FINALIZE_GAP_FRAMES):
                    continue
                # velocity from the last few points (px/frame, assumes ~1 pt/frame)
                k = min(5, len(traj) - 1)
                vx = (traj[-1][0] - traj[-1 - k][0]) / k
                vy = (traj[-1][1] - traj[-1 - k][1]) / k
                px = traj[-1][0] + vx * gap
                py = traj[-1][1] + vy * gap
                speed = (vx * vx + vy * vy) ** 0.5
                gate = self._STITCH_BASE_RADIUS_PX + self._STITCH_SPEED_SLACK * speed * gap
                dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                if dist <= gate and (best_dist is None or dist < best_dist):
                    best_id, best_dist = vid, dist
            if best_id is not None:
                self._stitch_alias[t["track_id"]] = best_id
                t["track_id"] = best_id
                present.add(best_id)
                self.n_stitched += 1
        return tracked

    @staticmethod
    def _bbox_iou(a: list, b: list) -> float:
        """IoU of two [x1, y1, x2, y2] boxes."""
        ix1 = max(a[0], b[0]); iy1 = max(a[1], b[1])
        ix2 = min(a[2], b[2]); iy2 = min(a[3], b[3])
        iw = max(0.0, ix2 - ix1); ih = max(0.0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0.0:
            return 0.0
        area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
        area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    def _audit_update(self, detections: list, tracked: list, frame_number: int,
                      iou_thresh: float = 0.5):
        """Per-frame audit: which output tracks got a REAL YOLO box this frame.

        A track is a 'real hit' only if it IoU-matches an input detection
        (>= iou_thresh); otherwise it was Kalman-coasted. This separates
        detection loss from association loss for the OC-SORT go/no-go (P2.C).
        """
        for t in tracked:
            tid = t["track_id"]
            real_hit = any(
                self._bbox_iou(t["bbox"], d["bbox"]) >= iou_thresh for d in detections
            )
            rec = self._audit_tracks.get(tid)
            if rec is None:
                rec = {
                    "real_yolo_hits": 0, "n_output_frames": 0,
                    "first_real_hit_frame": None, "cur_gap": 0, "max_coasted_gap": 0,
                    "entry_y": float(t["center"][1]),
                    "entry_bbox_area": float(t["bbox_area"]),
                }
                self._audit_tracks[tid] = rec
            rec["n_output_frames"] += 1
            if real_hit:
                rec["real_yolo_hits"] += 1
                if rec["first_real_hit_frame"] is None:
                    rec["first_real_hit_frame"] = frame_number
                rec["cur_gap"] = 0
            else:
                rec["cur_gap"] += 1
                if rec["cur_gap"] > rec["max_coasted_gap"]:
                    rec["max_coasted_gap"] = rec["cur_gap"]

    def _audit_emit(self, track_id: int, vehicle: dict):
        """Snapshot a finalized track's audit record (called for EVERY finalized
        track, including ones dropped as no-origin/insufficient_data — those are
        exactly the fragmentation cases we need to count)."""
        rec = self._audit_tracks.pop(track_id, None)
        traj = vehicle.get("trajectory", [])
        base = rec or {"real_yolo_hits": 0, "n_output_frames": 0,
                       "first_real_hit_frame": None, "max_coasted_gap": 0,
                       "entry_y": (float(traj[0][1]) if traj else None),
                       "entry_bbox_area": None}
        self._audit_records.append({
            "track_id": track_id,
            "trim_id": getattr(self, "_v3_trim_id", None),
            "real_yolo_hits": base["real_yolo_hits"],
            "n_output_frames": base["n_output_frames"],
            "max_coasted_gap": base["max_coasted_gap"],
            "first_real_hit_frame": base["first_real_hit_frame"],
            "entry_y": base.get("entry_y"),
            "entry_bbox_area": base.get("entry_bbox_area"),
            "final_points": len(traj),
            "origin_assigned": vehicle.get("origin_leg_id") is not None,
        })

    def process_cached(
        self,
        reader,
        start_frame: int,
        end_frame: int,
        detection_skip: int = 1,
        callback=None,
    ):
        """Retrack from cached detections — no video decode, no YOLO.

        Replays the same detection-frame schedule the live loop would have used
        (frames in [start_frame, end_frame) where frame % detection_skip == 0),
        merging the cache reader's ascending (frame_idx, detections) stream onto
        that schedule. Frames the cache has no rows for (YOLO emitted nothing,
        or a detection frame with zero vehicles) get an empty update so the
        tracker's Kalman cadence matches the live run exactly. This is the
        minutes-long iteration path the detection cache exists to enable.
        """
        self.is_running = True
        reader_iter = reader.iter_frames()
        nxt = next(reader_iter, None)
        skip = max(1, detection_skip)
        try:
            for fn in range(start_frame, end_frame):
                if fn % skip != 0:
                    continue
                # Advance the reader past any frames before fn (defensive; the
                # cache should not contain off-schedule frames).
                while nxt is not None and nxt[0] < fn:
                    nxt = next(reader_iter, None)
                if nxt is not None and nxt[0] == fn:
                    dets = nxt[1]
                    nxt = next(reader_iter, None)
                else:
                    dets = []
                self._ingest_detections(dets, fn)
                if callback and fn % 300 == 0:
                    callback({"frame_number": fn, "vehicle_count": self.vehicle_count})
            self._finalize_all_active(end_frame)
        finally:
            self.is_running = False

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
                # Max bbox length + center-y at that max, for the §3-D articulated
                # size test (the vehicle's fullest-visible extent). Updated below.
                "max_bbox_length": 0.0,
                "bbox_center_y_at_max": None,
                # Native articulated votes (plan_articulated_native): class-at-
                # birth under-calls semis whose far-field births resolve as
                # plain vehicle, so every class-8 detection votes. Counted here,
                # decided at finalize against NATIVE_ARTICULATED_MIN_FRAMES.
                "n_native_articulated": 0,
            }
            self.n_tracks_total += 1

        vehicle = self.active_vehicles[track_id]
        vehicle["trajectory"].append(center)
        vehicle["confidences"].append(detection["confidence"])
        vehicle["bbox_width"] = detection["bbox_width"]
        vehicle["bbox_height"] = detection["bbox_height"]
        vehicle["bbox_area"] = detection["bbox_area"]
        _len = max(detection["bbox_width"], detection["bbox_height"])
        if _len > vehicle.get("max_bbox_length", 0.0):
            vehicle["max_bbox_length"] = _len
            vehicle["bbox_center_y_at_max"] = center[1]
        if detection["class_id"] == NATIVE_ARTICULATED_CLASS_ID:
            vehicle["n_native_articulated"] = (
                vehicle.get("n_native_articulated", 0) + 1)

        if vehicle["origin_leg_id"] is None:
            n_pts = len(vehicle["trajectory"])
            # Attempt origin assignment on every frame once we have enough
            # trajectory points. Previously throttled to n_pts % 3 == 0,
            # which meant 2-point trajectories (vehicle detected once,
            # missed, redetected once) never even attempted assignment —
            # the vehicle got silently dropped as insufficient_data.
            if n_pts >= ORIGIN_ASSIGN_MIN_FRAMES:
                self._assign_origin(track_id, frame_number)

    def _nearest_origin_leg_id(self, point) -> int | None:
        """leg_id whose origin_zone point is closest to `point`. Used by the
        origin-rewrite gate to detect a turn match that wants to rewrite origin
        to a leg the track never entered from. Returns None if no leg has an
        origin_zone."""
        best, best_d = None, float("inf")
        for leg in self.legs:
            zone = leg.get("origin_zone")
            if not zone:
                continue
            p0 = zone[0]
            d = (point[0] - p0[0]) ** 2 + (point[1] - p0[1]) ** 2
            if d < best_d:
                best_d, best = d, leg["leg_id"]
        return best

    def _assign_origin(self, track_id: int, frame_number: int):
        vehicle = self.active_vehicles[track_id]
        traj = vehicle["trajectory"]

        # --- Tier 0: polyline-path match (Phase 1) ---
        # When the camera has calibrated road polylines, score the
        # trajectory's first few points against the entry segment of every
        # path. The leg whose path's entry segment best matches wins.
        # This runs FIRST because it's a more specific signal than tripwire
        # crossing (encodes the road's curve, not just a point + heading)
        # and the legacy tiers stay as fallbacks for cameras without paths.
        if self._paths and len(traj) >= 4:
            prefix = traj[:min(8, len(traj))]
            match = score_origin_by_polyline(prefix, self._paths)
            lid = match.get("origin_leg_id")
            if lid is not None:
                leg = next((l for l in self.legs if l["leg_id"] == lid), None)
                if leg is not None:
                    vehicle["origin_leg_id"] = lid
                    vehicle["reference_heading"] = leg["reference_heading"]
                    vehicle["origin_frame"] = frame_number
                    vehicle["origin_polyline_path_id"] = match.get("path_id")
                    self.n_crossed_enter += 1
                    self.n_origin_via_polyline += 1
                    return

        # --- Spatial check: did the trajectory cross any origin zone line? ---
        # v3 calibration stores a single origin point per leg; we synthesize a
        # perpendicular tripwire through it on the fly so the line-crossing
        # logic still works. Legacy v2 zones (2-point lines) pass through unchanged.
        # INCREMENTAL (2026-07-17): attempts run on every detection frame, so
        # every segment before `tripwire_scanned` was already checked against
        # ALL legs by a prior attempt and found enter-free (an enter would
        # have assigned origin and ended the attempts) — rescanning them is
        # outcome-identical and made long-lived unassigned tracks quadratic
        # (a stationary clutter track turned cam4 study_1100's replay from
        # ~minutes into 43 min). Scan only the segments added since.
        scan_from = max(1, int(vehicle.get("tripwire_scanned", 1)))
        for leg in self.legs:
            zone = leg.get("origin_zone")
            if not zone:
                continue
            if len(zone) == 1:
                ref = leg.get("reference_heading")
                if ref is None:
                    continue
                line_start, line_end = tripwire_from_point(
                    zone[0], ref,
                    half_length=self._calibration_params.get("tripwire_half_length_px"),
                )
            elif len(zone) >= 2:
                line_start = tuple(zone[0])
                line_end = tuple(zone[1])
            else:
                continue
            for i in range(scan_from, len(traj)):
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
        vehicle["tripwire_scanned"] = len(traj)

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

        # Exclude low-volume legs (driveways) from heading fallback. Their
        # ref_heading sits between main legs and silently absorbs cross-
        # leg traffic via the wide <=90 deg angular basin. See
        # HEADING_FALLBACK_EXCLUDE_LABEL_KEYWORDS in backend/config.py.
        def _eligible(leg: dict) -> bool:
            label = (leg.get("label") or "")
            return not any(kw in label for kw in HEADING_FALLBACK_EXCLUDE_LABEL_KEYWORDS)

        best_idx = None
        best_diff = float("inf")
        for i, leg in enumerate(self.legs):
            if not _eligible(leg):
                continue
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

    def _ensure_entry_gates(self):
        """Build the leg entry gates once (operator mouths + bank tangents —
        the entry_gates service, ported from the proven box-clip machinery)."""
        if self._entry_gates is None:
            from backend.services.entry_gates import build_gates
            mouths, heads = {}, {}
            for lg in self.legs:
                oz = lg.get("origin_zone")
                if oz:
                    mouths[lg["leg_id"]] = tuple(oz[0])
                    heads[lg["leg_id"]] = lg.get("reference_heading")
            # Gate geometry must be STABLE: built from _gate_paths (set by
            # callers that inject experimental candidate sets, e.g. replay
            # bank injection) so ablating candidates never rotates the gates
            # themselves. The fill-arm confound (origin_evidenced 4691->2628
            # from one added path's mouth tangents) is why this is separate.
            gate_paths = getattr(self, "_gate_paths", None) or self._paths
            self._entry_gates = build_gates(mouths, gate_paths or [], heads) \
                if mouths else {}
        return self._entry_gates

    def _gate_evidence(self, vehicle: dict) -> tuple[int | None, int | None, str | None]:
        """Entry-gate evidence for a finalized track: (origin, dest, tag).
        origin = the leg whose gate the track crossed INWARD (None when
        unevidenced), dest = the leg crossed outward last, tag one of
        'full' / 'entry_only' / 'exit_only' / 'no_crossing'. One classify
        call — the posterior half consumes dest/tag, the filter half origin.
        Frames are approximated as start_frame + index (coasted gaps shift
        jitter windows by at most the gap — immaterial at 2 s granularity)."""
        from backend.services.entry_gates import classify as gate_classify
        gates = self._ensure_entry_gates()
        if not gates:
            return None, None, None
        f0 = vehicle.get("start_frame") or 0
        pts = [(float(f0 + i), float(p[0]), float(p[1]))
               for i, p in enumerate(vehicle["trajectory"])]
        if len(pts) < 2:
            return None, None, None
        origin, dest, _fo, _fd, _op, _dp, tag = gate_classify(pts, gates, self.fps)
        return origin, dest, tag

    def _finalize_vehicle_data(self, track_id: int, vehicle: dict, frame_number: int):
        """Finalize a vehicle dict (from active_vehicles or recently_lost)."""
        # Audit snapshot first — before any early-return — so dropped tracks
        # (no origin / insufficient_data), the fragmentation cases, are counted.
        if self._audit_mode:
            self._audit_emit(track_id, vehicle)
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

        # Track-quality gate (Phase 1.1): with a loosened birth threshold the
        # tracker births from the low-confidence band; clutter among those
        # births is rejected HERE, with the whole track in hand, instead of at
        # birth. High-mean-conf tracks always pass (see track_filter docstring).
        if self._calibration_params.get("track_quality_filter"):
            ok, _reason = track_quality(trajectory, vehicle.get("confidences") or [])
            if not ok:
                self.n_quality_filtered += 1
                return

        classification = classify_trajectory(
            trajectory, vehicle["reference_heading"],
            through_max_angle=self._calibration_params.get("trajectory_through_max_angle"),
            turn_min_angle=self._calibration_params.get("trajectory_turn_min_angle"),
            uturn_min_angle=self._calibration_params.get("trajectory_uturn_min_angle"),
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
        origin_leg = next(
            (lg for lg in self.legs if lg["leg_id"] == origin_leg_id), None,
        )

        # --- Origin-evidence gate (item-8 mechanism 1, filter half) ---------
        # An inward entry-gate crossing BINDS origin: the early entry-tangent
        # assignment is overridden to the evidenced leg, and the joint scorer
        # only sees paths FROM that leg — the winning path can no longer
        # rewrite origin across the intersection (the phase-0 flip mechanism).
        # No evidence -> current behavior, counted (the posterior half gates
        # separately per plan_origin_evidence_gate_2026-07-14).
        candidate_paths = self._paths
        gate_origin = gate_dest = gate_tag = None
        # Branch-1 event columns (partial-evidence posterior); None unless the
        # unevidenced-origin posterior fires for this track.
        origin_post_json = None
        origin_margin_val = None
        dest_tie_marg = None
        posterior_source = None
        if ORIGIN_EVIDENCE_GATE_ENABLED and self._paths:
            evidenced, gate_dest, gate_tag = self._gate_evidence(vehicle)
            gate_origin = evidenced
            if evidenced is not None:
                self.n_origin_evidenced += 1
                if evidenced != origin_leg_id:
                    self.n_origin_corrected += 1
                    origin_leg_id = evidenced
                    origin_leg = next(
                        (lg for lg in self.legs if lg["leg_id"] == evidenced),
                        origin_leg)
                    vehicle["origin_leg_id"] = evidenced
                candidate_paths = [p for p in self._paths
                                   if p["origin_leg_id"] == evidenced]
            else:
                self.n_origin_unevidenced += 1

        # --- Tier 0: polyline-path (origin + destination + movement) ---
        # When the camera has calibrated paths, the (origin_leg,
        # destination_leg, movement_label) triple comes directly from the
        # best-matching path. No softmax scorer, no derive_movement — the
        # path's geometry already encodes the movement type (the curve
        # through the intersection IS the movement).
        #
        # Attribution v2 (joint partial-Fréchet, the preferred path): a single
        # scorer matches the whole trajectory to the best sub-curve of each
        # path and READS ORIGIN OFF the winning path, instead of trusting the
        # entry-tangent-based early origin assignment (structurally unreliable
        # at this camera — vehicles enter mid-turn). The legacy separate
        # destination scorer remains the fallback when the joint scorer finds
        # no confident match. See docs/implementation_plan_accuracy_2026-05-27.md.
        polyline_dest = None
        if candidate_paths and USE_JOINT_PARTIAL_FRECHET_SCORER:
            joint = score_path_joint(
                trajectory, candidate_paths,
                max_cost=JOINT_SCORER_MAX_COST_PX,
                min_coverage_frac=JOINT_SCORER_MIN_COVERAGE_FRAC,
                tail_window=JOINT_SCORER_TAIL_WINDOW,
                tail_weight=JOINT_SCORER_TAIL_WEIGHT,
                coverage_weight=JOINT_SCORER_COVERAGE_WEIGHT,
                # Per-camera override (Phase 2.3): cam3's live recipe was tuned
                # under dtw_mean and is pinned there; the config default is mdh.
                cost_metric=(self._calibration_params.get("cost_metric")
                             or JOINT_SCORER_COST_METRIC),
                turn_tail_prior_floor=JOINT_SCORER_TURN_TAIL_PRIOR_FLOOR,
                turn_min_coverage=JOINT_SCORER_TURN_MIN_COVERAGE,
                # Shared-exit collinear entry-tiebreak (cam2 SB<->EB swap fix).
                # Per-camera enable via calib knob; mdh-only inside the scorer.
                entry_tiebreak=self._calibration_params.get(
                    "entry_tiebreak", ENTRY_TIEBREAK_ENABLED),
                entry_tiebreak_exit_px=ENTRY_TIEBREAK_EXIT_PX,
                entry_tiebreak_collinear_px=ENTRY_TIEBREAK_COLLINEAR_PX,
                entry_tiebreak_min_entry_sep_px=ENTRY_TIEBREAK_MIN_ENTRY_SEP_PX,
                entry_tiebreak_decisive_px=ENTRY_TIEBREAK_DECISIVE_PX,
                # Speed-tiebreak (entry retry): inert unless paths carry
                # expected_speed. Per-camera calib_speed_tiebreak (0/1) overrides;
                # NULL/unset falls back to the config default. mdh-only.
                speed_tiebreak=(
                    SPEED_TIEBREAK_ENABLED
                    if self._calibration_params.get("speed_tiebreak") is None
                    else bool(self._calibration_params.get("speed_tiebreak"))),
                speed_tiebreak_decisive=SPEED_TIEBREAK_DECISIVE,
                speed_tiebreak_min_sep=SPEED_TIEBREAK_MIN_SEP,
                # Partial-evidence posterior consumes the admitted candidate
                # set; byte-identical result dict when the flag is off.
                return_candidates=(ORIGIN_POSTERIOR_ENABLED
                                   and ORIGIN_EVIDENCE_GATE_ENABLED),
            )
            if joint.get("entry_tiebreak_applied"):
                self.n_entry_tiebreak += 1
            if joint.get("speed_tiebreak_applied"):
                self.n_speed_tiebreak += 1
            # Origin-rewrite gate (snap-magnet defence): a straight "turn"
            # polyline can capture a THROUGH track and rewrite its origin to a
            # leg the track never entered from. Reject a TURN match that would
            # rewrite origin away from the nearest origin-zone to the track's
            # first point — but ONLY when the track itself is geometrically
            # straight (a through). Real turns curve, so genuine mid-turn-entry
            # turns stay below the floor and pass. See config notes.
            if (joint.get("destination_leg_id") is not None
                    and ORIGIN_REWRITE_GATE_ENABLED
                    and joint.get("movement_label") in ("left", "right", "u_turn")
                    and joint.get("origin_leg_id") is not None
                    and classification["path_straightness"] >= ORIGIN_REWRITE_GATE_STRAIGHTNESS):
                near = self._nearest_origin_leg_id(trajectory[0])
                if near is not None and near != joint["origin_leg_id"]:
                    joint = {**joint, "destination_leg_id": None}
                    self.n_origin_rewrite_gated += 1

            # --- Partial-evidence posterior (mechanism 1, posterior half) ---
            # plan_posterior_half_2026-07-15. Branch 1: an UNEVIDENCED track
            # may not hard-claim whichever admitted path composite-scores
            # best (the residual flip channel) — its origin gets an explicit
            # posterior over the admitted candidates' origins, weighted by
            # corpus-support proportions x shape residual; exit-gate evidence
            # filters candidates to the evidenced destination first. Counted
            # at the posterior max; the posterior + margin are persisted so
            # Feeder-1 queues near-ties (origin_ambiguous).
            if (ORIGIN_POSTERIOR_ENABLED and ORIGIN_EVIDENCE_GATE_ENABLED
                    and gate_tag is not None):
                cands = joint.get("candidates") or []
                if gate_origin is None and cands:
                    pool = cands
                    # The origin-rewrite gate's rule, applied PER-CANDIDATE
                    # (the cam1 sweep defect, 2026-07-15): a geometrically
                    # STRAIGHT track may not claim a TURN path whose origin is
                    # not its nearest origin zone. The winner-only veto above
                    # nulls the composite pick, but the posterior re-picked
                    # from the raw candidate list and resurrected the vetoed
                    # family — truncated exit stubs clear a short turn path's
                    # coverage floor while failing the long thru path's, so
                    # the turn is the ONLY admitted candidate (cam1 24->23
                    # left: 582 counted vs Mio 86). Same rule, same constant,
                    # no new knobs. An emptied pool = branch 1 stands down and
                    # the legacy fallback chain proceeds.
                    if (ORIGIN_REWRITE_GATE_ENABLED
                            and classification["path_straightness"]
                            >= ORIGIN_REWRITE_GATE_STRAIGHTNESS):
                        near = self._nearest_origin_leg_id(trajectory[0])
                        if near is not None:
                            allowed = [c for c in pool if not (
                                c["path"].get("movement_label")
                                in ("left", "right", "u_turn")
                                and c["path"].get("origin_leg_id") != near)]
                            if len(allowed) < len(pool):
                                self.n_posterior_vetoed += 1
                            pool = allowed
                    if pool and gate_tag == "exit_only" and gate_dest is not None:
                        exit_pool = [
                            c for c in pool
                            if c["path"].get("destination_leg_id") == gate_dest]
                        # An exit graze that matches no admitted path must not
                        # starve the posterior — fall back to the (vetoed) set.
                        pool = exit_pool or pool
                    marg, best_by = (partial_evidence.origin_posterior(pool)
                                     if pool else ({}, {}))
                    if marg:
                        o_star = max(marg, key=marg.get)
                        win = best_by[o_star]
                        joint = {
                            **joint,
                            "origin_leg_id": win["path"].get("origin_leg_id"),
                            "destination_leg_id": win["path"].get("destination_leg_id"),
                            "movement_label": win["path"].get("movement_label"),
                            "path_id": win["path"].get("path_id"),
                            "distance": win["cost"],
                            "coverage": win["coverage"],
                        }
                        origin_post_json = json.dumps(
                            {str(l): round(p, 4) for l, p in marg.items()})
                        origin_margin_val = posterior_margin(marg)
                        posterior_source = "branch1"
                        self.n_posterior_origin += 1
                        if origin_margin_val < ORIGIN_POSTERIOR_MARGIN_FLOOR:
                            self.n_origin_ambiguous += 1
                # Branch 2: an EVIDENCED track that died before its exit
                # (entry_only) whose admitted candidates tie on cost — the
                # separating geometry lies past the death point, so shape
                # cannot rank them (the 217-track EB right-snap). Tied cells
                # re-pick by corpus-support proportions; the destination
                # posterior + margin flow through the existing columns.
                elif (gate_origin is not None and gate_tag == "entry_only"
                        and joint.get("destination_leg_id") is not None
                        and len(cands) >= 2):
                    tied = partial_evidence.tied_candidates(
                        cands, joint["distance"], DEST_TIE_BAND)
                    if len({c["path"].get("destination_leg_id")
                            for c in tied}) >= 2:
                        marg, best_by = partial_evidence.destination_posterior(tied)
                        if marg:
                            d_star = max(marg, key=marg.get)
                            win = best_by[d_star]
                            joint = {
                                **joint,
                                "origin_leg_id": win["path"].get("origin_leg_id"),
                                "destination_leg_id": win["path"].get("destination_leg_id"),
                                "movement_label": win["path"].get("movement_label"),
                                "path_id": win["path"].get("path_id"),
                                "distance": win["cost"],
                                "coverage": win["coverage"],
                            }
                            dest_tie_marg = marg
                            posterior_source = "dest_tie"
                            self.n_posterior_dest += 1

            if joint.get("destination_leg_id") is not None:
                polyline_dest = joint
                # Origin is read off the winning path — override the
                # provisional early assignment (it gated "real vehicle?" but
                # its entry-tangent leg can be wrong here).
                new_origin = joint.get("origin_leg_id")
                if new_origin is not None and new_origin != origin_leg_id:
                    origin_leg_id = new_origin
                    vehicle["origin_leg_id"] = new_origin
                    origin_leg = next(
                        (lg for lg in self.legs if lg["leg_id"] == new_origin), None,
                    )
                    if origin_leg is not None and origin_leg.get("reference_heading") is not None:
                        vehicle["reference_heading"] = origin_leg["reference_heading"]
                    self.n_origin_via_polyline += 1
                    # NOTE: classify_trajectory() already ran above against the
                    # PROVISIONAL reference_heading, so the stored classifier_*
                    # audit columns are relative to the old origin for these
                    # joint-scorer hits. The reported movement comes from the
                    # path label (not classification), so counts are unaffected;
                    # only the diagnostic columns are stale. Acceptable for v1.

        if self._paths and polyline_dest is None:
            polyline_dest = score_destination_by_polyline(
                trajectory, origin_leg_id, self._paths,
            )
        if polyline_dest is not None and polyline_dest.get("destination_leg_id") is not None:
            self.n_destination_via_polyline += 1

        if polyline_dest and polyline_dest.get("destination_leg_id") is not None:
            destination_leg_id = polyline_dest["destination_leg_id"]
            destination_leg = next(
                (lg for lg in self.legs if lg["leg_id"] == destination_leg_id), None,
            )
            movement = polyline_dest["movement_label"]
            # Build a posterior-shaped dict for DB write so the existing
            # destination_posterior_json column stays populated.
            dest_result = {
                "destination_leg_id": destination_leg_id,
                "confidence": max(0.0, 1.0 - polyline_dest["distance"] / 100.0),
                # Branch-2 tie posterior when it fired (its small margin is
                # what queues the event); the usual peaked form otherwise.
                "posterior": (dest_tie_marg if dest_tie_marg
                              else {destination_leg_id: 1.0}),
                "via": ("polyline+tie_posterior" if dest_tie_marg else "polyline"),
                "polyline_path_id": polyline_dest.get("path_id"),
            }
        else:
            # --- Fallback: softmax destination scorer + derive_movement ---
            # The bug #5 (Phase B) fix used at cameras without polyline
            # calibration: score every leg by exit heading + position vs
            # leg-from-center direction.
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
            # --- Rescue (posterior half, the no-drop principle) -------------
            # An EVIDENCED track the whole chain failed to place would be
            # silently dropped here — phase-0's "box-complete, NO event"
            # pool (288) and the de-flip drops (39 genuine NB-lefts on 1100).
            # full journey -> count hard at the evidenced cell; entry-only ->
            # supports posterior over the evidenced origin's cells (no shape
            # signal exists; the honest small margin queues it). Unevidenced
            # tracks stay dropped — no evidence + no geometry = counting by
            # popularity, the named posterior risk.
            rescued = False
            if (ORIGIN_POSTERIOR_ENABLED and ORIGIN_EVIDENCE_GATE_ENABLED
                    and gate_origin is not None and self._paths):
                if gate_tag == "full" and gate_dest is not None:
                    cell_paths = [
                        p for p in self._paths
                        if p.get("origin_leg_id") == gate_origin
                        and p.get("destination_leg_id") == gate_dest]
                    mv = None
                    if cell_paths:
                        winp = max(cell_paths,
                                   key=lambda p: p.get("supporting_count") or 0)
                        mv = winp.get("movement_label")
                    else:
                        dleg = next((lg for lg in self.legs
                                     if lg["leg_id"] == gate_dest), None)
                        if origin_leg and dleg:
                            mv = derive_movement(origin_leg, dleg,
                                                 all_legs=self.legs)
                    if mv and mv != "insufficient_data":
                        destination_leg_id = gate_dest
                        destination_leg = next(
                            (lg for lg in self.legs
                             if lg["leg_id"] == gate_dest), None)
                        movement = mv
                        dest_result = {
                            "destination_leg_id": gate_dest, "confidence": 1.0,
                            "posterior": {gate_dest: 1.0}, "via": "gate_rescue",
                        }
                        posterior_source = "rescue_full"
                        rescued = True
                elif gate_tag == "entry_only":
                    origin_paths = [p for p in self._paths
                                    if p.get("origin_leg_id") == gate_origin]
                    marg, best_by = partial_evidence.supports_posterior(origin_paths)
                    if marg:
                        d_star = max(marg, key=marg.get)
                        winp = best_by[d_star]
                        mv = winp.get("movement_label")
                        if mv and mv != "insufficient_data":
                            destination_leg_id = d_star
                            destination_leg = next(
                                (lg for lg in self.legs
                                 if lg["leg_id"] == d_star), None)
                            movement = mv
                            dest_result = {
                                "destination_leg_id": d_star,
                                "confidence": marg[d_star],
                                "posterior": marg, "via": "supports_rescue",
                            }
                            posterior_source = "rescue_supports"
                            rescued = True
            if rescued:
                self.n_posterior_rescued += 1
            else:
                self.n_insufficient_data += 1
                return

        avg_conf = (
            sum(vehicle["confidences"]) / len(vehicle["confidences"])
            if vehicle["confidences"]
            else 0
        )

        # Native articulated decision (plan_articulated_native_2026-07-17):
        # enough class-8 votes -> articulated regardless of birth class; a
        # born-8 track WITHOUT the vote floor demotes to plain truck (a
        # 1-frame flicker never flips a class). Coco-scheme runs have no 8s
        # anywhere, so this is a no-op for them by construction.
        effective_class_id = vehicle["class_id"]
        if (vehicle.get("n_native_articulated", 0)
                >= NATIVE_ARTICULATED_MIN_FRAMES):
            effective_class_id = NATIVE_ARTICULATED_CLASS_ID
        elif effective_class_id == NATIVE_ARTICULATED_CLASS_ID:
            effective_class_id = 7
        vehicle_class = classify_vehicle(
            effective_class_id,
            vehicle["bbox_width"],
            vehicle["bbox_height"],
            vehicle["bbox_area"],
            avg_conf,
        )

        # Timestamp the event at the ORIGIN-CROSSING frame, not the finalization
        # frame. `frame_number` here is when the track was finalized — it lags the
        # actual crossing by transit time + up to the lost-track buffer (~15s),
        # which mis-bins vehicles into later per-minute / 15-min TMC periods (a
        # 07:14:58 crossing counted at 07:15). Miovision (and any TMC) counts at the
        # crossing, so use vehicle["origin_frame"] (set when the vehicle crossed its
        # origin leg; always present once origin_leg_id is assigned, which is a
        # precondition for writing an event). The finalization frame is still kept
        # verbatim in the `frame_number` column for audit.
        crossing_frame = vehicle.get("origin_frame")
        if crossing_frame is None:
            crossing_frame = frame_number
        timestamp_video = crossing_frame / self.fps

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
        # Precompute the near-tie margin so the review flag feeder can filter on
        # it in SQL instead of parsing every event's posterior (MASTER_PLAN §3-B).
        # From the serialised JSON so it is byte-identical to what the feeder
        # recomputes (else a boundary event could slip the SQL pre-filter).
        destination_margin = margin_from_json(posterior_json)

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
            destination_margin=destination_margin,
            # Partial-evidence posterior (branch 1): the origin posterior +
            # its near-tie margin; NULL for every other event (legacy shape).
            origin_posterior_json=origin_post_json,
            origin_margin=origin_margin_val,
            posterior_source=posterior_source,
            # §3-D: the vehicle's max bbox length + center-y, for the articulated
            # size test (exact from the tracker -> no cache re-linking needed).
            bbox_length=vehicle.get("max_bbox_length"),
            bbox_center_y=vehicle.get("bbox_center_y_at_max"),
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
                    destination_posterior_json,
                    destination_margin,
                    origin_posterior_json,
                    origin_margin,
                    posterior_source,
                    bbox_length,
                    bbox_center_y)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    kwargs.get("destination_margin"),
                    kwargs.get("origin_posterior_json"),
                    kwargs.get("origin_margin"),
                    kwargs.get("posterior_source"),
                    kwargs.get("bbox_length"),
                    kwargs.get("bbox_center_y"),
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
