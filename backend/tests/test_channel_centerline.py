"""Unit tests for the operator-channel centerline sampler (drawn-direct bank).

The full drawn-direct BUILD behavior (channel cells bypass fit/dedup/bearing
gates; U-turn support gate) is validated end-to-end via the CLI
`scripts/build_bank_gtfree.py` against the detection cache — the project's
convention for the builder's output. Here we pin the one genuinely-new PURE
helper: the sampler that must reproduce the calibration UI's rendered curve
(frontend/js/calibration.js `_chCtrl` + `_chQuadAt`) so the operator's drawn
template is used verbatim, not a piecewise-linear approximation of it.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_bank_gtfree import _channel_centerline


def test_endpoints_are_entry_and_exit():
    p = _channel_centerline([1, 2], [5, 9], [11, 3], 15)
    assert p[0] == [1.0, 2.0]
    assert p[-1] == [11.0, 3.0]


def test_curve_passes_through_drawn_apex_at_midpoint():
    # Odd count -> the exact t=0.5 sample is the middle point; the UI's control
    # point (2*apex - (entry+exit)/2) makes the Bezier pass through the drawn
    # apex there. This is the property that keeps the template faithful.
    p = _channel_centerline([0, 0], [5, 10], [10, 0], 5)
    assert p[2] == [5.0, 10.0]


def test_point_count_matches_request():
    for n in (5, 15, 26):
        assert len(_channel_centerline([0, 0], [3, 4], [10, 1], n)) == n


def test_no_apex_is_straight_line():
    assert _channel_centerline([0, 0], None, [10, 0], 3) == [[0.0, 0.0], [5.0, 0.0], [10.0, 0.0]]


def test_matches_ui_quadratic_bezier_formula():
    # Independent re-derivation of the UI math for every sample point.
    entry, apex, exit_ = [2, 3], [7, 12], [14, 5]
    cx = 2 * apex[0] - (entry[0] + exit_[0]) / 2
    cy = 2 * apex[1] - (entry[1] + exit_[1]) / 2
    n = 15
    p = _channel_centerline(entry, apex, exit_, n)
    for i in range(n):
        t = i / (n - 1)
        u = 1 - t
        ex = u * u * entry[0] + 2 * u * t * cx + t * t * exit_[0]
        ey = u * u * entry[1] + 2 * u * t * cy + t * t * exit_[1]
        assert math.isclose(p[i][0], round(ex, 1), abs_tol=0.06)
        assert math.isclose(p[i][1], round(ey, 1), abs_tol=0.06)
