"""YOLO vehicle detector wrapper."""

import os

import numpy as np

# PyTorch 2.6+ defaults weights_only=True which breaks ultralytics model loading.
os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

from ultralytics import YOLO  # noqa: E402

from backend.config import (
    PEDESTRIAN_CLASSES,
    VEHICLE_CLASSES,
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_IMGSZ,
    YOLO_IOU_THRESHOLD,
    YOLO_MODEL,
)
from backend.services.device import detect_device

ALL_CLASSES = {**VEHICLE_CLASSES, **PEDESTRIAN_CLASSES}


class VehicleDetector:
    """Wraps YOLO inference for vehicle and pedestrian detection."""

    RELEVANT_CLASSES = sorted(set(VEHICLE_CLASSES.keys()) | set(PEDESTRIAN_CLASSES.keys()))

    def __init__(self, model_path: str | None = None):
        """Load the YOLO model.

        Defaults to YOLO_MODEL from config.
        Model auto-downloads on first use.
        """
        self.model = YOLO(model_path or YOLO_MODEL)
        self._device = detect_device(os.environ.get("DEVICE"))

    def _parse_results(self, results) -> list[dict]:
        """Extract detection dicts from a single YOLO Results object."""
        boxes = results.boxes
        if boxes is None or len(boxes) == 0:
            return []

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        cls_ids = boxes.cls.cpu().numpy().astype(int)

        detections = []
        for i in range(len(cls_ids)):
            x1, y1, x2, y2 = xyxy[i]
            class_id = int(cls_ids[i])
            w = float(x2 - x1)
            h = float(y2 - y1)
            detections.append({
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
                "center": [float((x1 + x2) / 2), float((y1 + y2) / 2)],
                "class_id": class_id,
                "class_name": ALL_CLASSES.get(class_id, f"class_{class_id}"),
                "confidence": float(confs[i]),
                "bbox_width": w,
                "bbox_height": h,
                "bbox_area": w * h,
                "is_vehicle": class_id in VEHICLE_CLASSES,
                "is_pedestrian": class_id in PEDESTRIAN_CLASSES,
            })
        return detections

    def detect(self, frame: np.ndarray) -> list[dict]:
        """Run detection on a single frame.

        Returns list of detection dicts with bbox, center, class info,
        confidence, and size metrics.

        YOLO26 uses NMS-free end-to-end inference by default (one-to-one head).
        """
        results = self.model(
            frame,
            conf=YOLO_CONFIDENCE_THRESHOLD,
            iou=YOLO_IOU_THRESHOLD,
            imgsz=YOLO_IMGSZ,
            classes=self.RELEVANT_CLASSES,
            device=self._device,
            verbose=False,
        )
        return self._parse_results(results[0])

    def detect_batch(self, frames: list[np.ndarray]) -> list[list[dict]]:
        """Run detection on multiple frames using true batch inference.

        Passes all frames to the model in a single call for GPU-parallel
        processing, then parses each result individually.
        """
        if not frames:
            return []
        results = self.model(
            frames,
            conf=YOLO_CONFIDENCE_THRESHOLD,
            iou=YOLO_IOU_THRESHOLD,
            imgsz=YOLO_IMGSZ,
            classes=self.RELEVANT_CLASSES,
            device=self._device,
            verbose=False,
        )
        return [self._parse_results(r) for r in results]
