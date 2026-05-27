"""Unit tests for the joint partial-Fréchet path scorer (Attribution v2).

Covers backend/services/trajectory_classifier.py:
  - _discrete_frechet, _densify_polyline, _resample_to (helpers)
  - _best_partial_frechet (suffix sub-curve search — the mid-turn-entry fix)
  - score_path_joint (origin/dest/movement read off the winning path)

The scenarios encode the real failure mode this scorer exists to fix: a
trajectory that only sees the BACK HALF of a movement (vehicle enters YOLO's
FOV mid-turn) must still match the correct full path by its suffix, and origin
must be read off that path rather than estimated from the (turn-state) entry.
"""
import math

import pytest

from backend.services.trajectory_classifier import (
    _best_partial_frechet,
    _densify_polyline,
    _discrete_frechet,
    _resample_to,
    score_path_joint,
)


# Two clearly distinct movements sharing the L18 origin so the scorer must
# discriminate by SHAPE, not just endpoint. Listed entry -> exit.
PATHS = [
    # L18 -> L19 THROUGH: comes in upper-right, sweeps down-left across frame.
    {"path_id": 1, "origin_leg_id": 18, "destination_leg_id": 19,
     "polyline": [[610, 180], [500, 200], [400, 235], [300, 290],
                  [200, 335], [85, 370], [10, 410]],
     "movement_label": "through", "supporting_count": 250},
    # L18 -> L21 RIGHT: same start, but bends toward upper-middle and stops.
    {"path_id": 3, "origin_leg_id": 18, "destination_leg_id": 21,
     "polyline": [[610, 180], [500, 200], [400, 220], [320, 230],
                  [250, 235], [217, 234], [180, 230]],
     "movement_label": "right", "supporting_count": 80},
    # L19 -> L18 THROUGH: the reverse sweep (different origin entirely).
    {"path_id": 2, "origin_leg_id": 19, "destination_leg_id": 18,
     "polyline": [[10, 410], [85, 370], [200, 335], [300, 290],
                  [400, 235], [500, 200], [610, 180]],
     "movement_label": "through", "supporting_count": 230},
]


def _trace(polyline, *, frac_start=0.0, frac_end=1.0, step=8.0, jitter=0.0):
    """Synthesize a trajectory that follows a fraction of a polyline.

    frac_start/frac_end select the arc-length window covered (so frac_start=0.5
    simulates a track that only sees the back half — the mid-turn-entry case).
    """
    dense = _densify_polyline(polyline, step)
    n = len(dense)
    a = int(frac_start * (n - 1))
    b = int(frac_end * (n - 1))
    pts = dense[a:b + 1]
    if jitter:
        pts = [(x + jitter * math.sin(i), y + jitter * math.cos(i))
               for i, (x, y) in enumerate(pts)]
    return pts


# --- helpers -------------------------------------------------------------

def test_discrete_frechet_identical_is_zero():
    curve = [(0, 0), (10, 0), (20, 5)]
    assert _discrete_frechet(curve, curve) == pytest.approx(0.0, abs=1e-9)


def test_discrete_frechet_parallel_offset():
    a = [(0, 0), (10, 0), (20, 0)]
    b = [(0, 3), (10, 3), (20, 3)]
    assert _discrete_frechet(a, b) == pytest.approx(3.0, abs=1e-9)


def test_densify_preserves_arc_length():
    poly = [[0, 0], [100, 0], [100, 100]]
    dense = _densify_polyline(poly, 10.0)
    # arc length ~200; densified should reproduce it closely.
    length = sum(math.dist(dense[i], dense[i + 1]) for i in range(len(dense) - 1))
    assert length == pytest.approx(200.0, rel=0.02)
    assert len(dense) > 10


def test_resample_caps_length():
    pts = [(i, i) for i in range(100)]
    out = _resample_to(pts, 25)
    assert len(out) == 25
    assert out[0] == (0.0, 0.0)
    assert out[-1] == (99.0, 99.0)


def test_best_partial_frechet_matches_suffix():
    poly = _densify_polyline(PATHS[0]["polyline"], 12.0)
    # Trajectory covering only the back 40% of the path.
    traj = _trace(PATHS[0]["polyline"], frac_start=0.6, step=10.0)
    start, end, cost = _best_partial_frechet(traj, poly)
    assert cost < 8.0  # follows the suffix closely
    assert start > 0   # matched a suffix, not the whole polyline


# --- score_path_joint ----------------------------------------------------

def test_full_through_trajectory_picks_through_path():
    traj = _trace(PATHS[0]["polyline"], step=9.0)
    r = score_path_joint(traj, PATHS)
    assert r["path_id"] == 1
    assert r["origin_leg_id"] == 18
    assert r["destination_leg_id"] == 19
    assert r["movement_label"] == "through"


def test_full_right_turn_picks_right_path_over_through():
    # The right turn shares L18's origin + entry with the through; only the
    # shape downstream distinguishes them. Shape must win.
    traj = _trace(PATHS[1]["polyline"], step=9.0)
    r = score_path_joint(traj, PATHS)
    assert r["path_id"] == 3
    assert r["movement_label"] == "right"
    assert r["destination_leg_id"] == 21


def test_mid_turn_entry_still_picks_correct_path_and_origin():
    # THE core scenario: vehicle only seen for the back 45% of the through
    # movement. Origin (L18) must be READ OFF the path, not estimated from the
    # entry tangent (which here would look like mid-sweep, not an approach).
    traj = _trace(PATHS[0]["polyline"], frac_start=0.55, step=9.0)
    r = score_path_joint(traj, PATHS, min_coverage_frac=0.35)
    assert r["path_id"] == 1
    assert r["origin_leg_id"] == 18
    assert r["movement_label"] == "through"


def test_low_coverage_fragment_is_rejected():
    # A tiny snippet matching only ~10% of any path must not attribute.
    traj = _trace(PATHS[0]["polyline"], frac_start=0.45, frac_end=0.55, step=9.0)
    r = score_path_joint(traj, PATHS, min_coverage_frac=0.45)
    assert r["origin_leg_id"] is None


def test_far_trajectory_rejected_by_max_cost():
    traj = [(0, 0), (5, 0), (10, 0), (15, 0), (20, 0)]  # nowhere near any path
    r = score_path_joint(traj, PATHS, max_cost=28.0)
    assert r["origin_leg_id"] is None


def test_too_short_trajectory_returns_empty():
    r = score_path_joint([(610, 180), (500, 200)], PATHS)
    assert r["origin_leg_id"] is None
    assert r["considered"] == 0


def test_no_paths_returns_empty():
    traj = _trace(PATHS[0]["polyline"], step=9.0)
    r = score_path_joint(traj, [])
    assert r["origin_leg_id"] is None
