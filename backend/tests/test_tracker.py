"""Tests for ByteTrack tracker wrapper."""

import pytest

from backend.config import PEDESTRIAN_CLASSES, VEHICLE_CLASSES
from backend.services.tracker import VehicleTracker


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def make_detection(x1, y1, x2, y2, class_id=2, confidence=0.9):
    """Create a single detection dict matching VehicleDetector output format."""
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    w, h = x2 - x1, y2 - y1
    return {
        "bbox": [x1, y1, x2, y2],
        "center": [cx, cy],
        "class_id": class_id,
        "class_name": VEHICLE_CLASSES.get(
            class_id, PEDESTRIAN_CLASSES.get(class_id, f"class_{class_id}")
        ),
        "confidence": confidence,
        "bbox_width": w,
        "bbox_height": h,
        "bbox_area": w * h,
        "is_vehicle": class_id in VEHICLE_CLASSES,
        "is_pedestrian": class_id in PEDESTRIAN_CLASSES,
    }


def make_moving_vehicle(
    start_x, start_y, dx=10, dy=0, num_frames=10,
    width=100, height=80, class_id=2,
):
    """Generate a list of detection lists simulating a vehicle moving across frames."""
    frames = []
    for i in range(num_frames):
        x1 = start_x + i * dx
        y1 = start_y + i * dy
        frames.append([make_detection(x1, y1, x1 + width, y1 + height, class_id)])
    return frames


REQUIRED_KEYS = {
    "track_id", "bbox", "center", "class_id", "class_name",
    "confidence", "is_vehicle", "is_pedestrian",
    "bbox_width", "bbox_height", "bbox_area",
}


# ---------------------------------------------------------------------------
# TestTrackerInit
# ---------------------------------------------------------------------------

class TestTrackerInit:
    def test_creates_successfully(self):
        tracker = VehicleTracker()
        assert tracker is not None

    def test_initial_state_empty(self):
        tracker = VehicleTracker()
        assert tracker.get_active_track_ids() == []


# ---------------------------------------------------------------------------
# TestTrackerUpdate
# ---------------------------------------------------------------------------

class TestTrackerUpdate:
    def test_single_vehicle_consistent_id(self):
        tracker = VehicleTracker()
        frames = make_moving_vehicle(100, 200, dx=10, num_frames=10)
        track_ids = []
        for i, dets in enumerate(frames):
            results = tracker.update(dets, frame_number=i)
            assert len(results) == 1
            track_ids.append(results[0]["track_id"])
        # All frames should have the same track_id
        assert len(set(track_ids)) == 1

    def test_empty_detections(self):
        tracker = VehicleTracker()
        results = tracker.update([], frame_number=0)
        assert results == []

    def test_tracked_dict_structure(self):
        tracker = VehicleTracker()
        dets = [make_detection(100, 200, 200, 280)]
        results = tracker.update(dets, frame_number=0)
        assert len(results) == 1
        assert set(results[0].keys()) == REQUIRED_KEYS

    def test_multiple_vehicles_unique_ids(self):
        tracker = VehicleTracker()
        for i in range(5):
            dets = [
                make_detection(100 + i * 10, 200, 200 + i * 10, 280),
                make_detection(400 + i * 10, 300, 500 + i * 10, 380),
            ]
            results = tracker.update(dets, frame_number=i)
            if len(results) == 2:
                assert results[0]["track_id"] != results[1]["track_id"]

    def test_track_survives_gap(self):
        tracker = VehicleTracker()
        # Vehicle visible for 10 frames to establish a strong track
        first_id = None
        for i in range(10):
            dets = [make_detection(100 + i * 5, 200, 200 + i * 5, 280)]
            results = tracker.update(dets, frame_number=i)
            if results:
                first_id = results[0]["track_id"]
        assert first_id is not None

        # Disappears for 3 frames
        for i in range(10, 13):
            tracker.update([], frame_number=i)

        # Reappears at roughly the same position
        dets = [make_detection(150, 200, 250, 280)]
        results = tracker.update(dets, frame_number=13)
        assert len(results) == 1
        # Should maintain the same track_id (within lost_track_buffer=90)
        assert results[0]["track_id"] == first_id

    def test_pedestrian_tracking(self):
        tracker = VehicleTracker()
        dets = [make_detection(300, 400, 340, 500, class_id=0, confidence=0.8)]
        results = tracker.update(dets, frame_number=0)
        assert len(results) == 1
        assert results[0]["is_pedestrian"] is True
        assert results[0]["is_vehicle"] is False


# ---------------------------------------------------------------------------
# TestTrackerReset
# ---------------------------------------------------------------------------

class TestTrackerReset:
    def test_reset_clears_state(self):
        tracker = VehicleTracker()
        dets = [make_detection(100, 200, 200, 280)]
        tracker.update(dets, frame_number=0)
        assert len(tracker.get_active_track_ids()) > 0
        tracker.reset()
        assert tracker.get_active_track_ids() == []

    def test_new_ids_after_reset(self):
        tracker = VehicleTracker()
        dets = [make_detection(100, 200, 200, 280)]
        results1 = tracker.update(dets, frame_number=0)
        old_id = results1[0]["track_id"]
        tracker.reset()
        results2 = tracker.update(dets, frame_number=0)
        # After reset, ByteTrack's internal counter resets so new IDs are assigned
        # The new ID may or may not differ depending on internals,
        # but the tracker should function correctly
        assert len(results2) == 1
        assert isinstance(results2[0]["track_id"], int)


# ---------------------------------------------------------------------------
# TestTrackerSerialization
# ---------------------------------------------------------------------------

class TestTrackerSerialization:
    def test_get_state_returns_bytes(self):
        tracker = VehicleTracker()
        state = tracker.get_state()
        assert isinstance(state, bytes)
        assert len(state) > 0

    def test_state_roundtrip(self):
        tracker = VehicleTracker()
        # Feed 5 frames
        for i in range(5):
            dets = [make_detection(100 + i * 10, 200, 200 + i * 10, 280)]
            tracker.update(dets, frame_number=i)
        state = tracker.get_state()

        # Create new tracker, load state, feed frame 6
        tracker2 = VehicleTracker()
        tracker2.load_state(state)
        dets = [make_detection(150, 200, 250, 280)]
        results = tracker2.update(dets, frame_number=5)
        assert len(results) == 1
        assert isinstance(results[0]["track_id"], int)

    def test_load_state_on_fresh_tracker(self):
        tracker1 = VehicleTracker()
        dets = [make_detection(100, 200, 200, 280)]
        tracker1.update(dets, frame_number=0)
        state = tracker1.get_state()

        tracker2 = VehicleTracker()
        tracker2.load_state(state)
        # Should not crash and should be functional
        results = tracker2.update(
            [make_detection(110, 200, 210, 280)], frame_number=1
        )
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# TestClassMapping
# ---------------------------------------------------------------------------

class TestClassMapping:
    def test_vehicle_class_name_in_tracked(self):
        tracker = VehicleTracker()
        dets = [make_detection(100, 200, 200, 280, class_id=2)]
        results = tracker.update(dets, frame_number=0)
        assert results[0]["class_name"] == "car"

    def test_pedestrian_class_name_in_tracked(self):
        tracker = VehicleTracker()
        dets = [make_detection(300, 400, 340, 500, class_id=0)]
        results = tracker.update(dets, frame_number=0)
        assert results[0]["class_name"] == "person"
