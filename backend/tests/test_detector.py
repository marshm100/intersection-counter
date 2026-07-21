"""Tests for YOLO vehicle detector wrapper."""

import cv2
import numpy as np
import pytest

from backend.config import VEHICLE_CLASSES
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
    "bbox_width", "bbox_height", "bbox_area", "is_vehicle",
}


# ---------------------------------------------------------------------------
# TestDetectorInit
# ---------------------------------------------------------------------------

class TestDetectorInit:
    def test_model_loads(self, detector):
        assert detector is not None
        assert detector.model is not None

    def test_relevant_classes(self):
        # Pedestrians (classes 0=person, 1=bicycle) are out of scope for v2.
        assert VehicleDetector.RELEVANT_CLASSES == [2, 3, 5, 7]


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

    def test_is_vehicle_flag(self, detector):
        frame = make_traffic_scene()
        result = detector.detect(frame)
        for det in result:
            cid = det["class_id"]
            assert det["is_vehicle"] == (cid in VEHICLE_CLASSES)


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
        assert VEHICLE_CLASSES == {2: "car", 3: "motorcycle", 5: "bus",
                                   7: "truck", 8: "articulated_truck",
                                   9: "single_unit_truck"}

    def test_relevant_classes_exclude_native_ids(self):
        # The stock-model COCO filter must never request the synthetic ids
        # (8 = boat, 9 = traffic light in COCO).
        from backend.services.detector import VehicleDetector
        assert VehicleDetector.RELEVANT_CLASSES == [2, 3, 5, 7]


class TestFinetuneClassScheme:
    """The promoted two-class-head mapping, native-articulated revision
    (plan_articulated_native_2026-07-17): ft classes 0/1/2 -> 2/8/7 —
    0/2 exactly as the FM51 full-chain gate validated, 1 on its own
    native id so the semi signal survives to the L/M/A columns."""

    def test_parse_maps_ft_classes(self):
        import numpy as np
        from unittest.mock import MagicMock
        from backend.services.detector import VehicleDetector

        det = VehicleDetector.__new__(VehicleDetector)
        det.class_scheme = "finetune_v1"
        boxes = MagicMock()
        boxes.__len__ = lambda self: 3
        boxes.xyxy.cpu.return_value.numpy.return_value = np.array(
            [[0, 0, 10, 10], [5, 5, 40, 20], [1, 1, 30, 15]], dtype=float)
        boxes.conf.cpu.return_value.numpy.return_value = np.array([.9, .8, .7])
        boxes.cls.cpu.return_value.numpy.return_value = np.array([0, 1, 2])
        results = MagicMock(); results.boxes = boxes
        out = det._parse_results(results)
        assert [d["class_id"] for d in out] == [2, 8, 7]
        assert all(d["is_vehicle"] for d in out)
        assert out[1]["class_name"] == "articulated_truck"
        assert out[2]["class_name"] == "truck"

    def test_parse_maps_ft_v2_classes(self):
        """finetune_v2 (plan_finetune_v2_retrain_2026-07-20): 0/1 as v1;
        2 (long) AND 3 (medium) both ride the native single-unit id 9 ->
        FHWA 5 -> Mediums, aspect branch bypassed."""
        import numpy as np
        from unittest.mock import MagicMock
        from backend.services.detector import VehicleDetector

        det = VehicleDetector.__new__(VehicleDetector)
        det.class_scheme = "finetune_v2"
        boxes = MagicMock()
        boxes.__len__ = lambda self: 4
        boxes.xyxy.cpu.return_value.numpy.return_value = np.array(
            [[0, 0, 10, 10], [5, 5, 40, 20], [1, 1, 30, 15], [2, 2, 20, 12]],
            dtype=float)
        boxes.conf.cpu.return_value.numpy.return_value = np.array(
            [.9, .8, .7, .6])
        boxes.cls.cpu.return_value.numpy.return_value = np.array([0, 1, 2, 3])
        results = MagicMock(); results.boxes = boxes
        out = det._parse_results(results)
        assert [d["class_id"] for d in out] == [2, 8, 9, 9]
        assert all(d["is_vehicle"] for d in out)
        assert out[2]["class_name"] == "single_unit_truck"
        assert out[3]["class_name"] == "single_unit_truck"

    def test_coco_scheme_unchanged(self):
        import numpy as np
        from unittest.mock import MagicMock
        from backend.services.detector import VehicleDetector

        det = VehicleDetector.__new__(VehicleDetector)
        det.class_scheme = "coco"
        boxes = MagicMock()
        boxes.__len__ = lambda self: 1
        boxes.xyxy.cpu.return_value.numpy.return_value = np.array(
            [[0, 0, 10, 10]], dtype=float)
        boxes.conf.cpu.return_value.numpy.return_value = np.array([.9])
        boxes.cls.cpu.return_value.numpy.return_value = np.array([7])
        results = MagicMock(); results.boxes = boxes
        out = det._parse_results(results)
        assert out[0]["class_id"] == 7
