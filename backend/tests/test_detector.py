"""Tests for YOLOv8 vehicle detector wrapper."""

import cv2
import numpy as np
import pytest

from backend.config import PEDESTRIAN_CLASSES, VEHICLE_CLASSES
from backend.services.detector import VehicleDetector


@pytest.fixture(scope="module")
def detector():
    """Create a VehicleDetector instance (loads model once for all tests)."""
    return VehicleDetector()


def make_traffic_scene():
    """Create a 640x480 frame with car-like rectangles."""
    frame = np.full((480, 640, 3), (128, 128, 128), dtype=np.uint8)
    cv2.rectangle(frame, (100, 200), (200, 280), (0, 0, 180), -1)
    cv2.rectangle(frame, (300, 220), (420, 300), (200, 200, 200), -1)
    cv2.rectangle(frame, (450, 180), (600, 320), (50, 50, 200), -1)
    return frame


REQUIRED_KEYS = {
    "bbox", "center", "class_id", "class_name", "confidence",
    "bbox_width", "bbox_height", "bbox_area", "is_vehicle", "is_pedestrian",
}


# ---------------------------------------------------------------------------
# TestDetectorInit
# ---------------------------------------------------------------------------

class TestDetectorInit:
    def test_model_loads(self, detector):
        assert detector is not None
        assert detector.model is not None

    def test_relevant_classes(self):
        assert VehicleDetector.RELEVANT_CLASSES == [0, 1, 2, 3, 5, 7]


# ---------------------------------------------------------------------------
# TestDetect
# ---------------------------------------------------------------------------

class TestDetect:
    def test_detect_returns_list(self, detector):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = detector.detect(frame)
        assert isinstance(result, list)

    def test_detect_empty_on_solid_color(self, detector):
        frame = np.full((480, 640, 3), 255, dtype=np.uint8)
        result = detector.detect(frame)
        assert isinstance(result, list)
        for det in result:
            assert isinstance(det, dict)

    def test_detection_dict_structure(self, detector):
        frame = make_traffic_scene()
        result = detector.detect(frame)
        for det in result:
            assert set(det.keys()) == REQUIRED_KEYS

    def test_confidence_range(self, detector):
        frame = make_traffic_scene()
        result = detector.detect(frame)
        for det in result:
            assert 0.0 <= det["confidence"] <= 1.0

    def test_bbox_coordinates_valid(self, detector):
        frame = make_traffic_scene()
        result = detector.detect(frame)
        for det in result:
            x1, y1, x2, y2 = det["bbox"]
            assert x1 < x2
            assert y1 < y2

    def test_flags_exclusive(self, detector):
        frame = make_traffic_scene()
        result = detector.detect(frame)
        for det in result:
            cid = det["class_id"]
            assert det["is_vehicle"] == (cid in VEHICLE_CLASSES)
            assert det["is_pedestrian"] == (cid in PEDESTRIAN_CLASSES)
            # No class is in both maps
            assert not (det["is_vehicle"] and det["is_pedestrian"])


# ---------------------------------------------------------------------------
# TestDetectOnSyntheticScene
# ---------------------------------------------------------------------------

class TestDetectOnSyntheticScene:
    def test_detect_on_synthetic_scene(self, detector):
        frame = make_traffic_scene()
        result = detector.detect(frame)
        assert isinstance(result, list)

    def test_detect_with_different_sizes(self, detector):
        for h, w in [(240, 320), (720, 1280), (1080, 1920)]:
            frame = np.full((h, w, 3), 128, dtype=np.uint8)
            result = detector.detect(frame)
            assert isinstance(result, list)

    def test_detect_batch(self, detector):
        frames = [
            np.zeros((480, 640, 3), dtype=np.uint8),
            np.full((480, 640, 3), 128, dtype=np.uint8),
            make_traffic_scene(),
        ]
        results = detector.detect_batch(frames)
        assert len(results) == 3
        for r in results:
            assert isinstance(r, list)


# ---------------------------------------------------------------------------
# TestClassMapping
# ---------------------------------------------------------------------------

class TestClassMapping:
    def test_vehicle_class_names(self):
        assert VEHICLE_CLASSES == {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

    def test_pedestrian_class_names(self):
        assert PEDESTRIAN_CLASSES == {0: "person", 1: "bicycle"}
