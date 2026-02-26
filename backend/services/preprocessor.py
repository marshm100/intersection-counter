"""Adaptive image preprocessor for varying lighting conditions.

Enhances frames before YOLO detection, especially for night/dusk
conditions in long recordings. Budget: <50ms per frame on target hardware.
"""

import cv2
import numpy as np


class AdaptivePreprocessor:
    """Adapts frame preprocessing to current lighting conditions."""

    def __init__(self):
        """Initialize preprocessor with CLAHE and pre-computed gamma LUTs."""
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self._gamma_luts: dict[float, np.ndarray] = {}
        for gamma in (0.4, 0.7, 1.0, 1.5):
            self._gamma_luts[gamma] = self._build_gamma_lut(gamma)

    @staticmethod
    def _build_gamma_lut(gamma: float) -> np.ndarray:
        table = np.array(
            [((i / 255.0) ** gamma) * 255 for i in range(256)],
            dtype=np.uint8,
        )
        return table

    def assess_frame(self, frame: np.ndarray) -> dict:
        """Assess current frame lighting conditions. Fast path (<5ms)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mean_b = float(gray.mean())
        std_b = float(gray.std())
        contrast = std_b / mean_b if mean_b > 0 else 0.0

        is_night = mean_b < 50
        is_dark = mean_b < 80
        is_bright = mean_b > 200
        is_low_contrast = contrast < 0.3

        if mean_b < 50:
            condition = "night"
        elif mean_b < 80:
            condition = "dusk"
        elif mean_b > 200:
            condition = "overexposed"
        else:
            condition = "day"

        return {
            "brightness": mean_b,
            "contrast": contrast,
            "is_night": is_night,
            "is_dark": is_dark,
            "is_bright": is_bright,
            "is_low_contrast": is_low_contrast,
            "condition": condition,
        }

    def preprocess(
        self, frame: np.ndarray, assessment: dict | None = None
    ) -> np.ndarray:
        """Apply adaptive preprocessing based on frame assessment.

        - day with good contrast: return unchanged (0ms)
        - day with low contrast: CLAHE on L channel (~10ms)
        - dusk: CLAHE + gamma=0.7 (~15ms)
        - night: CLAHE + gamma=0.4 (~15ms)
        - overexposed: gamma=1.5 (~5ms)
        """
        if assessment is None:
            assessment = self.assess_frame(frame)

        condition = assessment["condition"]
        low_contrast = assessment["is_low_contrast"]

        if condition == "day" and not low_contrast:
            return frame

        if condition == "day" and low_contrast:
            return self._apply_clahe_lab(frame)

        if condition == "dusk":
            out = self._apply_clahe_lab(frame)
            return self._gamma_correction(out, 0.7)

        if condition == "night":
            out = self._apply_clahe_lab(frame)
            return self._gamma_correction(out, 0.4)

        if condition == "overexposed":
            return self._gamma_correction(frame, 1.5)

        return frame

    def _apply_clahe_lab(self, frame: np.ndarray) -> np.ndarray:
        """Apply CLAHE to the L channel of LAB color space."""
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        l_ch = self._clahe.apply(l_ch)
        lab = cv2.merge([l_ch, a_ch, b_ch])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    def _gamma_correction(self, frame: np.ndarray, gamma: float) -> np.ndarray:
        """Apply gamma correction using pre-computed or on-demand LUT."""
        lut = self._gamma_luts.get(gamma)
        if lut is None:
            lut = self._build_gamma_lut(gamma)
            self._gamma_luts[gamma] = lut
        return cv2.LUT(frame, lut)
