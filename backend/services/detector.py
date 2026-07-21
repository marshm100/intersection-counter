"""YOLO vehicle detector wrapper."""

import logging
import os
from pathlib import Path

import numpy as np

# PyTorch 2.6+ defaults weights_only=True which breaks ultralytics model loading.
os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

from ultralytics import YOLO  # noqa: E402

from backend.config import (
    NATIVE_ARTICULATED_CLASS_ID,
    NATIVE_SINGLE_UNIT_CLASS_ID,
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

    # The COCO class filter for STOCK models. The native ids (8 articulated,
    # 9 single-unit) are ours, not COCO's (boat / traffic light there) — they
    # must never reach a coco-scheme model's `classes=` request.
    RELEVANT_CLASSES = sorted(
        k for k in VEHICLE_CLASSES
        if k not in (NATIVE_ARTICULATED_CLASS_ID, NATIVE_SINGLE_UNIT_CLASS_ID))

    # Fine-tuned head schemes, keyed by class_scheme. v1 (plan_detector_
    # finetune, promoted 2026-07-17): 0 vehicle / 1 articulated / 2
    # long_single, with 0/2 keeping EXACTLY the mapping the FM51 full-chain
    # gate validated (long_single -> COCO truck + aspect subclassification)
    # and class 1 riding its own id end-to-end (plan_articulated_native).
    # v2 (plan_finetune_v2_retrain_2026-07-20): adds 3 medium, and BOTH 2/3
    # ride the native single-unit id -> FHWA 5 -> Mediums, aspect bypassed.
    _FT_CLASS_MAPS = {
        "finetune_v1": {0: 2, 1: NATIVE_ARTICULATED_CLASS_ID, 2: 7},
        "finetune_v2": {0: 2, 1: NATIVE_ARTICULATED_CLASS_ID,
                        2: NATIVE_SINGLE_UNIT_CLASS_ID,
                        3: NATIVE_SINGLE_UNIT_CLASS_ID},
    }

    def __init__(
        self,
        model_path: str | None = None,
        imgsz: int | None = None,
        confidence: float | None = None,
        class_scheme: str = "coco",
    ):
        """Load the YOLO model.

        Defaults pull from config (accurate mode); the v3 orchestrator
        passes per-mode overrides. Model auto-downloads on first use.
        class_scheme: "coco" (stock models) or a _FT_CLASS_MAPS key
        ("finetune_v1" = the promoted head, "finetune_v2" = the 4-class
        retrain); ft detections are class-mapped to chain ids.
        """
        self.class_scheme = class_scheme
        mp = model_path or YOLO_MODEL
        self.imgsz = imgsz if imgsz is not None else YOLO_IMGSZ
        self.confidence = (
            confidence if confidence is not None else YOLO_CONFIDENCE_THRESHOLD
        )
        requested = os.environ.get("DEVICE")
        self._device = detect_device(requested)
        if self._device == "openvino":
            # Iris-Xe GPU via OpenVINO: load the exported _openvino_model (export
            # once, imgsz baked in) and run on the Intel GPU.
            explicit = (requested or "").lower().strip() == "openvino"
            try:
                self.model = self._load_openvino(mp)
            except RuntimeError:
                # EXPLICIT DEVICE=openvino fails loudly (you asked for the GPU and
                # must be told it's unusable, not silently degraded). An AUTO
                # selection (no DEVICE set) degrades gracefully to PyTorch CPU so a
                # machine that never built the export still processes.
                if explicit:
                    raise
                logger.warning(
                    "OpenVINO iGPU auto-selected but its export is unavailable; "
                    "falling back to PyTorch CPU (~3.7x slower). Pre-export for the "
                    "iGPU:  py scripts/export_yolo_openvino.py --model %s --imgsz %d",
                    mp, self.imgsz,
                )
                self._device = "cpu"
                self.model = YOLO(mp)
        else:
            self.model = YOLO(mp)

    def _load_openvino(self, model_path: str):
        """Load the pre-exported OpenVINO model and run it on the Intel GPU.

        DEVICE=openvino is an EXPLICIT request — detect_device() only returns
        "openvino" when the OV runtime + an Intel GPU are both present — so a
        failure here is surfaced LOUDLY (raise), never silently degraded to CPU.
        A silent fallback once masked a missing/heavy export as a "GPU stall":
        the run quietly went CPU-bound at ~2.33 fps and the GPU got blamed. If
        you wanted the GPU and can't have it, you want to know, not to discover
        it from the throughput.

        Export is a separate, explicit step (scripts/export_yolo_openvino.py) —
        we do NOT export inside the pipeline hot path (a low-RAM in-pipeline
        export at imgsz=1280 is exactly what stalled before). The export dir
        keeps ultralytics' '<stem>_openvino_model' suffix (how ultralytics
        auto-detects the format) and a '.imgsz' sidecar records the baked-in
        imgsz so a mode/imgsz mismatch is caught here instead of mis-detecting.
        """
        ov_dir = Path(model_path).with_suffix("").as_posix() + "_openvino_model"
        marker = Path(ov_dir) / ".imgsz"
        export_cmd = (
            f"py scripts/export_yolo_openvino.py --model {model_path} --imgsz {self.imgsz}"
        )
        if not Path(ov_dir).exists():
            raise RuntimeError(
                f"DEVICE=openvino requested but no OpenVINO export at '{ov_dir}'. "
                f"Pre-export it first:  {export_cmd}"
            )
        cur = marker.read_text().strip() if marker.exists() else None
        if cur != str(self.imgsz):
            raise RuntimeError(
                f"OpenVINO export '{ov_dir}' was built for imgsz={cur}, but this "
                f"run needs imgsz={self.imgsz}. Re-export:  {export_cmd}"
            )
        model = YOLO(ov_dir, task="detect")
        self._device = "intel:gpu"
        logger.info(
            "OpenVINO detector ready on Intel GPU (intel:gpu): %s @ imgsz=%d",
            ov_dir, self.imgsz,
        )
        return model

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
            ft_map = self._FT_CLASS_MAPS.get(self.class_scheme)
            if ft_map is not None:
                class_id = ft_map.get(class_id, 2)
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
        ft_map = self._FT_CLASS_MAPS.get(self.class_scheme)
        results = self.model(
            frame,
            conf=self.confidence,
            iou=YOLO_IOU_THRESHOLD,
            imgsz=self.imgsz,
            classes=(list(ft_map) if ft_map is not None
                     else self.RELEVANT_CLASSES),
            device=self._device,
            verbose=False,
        )
        return self._parse_results(results[0])

    def detect_batch(self, frames: list[np.ndarray]) -> list[list[dict]]:
        """Run detection on multiple frames.

        CUDA/CPU torch backends get true batch inference (one model call).
        The OpenVINO export is STATIC batch-1 (static shapes are what make
        the iGPU fast — see export_yolo_openvino.py), so an N-frame tensor
        trips the intel_gpu plugin's shape check; there is no GPU batching
        to be had from that export, and per-frame calls are exactly as fast.
        """
        if not frames:
            return []
        if str(self._device).startswith("intel"):
            return [self.detect(f) for f in frames]
        ft_map = self._FT_CLASS_MAPS.get(self.class_scheme)
        results = self.model(
            frames,
            conf=self.confidence,
            iou=YOLO_IOU_THRESHOLD,
            imgsz=self.imgsz,
            classes=(list(ft_map) if ft_map is not None
                     else self.RELEVANT_CLASSES),
            device=self._device,
            verbose=False,
        )
        return [self._parse_results(r) for r in results]
