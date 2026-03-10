"""Unit tests for frame_annotator.render_frame_preview."""

import numpy as np
import pytest

from backend.services.frame_annotator import render_frame_preview, PREVIEW_MAX_WIDTH


def _black_frame(h: int, w: int) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


JPEG_MAGIC = b"\xff\xd8\xff"


class TestRenderFramePreview:
    def test_returns_jpeg_bytes(self):
        frame = _black_frame(480, 640)
        result = render_frame_preview(frame, [], [], [])
        assert isinstance(result, bytes)
        assert result[:3] == JPEG_MAGIC

    def test_empty_tracked_no_crash(self):
        frame = _black_frame(480, 640)
        result = render_frame_preview(frame, [], [], [])
        assert result[:3] == JPEG_MAGIC

    def test_bbox_drawn_no_crash(self):
        frame = _black_frame(480, 640)
        tracked = [
            {
                "track_id": 1,
                "class_name": "car",
                "is_vehicle": True,
                "bbox": (50, 50, 150, 150),
                "center": (100, 100),
            }
        ]
        result = render_frame_preview(frame, tracked, [], [])
        assert result[:3] == JPEG_MAGIC

    def test_origin_zones_drawn(self):
        frame = _black_frame(480, 640)
        zones = [
            [[100.0, 200.0], [300.0, 200.0]],
            [[50.0, 100.0], [200.0, 100.0]],
        ]
        legs = [{"leg_id": 1}, {"leg_id": 2}]
        result = render_frame_preview(frame, [], zones, legs)
        assert result[:3] == JPEG_MAGIC

    def test_large_frame_scaled_down(self):
        import cv2
        frame = _black_frame(1080, 1920)
        result = render_frame_preview(frame, [], [], [])
        assert result[:3] == JPEG_MAGIC
        buf = np.frombuffer(result, dtype=np.uint8)
        decoded = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        assert decoded is not None
        assert decoded.shape[1] <= PREVIEW_MAX_WIDTH

    def test_small_frame_not_upscaled(self):
        import cv2
        frame = _black_frame(240, 320)
        result = render_frame_preview(frame, [], [], [])
        assert result[:3] == JPEG_MAGIC
        buf = np.frombuffer(result, dtype=np.uint8)
        decoded = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        assert decoded is not None
        assert decoded.shape[1] == 320
