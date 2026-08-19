"""Fold gate for path establishment (operator ruling 2026-08-19).

The operator found live confirmed paths carrying near-reversals ("two
sharp angles ... disqualifying") — splice-shaped trajectories had voted
on the fitted shape AND inflated the support counts. These tests pin the
three layers of the fix: the concentrated-turn measure itself, member
exclusion (with u-turn exemption) inside discover_paths, and the
fitted-output backstop."""
import sys

import pytest

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.path_shape import (                        # noqa: E402
    MEMBER_PINCH_DEG, PATH_FOLD_REJECT_DEG, max_concentrated_turn)
import auto_calibrate as ac                                      # noqa: E402

ZA = {"zone_id": 1, "centroid": (0.0, 0.0)}
ZB = {"zone_id": 2, "centroid": (400.0, 0.0)}
ZC = {"zone_id": 3, "centroid": (150.0, 150.0)}


def _line(p0, p1, n=30):
    return [(p0[0] + (p1[0] - p0[0]) * i / (n - 1),
             p0[1] + (p1[1] - p0[1]) * i / (n - 1)) for i in range(n)]


def _arc(cx, cy, r, deg0, deg1, n=40):
    import math
    out = []
    for i in range(n):
        t = math.radians(deg0 + (deg1 - deg0) * i / (n - 1))
        out.append((cx + r * math.sin(t), cy - r * math.cos(t)))
    return out


class TestMaxConcentratedTurn:
    def test_straight_is_flat(self):
        assert max_concentrated_turn(_line((0, 0), (400, 0))) < 5.0

    def test_smooth_quarter_turn_stays_under_gate(self):
        # r=150 arc: ~90 deg total spread across ~9 chords of 25 px
        arc = _arc(0, 150, 150, 0, 90)
        assert max_concentrated_turn(arc) < PATH_FOLD_REJECT_DEG

    def test_fold_trips_both_thresholds(self):
        fold = _line((0, 0), (400, 0), 20) + _line((400, 0), (0, 40), 20)[1:]
        v = max_concentrated_turn(fold)
        assert v >= PATH_FOLD_REJECT_DEG
        assert v >= MEMBER_PINCH_DEG

    def test_stationary_jitter_cannot_fake_a_turn(self):
        # never accumulates two 25 px displacement chords
        jitter = [(0, 0), (3, 4), (1, 1), (4, 2), (0, 3), (2, 0)] * 6
        assert max_concentrated_turn(jitter) == 0.0

    def test_too_short_is_zero(self):
        assert max_concentrated_turn([]) == 0.0
        assert max_concentrated_turn([(0, 0), (100, 0)]) == 0.0


class TestDiscoverPathsFoldGate:
    def test_pinched_members_excluded_and_support_deflated(self):
        # 12 clean throughs A->B + 9 splices that END in B (the thief's
        # exit) — the raw fitter would have reported support 21.
        clean = [_line((0, 0), (400, 0)) for _ in range(12)]
        pinched = [_line((0, 0), (460, 15), 20)
                   + _line((460, 15), (400, 0), 6)[1:] for _ in range(9)]
        stats = {}
        paths = ac.discover_paths(clean + pinched, [ZA], [ZB],
                                  stats_out=stats)
        assert len(paths) == 1
        assert paths[0]["supporting_count"] == 12
        assert "shape_flag" not in paths[0]
        assert stats["members_excluded_pinched"] == 9
        assert stats["paths_rejected_folded"] == []

    def test_folded_fit_rejected_by_backstop(self, monkeypatch):
        # members individually pass the gate; force the FIT to fold (the
        # median-of-mixture case) and assert the output backstop drops it
        fold = _line((0, 0), (400, 0), 8) + _line((400, 0), (0, 40), 7)[1:]
        monkeypatch.setattr(ac, "_fit_mean_polyline", lambda g, n: fold)
        members = [_line((0, 0), (400, 0)) for _ in range(10)]
        stats = {}
        paths = ac.discover_paths(members, [ZA], [ZB], stats_out=stats)
        assert paths == []
        rej = stats["paths_rejected_folded"]
        assert len(rej) == 1
        assert rej[0]["entry_zone_id"] == 1
        assert rej[0]["exit_zone_id"] == 2
        assert rej[0]["max_turn_deg"] >= PATH_FOLD_REJECT_DEG

    def test_uturn_exempt_from_member_gate_but_flagged(self):
        # hairpins out and back to the SAME zone: legitimately sharp —
        # kept (member gate exempts same-zone) but flagged for the UI
        hairpins = [_line((0, 0), (300, 0), 15)
                    + _line((300, 0), (10, 40), 15)[1:] for _ in range(10)]
        stats = {}
        paths = ac.discover_paths(hairpins, [ZA], [ZA, ZB],
                                  stats_out=stats)
        assert len(paths) == 1
        assert paths[0]["entry_zone_id"] == paths[0]["exit_zone_id"] == 1
        assert paths[0]["shape_flag"] == "concentrated_reversal"
        assert stats["members_excluded_pinched"] == 0

    def test_smooth_turn_passes_untouched(self):
        turns = [_arc(0, 150, 150, 0, 90) for _ in range(10)]
        stats = {}
        paths = ac.discover_paths(turns, [ZA], [ZC], stats_out=stats)
        assert len(paths) == 1
        assert "shape_flag" not in paths[0]
        assert stats["members_excluded_pinched"] == 0
        assert stats["paths_rejected_folded"] == []

    def test_stats_out_optional(self):
        clean = [_line((0, 0), (400, 0)) for _ in range(10)]
        paths = ac.discover_paths(clean, [ZA], [ZB])
        assert len(paths) == 1
