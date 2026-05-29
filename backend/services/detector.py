"""YOLO vehicle detector wrapper."""

import logging
import os
from pathlib import Path

import numpy as np

# PyTorch 2.6+ defaults weights_only=True which breaks ultralytics model loading.
os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

from ultralytics import YOLO  # noqa: E402

from backend.config import (
    VEHICLE_CLASSES,
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_IMGSZ,
    YOLO_IOU_THRESHOLD,
    YOLO_MODEL,
)
from backend.services.device import detect_device

logger = logging.getLogger(__name__)
ALL_CLASSES = VEHICLE_CLASSES


class VehicleDetector:
    """Wraps YOLO inference for vehicle detection.

    Pedestrians are out of scope for v2 per PRD — only vehicle classes are
    passed to YOLO so the detector never produces pedestrian detections.

    Model / imgsz / confidence are accepted as constructor args so the
    pipeline can pick a fast vs accurate config per project without
    mutating module-level constants.
    """

    RELEVANT_CLASSES = sorted(VEHICLE_CLASSES.keys())

    def __init__(
        self,
        model_path: str | None = None,
        imgsz: int | None = None,
        confidence: float | None = None,
    ):
        """Load the YOLO model.

        Defaults pull from config (accurate mode); the v3 orchestrator
        passes per-mode overrides. Model auto-downloads on first use.
        """
        mp = model_path or YOLO_MODEL
        self.imgsz = imgsz if imgsz is not None else YOLO_IMGSZ
        self.confidence = (
            confidence if confidence is not None else YOLO_CONFIDENCE_THRESHOLD
        )
        self._device = detect_device(os.environ.get("DEVICE"))
        if self._device == "openvino":
            # Iris-Xe GPU via OpenVINO: load the exported _openvino_model (export
            # once, imgsz baked in) and run on the Intel GPU. Falls back to the
            # PyTorch .pt on CPU if export/load fails — never blocks processing.
            self.model = self._load_openvino(mp)
        else:
            self.model = YOLO(mp)

    def _load_openvino(self, model_path: str):
        """Load (exporting if needed) the OpenVINO model for the Intel GPU.
        On any failure, fall back to the PyTorch model on CPU.

        The export dir MUST keep ultralytics' '<stem>_openvino_model' suffix —
        that's how ultralytics auto-detects the OpenVINO format. imgsz is baked
        in at export, tracked via a sidecar so a different imgsz re-exports.
        (balanced=yolo26s@960 and accurate=yolo26l@1280 have different stems, so
        they don't collide in practice.)"""
        try:
            ov_dir = Path(model_path).with_suffix("").as_posix() + "_openvino_model"
            marker = Path(ov_dir) / ".imgsz"
            cur = marker.read_text().strip() if marker.exists() else None
            if not (Path(ov_dir).exists() and cur == str(self.imgsz)):
                logger.info("Exporting %s -> OpenVINO (imgsz=%d, FP16)...", model_path, self.imgsz)
                YOLO(model_path).export(format="openvino", imgsz=self.imgsz, half=True)
                marker.write_text(str(self.imgsz))
            self._device = "intel:gpu"
            return YOLO(ov_dir, task="detect")
        except Exception as e:
            logger.warning("OpenVINO load failed (%s); falling back to PyTorch CPU.", e)
            self._device = "cpu"
            return YOLO(model_path)

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
            conf=self.confidence,
            iou=YOLO_IOU_THRESHOLD,
            imgsz=self.imgsz,
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
            conf=self.confidence,
            iou=YOLO_IOU_THRESHOLD,
            imgsz=self.imgsz,
            classes=self.RELEVANT_CLASSES,
            device=self._device,
            verbose=False,
        )
        return [self._parse_results(r) for r in results]
