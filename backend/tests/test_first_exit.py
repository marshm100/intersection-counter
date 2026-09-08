"""THE FIRST-EXIT RULE (operator ruling 2026-09-08).

"it crosses the n and then crosses the s... it may kind of jitter over
the s a bit, but it never goes all the way back to n. And it shouldn't
matter because it went from n to s, period."

A journey ends at its first LEGITIMATE exit. A different-leg exit is
legitimate at once; a same-leg exit only if it is a real u-turn.
"""
import backend.config as cfg
import pytest

from backend.services.entry_gates import classify

FPS = 10.0
# A box intersection: N gate on the left, S gate on the right, W gate
# at the bottom. Inward normals point at the centre (500, 300).
GATES = {
    1: ((200.0, 100.0), (200.0, 500.0), (1.0, 0.0)),      # N (left)
    2: ((800.0, 100.0), (800.0, 500.0), (-1.0, 0.0)),     # S (right)
    3: ((300.0, 600.0), (700.0, 600.0), (0.0, -1.0)),     # W (bottom)
}


def _leg(track):
    return classify(track, GATES, FPS)


def _line(x0, x1, y, f0, n=40):
    return [(float(f0 + i), x0 + (x1 - x0) * i / (n - 1), float(y))
            for i in range(n)]


@pytest.fixture
def rule_on(monkeypatch):
    monkeypatch.setattr(cfg, "JOURNEY_FIRST_EXIT", True)


class TestFirstExit:
    def test_theft_after_the_journey_cannot_rewrite_it(self, rule_on):
        # the operator's filmed case: in over N, out over S (journey
        # done), then MUCH later the stolen box comes back across N.
        t = _line(150.0, 850.0, 300.0, 0)          # N-in ... S-out
        t += _line(850.0, 150.0, 320.0, 900)       # theft: back across N
        o, d, *_rest, tag = _leg(t)
        assert (o, d) == (1, 2) and tag == "full"   # N -> S, a through

    def test_flag_off_loses_the_through(self, monkeypatch):
        # With the flag off the LAST exit wins, so the finished N->S
        # journey is destroyed by the later theft: the answer is
        # anything but the correct through. (On real tracks the theft
        # has enough dwell to score a u_turn outright; this synthetic
        # falls to entry_only. Either way the through is lost.)
        monkeypatch.setattr(cfg, "JOURNEY_FIRST_EXIT", False)
        t = _line(150.0, 850.0, 300.0, 0)
        t += _line(850.0, 150.0, 320.0, 900)
        o, d, *_rest = _leg(t)
        assert (o, d) != (1, 2)

    def test_genuine_uturn_survives(self, rule_on):
        # in over N, deep excursion, long dwell, out over N in the
        # opposite lane -> still a u-turn
        t = _line(150.0, 600.0, 280.0, 0)           # well past the gate
        t += [(float(100 + i), 600.0, 280.0 + i) for i in range(80)]
        t += _line(600.0, 150.0, 360.0, 200)        # back out over N
        o, d, *_rest, tag = _leg(t)
        assert (o, d) == (1, 1) and tag == "full"

    def test_same_leg_graze_is_skipped_for_the_real_exit(self, rule_on):
        # the cam2 trap: in over N, immediately grazes back over N
        # (no dwell, no excursion), then really exits over S.
        t = _line(150.0, 260.0, 300.0, 0, n=8)      # in over N
        t += _line(260.0, 150.0, 302.0, 8, n=6)     # graze back out
        t += _line(150.0, 850.0, 304.0, 20)         # the real journey
        o, d, *_rest, tag = _leg(t)
        assert (o, d) == (1, 2) and tag == "full"   # N -> S, not N -> N

    def test_no_exit_after_entry_is_entry_only(self, rule_on):
        t = _line(150.0, 500.0, 300.0, 0)
        o, d, *_rest, tag = _leg(t)
        assert o == 1 and d is None and tag == "entry_only"
