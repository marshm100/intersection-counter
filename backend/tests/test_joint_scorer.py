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
    _dtw_mean,
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


def test_dtw_mean_identical_is_zero():
    curve = [(0, 0), (10, 0), (20, 5)]
    assert _dtw_mean(curve, curve) == pytest.approx(0.0, abs=1e-9)


def test_dtw_mean_parallel_offset():
    a = [(0, 0), (10, 0), (20, 0)]
    b = [(0, 3), (10, 3), (20, 3)]
    assert _dtw_mean(a, b) == pytest.approx(3.0, abs=1e-9)


def test_dtw_mean_is_robust_to_a_single_outlier_vs_frechet():
    # One spiked point should barely move the mean coupled distance, but
    # spikes the sup-norm Fréchet. This is why dtw_mean is the default.
    clean = [(float(i), 0.0) for i in range(20)]
    spiked = [(float(i), 0.0) for i in range(20)]
    spiked[10] = (10.0, 60.0)  # one big lateral jump
    frechet = _discrete_frechet(clean, spiked)
    dtw = _dtw_mean(clean, spiked)
    assert frechet >= 55.0   # sup norm sees the full spike
    assert dtw < 12.0        # mean barely moves
    assert dtw < frechet / 4


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
    assert start > 0              # matched a suffix, not the whole polyline
    assert start < len(poly) - 5  # ...an INTERNAL start, not the shortest 2-pt suffix
    assert end == len(poly) - 1   # end stays anchored at the exit


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
    # Uses the production default min_coverage_frac (0.28) — no override. A
    # higher floor would reject exactly this mid-turn case (the coverage tension).
    traj = _trace(PATHS[0]["polyline"], frac_start=0.55, step=9.0)
    r = score_path_joint(traj, PATHS)
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


# --- entry-tiebreak: shared-exit collinear disambiguation -----------------

# Two paths that MERGE to a shared exit (leg 29) and run collinear near it, but
# whose ENTRIES are 150 px apart — the cam2 SB-thru(27->29) vs EB-right(28->29)
# attribution swap in miniature. B's body lies EXACTLY on the track while A's
# bank body sits 11 px off, so under mdh (min-directed) the higher-support rival
# B ranks first — the mis-pick that rewrites origin 27 -> 28 live. The track's
# ENTRY, however, is A's. Both labelled "through" so the turn gate is not in play
# (the swap is an ORIGIN error; movement is incidental here).
TB_A = {"path_id": 1, "origin_leg_id": 27, "destination_leg_id": 29,
        "polyline": [[20, 100], [60, 100], [100, 100], [140, 100],
                     [170, 111], [200, 111], [230, 111], [260, 111], [290, 111]],
        "movement_label": "through", "supporting_count": 100}
TB_B = {"path_id": 2, "origin_leg_id": 28, "destination_leg_id": 29,
        "polyline": [[170, 100], [200, 100], [230, 100], [260, 100], [290, 100]],
        "movement_label": "through", "supporting_count": 250}
# A real origin-27 track: its own entry arm (x20..140) plus a body on the shared line.
TB_TRAJ = [(20, 100), (50, 100), (80, 100), (110, 100), (140, 100),
           (170, 100), (200, 100), (230, 100), (260, 100), (290, 100)]


def test_entry_tiebreak_recovers_origin_from_collinear_shared_exit():
    # Without the tiebreak, mdh ranks the collinear higher-support rival (B) first
    # and rewrites origin 27 -> 28 (the live cam2 EB-over / SB-under swap).
    off = score_path_joint(TB_TRAJ, [TB_A, TB_B], cost_metric="mdh",
                           entry_tiebreak=False)
    assert off["origin_leg_id"] == 28
    assert off["entry_tiebreak_applied"] is False
    # With it, the track's ENTRY (near A's) breaks the collinear tie back to 27.
    on = score_path_joint(TB_TRAJ, [TB_A, TB_B], cost_metric="mdh",
                          entry_tiebreak=True)
    assert on["origin_leg_id"] == 27
    assert on["destination_leg_id"] == 29
    assert on["entry_tiebreak_applied"] is True


def test_entry_tiebreak_is_mdh_only():
    # dtw cameras (e.g. cam3) must never trigger it — the tiebreak targets the
    # mdh min-directed relaxation specifically, so dtw stays byte-identical.
    r = score_path_joint(TB_TRAJ, [TB_A, TB_B], cost_metric="dtw_mean",
                         entry_tiebreak=True)
    assert r["entry_tiebreak_applied"] is False


def test_entry_tiebreak_needs_separated_entries():
    # If the two entries are not well separated the entry is no discriminator and
    # the tiebreak must stay out — raising the min-separation above the 150 px gap
    # disables it, so mdh's (wrong) pick stands.
    r = score_path_joint(TB_TRAJ, [TB_A, TB_B], cost_metric="mdh",
                         entry_tiebreak=True, entry_tiebreak_min_entry_sep_px=200.0)
    assert r["origin_leg_id"] == 28
    assert r["entry_tiebreak_applied"] is False


def test_entry_tiebreak_inert_on_distinct_exit_paths():
    # On the normal fixture (paths exit to DIFFERENT legs) the shared-exit cluster
    # never forms, so enabling the tiebreak changes nothing.
    traj = _trace(PATHS[0]["polyline"], step=9.0)
    base = score_path_joint(traj, PATHS, cost_metric="mdh", entry_tiebreak=False)
    tb = score_path_joint(traj, PATHS, cost_metric="mdh", entry_tiebreak=True)
    assert tb["path_id"] == base["path_id"]
    assert tb["origin_leg_id"] == base["origin_leg_id"]
    assert tb["entry_tiebreak_applied"] is False


# --- speed-tiebreak: the entry-tiebreak retry -----------------------------
# Same collinear shared-exit cluster (TB_A/TB_B), but the discriminator is each
# path's `expected_speed` signature vs the track's median step. TB_TRAJ steps are
# 30 px -> a "fast" track that matches the SB-approach signature; mdh still ranks
# the collinear rival B (origin 28) first, and speed re-picks A (origin 27).

def test_speed_tiebreak_recovers_origin_from_collinear_shared_exit():
    A = {**TB_A, "expected_speed": 28.0}   # SB-approach signature (fast)
    B = {**TB_B, "expected_speed": 8.0}    # EB-approach signature (slow)
    off = score_path_joint(TB_TRAJ, [A, B], cost_metric="mdh", speed_tiebreak=False)
    assert off["origin_leg_id"] == 28
    assert off["speed_tiebreak_applied"] is False
    on = score_path_joint(TB_TRAJ, [A, B], cost_metric="mdh", speed_tiebreak=True)
    assert on["origin_leg_id"] == 27
    assert on["destination_leg_id"] == 29
    assert on["speed_tiebreak_applied"] is True


def test_speed_tiebreak_is_mdh_only():
    A = {**TB_A, "expected_speed": 28.0}; B = {**TB_B, "expected_speed": 8.0}
    r = score_path_joint(TB_TRAJ, [A, B], cost_metric="dtw_mean", speed_tiebreak=True)
    assert r["speed_tiebreak_applied"] is False


def test_speed_tiebreak_inert_without_signatures():
    # No expected_speed on the paths -> cannot fire. Guarantees production banks
    # that don't yet carry the signature are byte-identical.
    r = score_path_joint(TB_TRAJ, [TB_A, TB_B], cost_metric="mdh", speed_tiebreak=True)
    assert r["speed_tiebreak_applied"] is False
    assert r["origin_leg_id"] == 28


def test_speed_tiebreak_needs_separated_signatures():
    # Signatures within min_sep can't discriminate -> stay out, mdh's pick stands.
    A = {**TB_A, "expected_speed": 8.5}; B = {**TB_B, "expected_speed": 8.0}
    r = score_path_joint(TB_TRAJ, [A, B], cost_metric="mdh", speed_tiebreak=True)
    assert r["speed_tiebreak_applied"] is False
    assert r["origin_leg_id"] == 28
