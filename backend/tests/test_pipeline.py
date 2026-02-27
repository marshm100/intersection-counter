"""Tests for the processing pipeline.

Uses mocked detector to avoid loading YOLO — tests pipeline logic only:
origin crossing, trajectory building, finalization, event writing.
"""

import json
import os
import pickle
import sqlite3
import tempfile
import threading

import cv2
import numpy as np
import pytest
from unittest.mock import MagicMock, PropertyMock, patch

from backend.database import SCHEMA
from backend.services.pipeline import ProcessingPipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_env():
    """Create a temp project dir with initialized DB, mock legs, and video."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "project.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)

        # NB origin zone: horizontal line at y=800, right-to-left so
        # left side (+1) = interior (above line, toward intersection center)
        conn.execute(
            """INSERT INTO legs
               (label, cardinal_direction, sort_order, origin_zone, reference_heading)
               VALUES (?, ?, ?, ?, ?)""",
            ("Northbound", "NB", 1, json.dumps([[700, 800], [300, 800]]), 0.0),
        )
        # EB origin zone: vertical line at x=200, bottom-to-top so
        # left side (+1) = interior (right of line, toward center)
        conn.execute(
            """INSERT INTO legs
               (label, cardinal_direction, sort_order, origin_zone, reference_heading)
               VALUES (?, ?, ?, ?, ?)""",
            ("Eastbound", "EB", 2, json.dumps([[200, 700], [200, 300]]), 90.0),
        )
        conn.commit()
        conn.close()

        # Create a 30-frame synthetic video (640x480 @ 30fps)
        video_path = os.path.join(tmpdir, "test.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(video_path, fourcc, 30.0, (640, 480))
        for _ in range(30):
            writer.write(np.zeros((480, 640, 3), dtype=np.uint8))
        writer.release()

        legs = [
            {
                "leg_id": 1,
                "label": "Northbound",
                "cardinal_direction": "NB",
                "origin_zone": [[700, 800], [300, 800]],
                "reference_heading": 0.0,
            },
            {
                "leg_id": 2,
                "label": "Eastbound",
                "cardinal_direction": "EB",
                "origin_zone": [[200, 700], [200, 300]],
                "reference_heading": 90.0,
            },
        ]

        yield {
            "db_path": db_path,
            "video_path": video_path,
            "legs": legs,
            "tmpdir": tmpdir,
        }


def _make_pipeline(env, video_start_time=None):
    """Create a pipeline without loading YOLO."""
    return ProcessingPipeline(
        project_id="test",
        db_path=env["db_path"],
        video_path=env["video_path"],
        legs=env["legs"],
        fps=30.0,
        video_start_time=video_start_time,
    )


def _make_detection(x, y, w=100, h=60, class_id=2, confidence=0.9):
    """Build a detection dict at center (x, y)."""
    x1, y1, x2, y2 = x - w / 2, y - h / 2, x + w / 2, y + h / 2
    return {
        "bbox": [x1, y1, x2, y2],
        "center": [float(x), float(y)],
        "class_id": class_id,
        "class_name": "car",
        "confidence": confidence,
        "bbox_width": float(w),
        "bbox_height": float(h),
        "bbox_area": float(w * h),
        "is_vehicle": class_id in (2, 3, 5, 7),
        "is_pedestrian": class_id in (0, 1),
    }


def _nb_through_detections(num_frames=20):
    """Vehicle enters from south (y=850), crosses NB zone at y=800, goes north.

    With frame_skip=1 and step=40 we get:
    y: 850, 810, 770, 730, … all the way to y=90.
    Crosses y=800 zone between frame 0 (y=850) and frame 1 (y=810).
    """
    frames = []
    for i in range(num_frames):
        y = 850 - i * 40
        frames.append([_make_detection(500, y)])
    return frames


def _count_vehicle_events(db_path):
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM vehicle_events").fetchone()[0]
    conn.close()
    return count


def _get_vehicle_events(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM vehicle_events").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# TestPipelineInit
# ---------------------------------------------------------------------------

class TestPipelineInit:
    def test_creates_successfully(self, pipeline_env):
        p = _make_pipeline(pipeline_env)
        assert p is not None
        # Detector should NOT be loaded yet
        assert p._detector is None

    def test_origin_zones_parsed(self, pipeline_env):
        p = _make_pipeline(pipeline_env)
        assert len(p.origin_zones) == 2
        assert p.origin_zones[0] == [[700, 800], [300, 800]]
        assert p.origin_zones[1] == [[200, 700], [200, 300]]

    def test_initial_counts_zero(self, pipeline_env):
        p = _make_pipeline(pipeline_env)
        assert p.vehicle_count == 0
        assert p.pedestrian_count == 0
        assert p.error_count == 0


# ---------------------------------------------------------------------------
# TestPipelineProcessing (mocked detector)
# ---------------------------------------------------------------------------

class TestPipelineProcessing:
    def test_vehicle_crosses_origin_and_finalized(self, pipeline_env):
        """Vehicle crosses NB origin zone and goes straight → 1 event."""
        p = _make_pipeline(pipeline_env)
        mock_dets = _nb_through_detections(num_frames=20)
        frame_idx = [0]

        # Mock preprocessor (passthrough), detector (scripted), tracker (identity)
        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        def mock_detect(frame):
            idx = frame_idx[0]
            frame_idx[0] += 1
            return mock_dets[idx] if idx < len(mock_dets) else []
        p._detector.detect = mock_detect

        # Tracker that assigns consistent track_id=1
        call_count = [0]
        def mock_tracker_update(detections, frame_number):
            call_count[0] += 1
            results = []
            for d in detections:
                results.append({**d, "track_id": 1})
            return results

        p._tracker = MagicMock()
        p._tracker.update = mock_tracker_update
        p._tracker.get_state = MagicMock(return_value=b"")

        p.process_video(frame_skip=1, start_frame=0)

        assert _count_vehicle_events(pipeline_env["db_path"]) >= 1
        events = _get_vehicle_events(pipeline_env["db_path"])
        assert events[0]["origin_leg_id"] == 1

    def test_vehicle_never_crosses_origin(self, pipeline_env):
        """Vehicle stays below origin zone → 0 events."""
        p = _make_pipeline(pipeline_env)
        # Vehicle at y=900, never crosses y=800 zone
        mock_dets = [[_make_detection(500, 900 + i)] for i in range(20)]
        frame_idx = [0]

        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        def mock_detect(frame):
            idx = frame_idx[0]
            frame_idx[0] += 1
            return mock_dets[idx] if idx < len(mock_dets) else []
        p._detector.detect = mock_detect

        p._tracker = MagicMock()
        p._tracker.update = lambda dets, fn: [{**d, "track_id": 1} for d in dets]
        p._tracker.get_state = MagicMock(return_value=b"")

        p.process_video(frame_skip=1)
        assert _count_vehicle_events(pipeline_env["db_path"]) == 0

    def test_multiple_vehicles(self, pipeline_env):
        """Two vehicles crossing at different times → 2 events."""
        p = _make_pipeline(pipeline_env)

        # Vehicle A crosses first, then Vehicle B
        all_dets = []
        for i in range(20):
            frame_dets = []
            # Vehicle A: crosses NB zone
            ya = 850 - i * 40
            frame_dets.append(_make_detection(400, ya))
            # Vehicle B: crosses NB zone, offset in time
            if i >= 5:
                yb = 850 - (i - 5) * 40
                frame_dets.append(_make_detection(600, yb))
            all_dets.append(frame_dets)

        frame_idx = [0]
        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        def mock_detect(frame):
            idx = frame_idx[0]
            frame_idx[0] += 1
            return all_dets[idx] if idx < len(all_dets) else []
        p._detector.detect = mock_detect

        # Tracker assigns id based on x position
        p._tracker = MagicMock()
        def mock_update(dets, fn):
            results = []
            for d in dets:
                tid = 1 if d["center"][0] < 500 else 2
                results.append({**d, "track_id": tid})
            return results
        p._tracker.update = mock_update
        p._tracker.get_state = MagicMock(return_value=b"")

        p.process_video(frame_skip=1)
        assert _count_vehicle_events(pipeline_env["db_path"]) >= 2

    def test_frame_error_continues(self, pipeline_env):
        """Detector exception on one frame → processing continues."""
        p = _make_pipeline(pipeline_env)
        call_count = [0]

        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        def mock_detect(frame):
            call_count[0] += 1
            if call_count[0] == 3:
                raise RuntimeError("Simulated detection error")
            return []
        p._detector.detect = mock_detect

        p._tracker = MagicMock()
        p._tracker.update = MagicMock(return_value=[])
        p._tracker.get_state = MagicMock(return_value=b"")

        p.process_video(frame_skip=1)
        assert p.error_count >= 1
        # Processing didn't crash — more frames were processed after the error
        assert call_count[0] > 3

    def test_pause_saves_checkpoint(self, pipeline_env):
        """Pause signal → checkpoint saved to DB."""
        p = _make_pipeline(pipeline_env)

        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        call_count = [0]
        p._detector = MagicMock()
        def mock_detect(frame):
            call_count[0] += 1
            if call_count[0] >= 3:
                p.pause()
            return []
        p._detector.detect = mock_detect

        p._tracker = MagicMock()
        p._tracker.update = MagicMock(return_value=[])
        p._tracker.get_state = MagicMock(return_value=b"state")

        p.process_video(frame_skip=1)
        assert p._checkpoint_mgr.has_checkpoint() is True


# ---------------------------------------------------------------------------
# TestPipelineCheckpointIntegration
# ---------------------------------------------------------------------------

class TestPipelineCheckpointIntegration:
    def test_resume_from_checkpoint(self, pipeline_env):
        """Save checkpoint, then restore counts and start_frame."""
        p = _make_pipeline(pipeline_env)
        p.vehicle_count = 10
        p.pedestrian_count = 3
        p.error_count = 1
        p.active_vehicles = {1: {"trajectory": [(100, 200)]}}

        p._save_checkpoint(frame_number=900, video_time=30.0)

        p2 = _make_pipeline(pipeline_env)
        start_frame = p2.resume_from_checkpoint()

        assert p2.vehicle_count == 10
        assert p2.pedestrian_count == 3
        assert p2.error_count == 1
        # Rewind by 60s * 30fps = 1800 frames → max(0, 900-1800) = 0
        assert start_frame == 0

    def test_resume_restores_active_vehicles(self, pipeline_env):
        """Active vehicles dict is restored from checkpoint."""
        p = _make_pipeline(pipeline_env)
        p.active_vehicles = {
            5: {
                "origin_leg_id": 1,
                "trajectory": [(100, 200), (110, 190)],
                "confidences": [0.9, 0.85],
            }
        }
        p._save_checkpoint(frame_number=500, video_time=16.7)

        p2 = _make_pipeline(pipeline_env)
        p2.resume_from_checkpoint()
        assert 5 in p2.active_vehicles
        assert p2.active_vehicles[5]["origin_leg_id"] == 1
        assert len(p2.active_vehicles[5]["trajectory"]) == 2


# ---------------------------------------------------------------------------
# TestVehicleEventWriting
# ---------------------------------------------------------------------------

class TestVehicleEventWriting:
    def test_event_fields_complete(self, pipeline_env):
        """After finalization, all vehicle_events columns are populated."""
        p = _make_pipeline(pipeline_env)

        # Manually set up a vehicle that crossed origin and has a trajectory
        p.active_vehicles[99] = {
            "origin_leg_id": 1,
            "reference_heading": 0.0,
            "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20,
            "last_center": (500, 400),
            "class_id": 2,
            "class_name": "car",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
        }

        p._finalize_vehicle(99, frame_number=25)

        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        e = events[0]
        assert e["vehicle_track_id"] == 99
        assert e["origin_leg_id"] == 1
        assert e["movement"] in ("through", "left", "right", "uturn")
        assert e["vehicle_class"] is not None
        assert e["detection_confidence"] == pytest.approx(0.9)
        assert e["frame_number"] == 25

    def test_timestamp_real_computed(self, pipeline_env):
        """When video_start_time is set, timestamp_real is computed."""
        p = _make_pipeline(pipeline_env, video_start_time="2024-06-15T08:00:00")

        p.active_vehicles[50] = {
            "origin_leg_id": 1,
            "reference_heading": 0.0,
            "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20,
            "last_center": (500, 400),
            "class_id": 2,
            "class_name": "car",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
        }

        p._finalize_vehicle(50, frame_number=900)

        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        assert events[0]["timestamp_real"] is not None
        assert "2024-06-15" in events[0]["timestamp_real"]
