"""THE GRAZED EXIT (config.EXIT_GRAZE_SKIP, 2026-10-02): a track that crosses
an exit line and then rides ALONG it did not leave through it (cam5's NB
throughs along the E line). A track that crosses and moves away outward did."""
import backend.config as cfg
from backend.services.entry_gates import classify_pair, rides_line_after

FPS = 10.0
GATES = {   # N left (x=200), S right (x=800), E top (y=100)
    1: ((200.0, 100.0), (200.0, 500.0), (1.0, 0.0)),
    2: ((800.0, 100.0), (800.0, 500.0), (-1.0, 0.0)),
    4: ((300.0, 100.0), (700.0, 100.0), (0.0, 1.0)),
}
HALF_W = 15.0


def _path(knots, per_leg=20):
    pts, f = [], 0.0
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        for i in range(per_leg):
            t = i / per_leg
            pts.append((f, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            f += 1.0
    pts.append((f, *knots[-1]))
    return pts


def _pair(knots):
    centre = _path(knots)
    l = [(f, x - HALF_W, y) for f, x, y in centre]
    r = [(f, x + HALF_W, y) for f, x, y in centre]
    return classify_pair(l, r, GATES, FPS)


GRAZE = [(150.0, 300.0), (380.0, 110.0), (420.0, 96.0), (850.0, 92.0)]
EXIT = [(150.0, 300.0), (450.0, 110.0), (500.0, 30.0)]


def test_default_off_takes_the_grazed_line():
    assert cfg.EXIT_GRAZE_SKIP is False
    o, d, *_rest, tag = _pair(GRAZE)
    assert (o, d, tag) == (1, 4, "full")


def test_graze_skipped_finds_the_real_exit(monkeypatch):
    monkeypatch.setattr(cfg, "EXIT_GRAZE_SKIP", True)
    o, d, *_rest, tag = _pair(GRAZE)
    assert (o, d, tag) == (1, 2, "full")


def test_real_exit_kept(monkeypatch):
    monkeypatch.setattr(cfg, "EXIT_GRAZE_SKIP", True)
    o, d, *_rest, tag = _pair(EXIT)
    assert (o, d, tag) == (1, 4, "full")


def test_graze_with_no_later_exit_stands(monkeypatch):
    monkeypatch.setattr(cfg, "EXIT_GRAZE_SKIP", True)
    o, d, *_rest, tag = _pair([(150.0, 300.0), (380.0, 110.0), (420.0, 96.0), (760.0, 92.0)])
    assert (o, d, tag) == (1, 4, "full")        # ends before S: the E exit stands


def test_graze_never_becomes_a_uturn(monkeypatch):
    monkeypatch.setattr(cfg, "EXIT_GRAZE_SKIP", True)
    o, d, *_rest, tag = _pair([(150.0, 300.0), (380.0, 110.0), (420.0, 96.0),
                               (760.0, 92.0), (300.0, 92.0), (150.0, 200.0)])
    assert (o, d, tag) == (1, 4, "full")        # back out over its own N line: not a u-turn


def test_rides_line_measure():
    track = _path(GRAZE)
    assert rides_line_after(track, (45.0, 4, False, (406.0, 100.0)), GATES)
    assert not rides_line_after(_path(EXIT), (20.0, 4, False, (450.0, 100.0)), GATES)
