"""BORN AT THE MOUTH (config.BORN_AT_MOUTH, 2026-10-01): a track first seen
just past an entry line, moving inward and holding a real exit, entered over
that line. A track first seen mid-box (from behind another vehicle) does not
get an origin this way (the G-DEF-7 failure)."""
import backend.config as cfg
from backend.services.entry_gates import classify_pair

FPS = 10.0
GATES = {   # the test_state_machine box: N left (x=200), S right (x=800), W bottom
    1: ((200.0, 100.0), (200.0, 500.0), (1.0, 0.0)),
    2: ((800.0, 100.0), (800.0, 500.0), (-1.0, 0.0)),
    3: ((300.0, 600.0), (700.0, 600.0), (0.0, -1.0)),
}
HALF_W = 15.0                              # box width 30


def _pair(x0, x1, y=300.0, n=40):
    centre = [(float(i), x0 + (x1 - x0) * i / (n - 1), y) for i in range(n)]
    l = [(f, x - HALF_W, y) for f, x, y in centre]
    r = [(f, x + HALF_W, y) for f, x, y in centre]
    return classify_pair(l, r, GATES, FPS)


def test_default_off_keeps_exit_only():
    assert cfg.BORN_AT_MOUTH is False
    *_rest, tag = _pair(225.0, 850.0)
    assert tag == "exit_only"


def test_born_just_past_the_line_entered_over_it(monkeypatch):
    monkeypatch.setattr(cfg, "BORN_AT_MOUTH", True)
    o, d, fo, fd, *_rest, tag = _pair(225.0, 850.0)       # 25 px past N, width 30
    assert (o, d, tag) == (1, 2, "full") and fo < fd


def test_born_mid_box_gets_no_origin(monkeypatch):
    monkeypatch.setattr(cfg, "BORN_AT_MOUTH", True)
    *_rest, tag = _pair(500.0, 850.0)                     # 300 px from N
    assert tag == "exit_only"
