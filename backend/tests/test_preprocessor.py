"""Tests for adaptive image preprocessor."""

import cv2
import numpy as np
import pytest

from backend.services.preprocessor import AdaptivePreprocessor


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def make_dark_frame(width=640, height=480, brightness=30):
    """Create a uniformly dark frame."""
    return np.full((height, width, 3), brightness, dtype=np.uint8)


def make_bright_frame(width=640, height=480, brightness=220):
    """Create a uniformly bright frame."""
    return np.full((height, width, 3), brightness, dtype=np.uint8)


def make_normal_frame(width=640, height=480, brightness=128):
    """Create a normal-brightness frame with some variation."""
    rng = np.random.RandomState(42)
    lo = max(0, brightness - 40)
    hi = min(255, brightness + 40)
    return rng.randint(lo, hi + 1, (height, width, 3)).astype(np.uint8)


def mean_brightness(frame):
    """Get mean brightness of a frame."""
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()


@pytest.fixture
def preprocessor():
    return AdaptivePreprocessor()


# ---------------------------------------------------------------------------
# TestAssessFrame
# ---------------------------------------------------------------------------

class TestAssessFrame:
    def test_night_detection(self, preprocessor):
        frame = make_dark_frame(brightness=30)
        a = preprocessor.assess_frame(frame)
        assert a["is_night"] is True
        assert a["condition"] == "night"

    def test_dusk_detection(self, preprocessor):
        frame = make_dark_frame(brightness=65)
        a = preprocessor.assess_frame(frame)
        assert a["is_dark"] is True
        assert a["condition"] == "dusk"

    def test_day_detection(self, preprocessor):
        frame = make_normal_frame(brightness=128)
        a = preprocessor.assess_frame(frame)
        assert a["condition"] == "day"

    def test_overexposed_detection(self, preprocessor):
        frame = make_bright_frame(brightness=220)
        a = preprocessor.assess_frame(frame)
        assert a["is_bright"] is True
        assert a["condition"] == "overexposed"

    def test_brightness_range(self, preprocessor):
        for b in [10, 65, 128, 230]:
            frame = np.full((100, 100, 3), b, dtype=np.uint8)
            a = preprocessor.assess_frame(frame)
            assert 0 <= a["brightness"] <= 255

    def test_contrast_nonnegative(self, preprocessor):
        frame = make_normal_frame()
        a = preprocessor.assess_frame(frame)
        assert a["contrast"] >= 0


# ---------------------------------------------------------------------------
# TestPreprocess
# ---------------------------------------------------------------------------

class TestPreprocess:
    def test_night_frame_brightened(self, preprocessor):
        frame = make_dark_frame(brightness=30)
        orig_b = mean_brightness(frame)
        out = preprocessor.preprocess(frame)
        assert mean_brightness(out) > orig_b

    def test_day_frame_unchanged_or_similar(self, preprocessor):
        frame = make_normal_frame(brightness=128)
        orig_b = mean_brightness(frame)
        out = preprocessor.preprocess(frame)
        assert abs(mean_brightness(out) - orig_b) < 20

    def test_overexposed_darkened(self, preprocessor):
        frame = make_bright_frame(brightness=220)
        orig_b = mean_brightness(frame)
        out = preprocessor.preprocess(frame)
        assert mean_brightness(out) < orig_b

    def test_output_shape_matches_input(self, preprocessor):
        for shape in [(480, 640, 3), (720, 1280, 3), (1080, 1920, 3)]:
            frame = np.full(shape, 60, dtype=np.uint8)
            out = preprocessor.preprocess(frame)
            assert out.shape == frame.shape
            assert out.dtype == frame.dtype

    def test_output_valid_range(self, preprocessor):
        frame = make_dark_frame(brightness=30)
        out = preprocessor.preprocess(frame)
        assert out.min() >= 0
        assert out.max() <= 255

    def test_preprocess_with_explicit_assessment(self, preprocessor):
        frame = make_dark_frame(brightness=30)
        assessment = preprocessor.assess_frame(frame)
        out = preprocessor.preprocess(frame, assessment=assessment)
        assert mean_brightness(out) > mean_brightness(frame)


# ---------------------------------------------------------------------------
# TestGammaCorrection
# ---------------------------------------------------------------------------

class TestGammaCorrection:
    def test_gamma_brightens(self, preprocessor):
        frame = make_dark_frame(brightness=60)
        out = preprocessor._gamma_correction(frame, 0.4)
        assert mean_brightness(out) > mean_brightness(frame)

    def test_gamma_darkens(self, preprocessor):
        frame = make_bright_frame(brightness=200)
        out = preprocessor._gamma_correction(frame, 1.5)
        assert mean_brightness(out) < mean_brightness(frame)


# ---------------------------------------------------------------------------
# TestPerformance
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_preprocess_speed(self, preprocessor):
        # Verify no crash on 1080p; <50ms target on real hardware
        frame = np.full((1080, 1920, 3), 40, dtype=np.uint8)
        out = preprocessor.preprocess(frame)
        assert out.shape == frame.shape
