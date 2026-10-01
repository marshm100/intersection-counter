"""THE THEFT SPLIT (config.THEFT_SPLIT, 2026-10-01): a track that follows a car
away until it is small and nearly still, then carries on with a car coming the
other way, is cut at the turning point. A U-turn (turning while moving) and a
car that stops and drives on the same way are not cut."""
import numpy as np

import backend.config as cfg
from backend.services.tracklet_linker import _cfg, split_reversals

FPS = 10.0


def _rows(pts, tid=1):
    return np.array([(tid, f, x, y, w, w * 0.5, 0.9, 2) for f, x, y, w in pts], dtype=float)


def _away_and_back():
    pts, f = [], 0
    for k in range(30):                           # away: x 100 -> 400, box 40 -> 12
        pts.append((f, 100 + 10 * k, 200, 40 - k)); f += 1
    for k in range(10):                           # nearly still at the far end
        pts.append((f, 400 + 0.2 * k, 200, 11)); f += 1
    for k in range(30):                           # back: the oncoming car, growing
        pts.append((f, 402 - 10 * k, 205, 12 + k)); f += 1
    return _rows(pts)


def test_a_far_field_hand_off_is_cut(monkeypatch):
    out, n = split_reversals(_away_and_back(), FPS, _cfg())
    assert n == 1 and len(np.unique(out[:, 0])) == 2


def test_a_u_turn_is_not_cut():
    # turns through a half circle while moving, same box size throughout
    t = np.linspace(0, np.pi, 40)
    pts = [(i, 300 + 80 * np.sin(a), 200 - 80 * np.cos(a), 40) for i, a in enumerate(t)]
    pts = [(i, 100 + 5 * i, 120, 40) for i in range(-30, 0)] + pts
    pts = [(i + 30, x, y, w) for i, x, y, w in pts]
    out, n = split_reversals(_rows(pts), FPS, _cfg())
    assert n == 0


def test_a_car_that_stops_and_drives_on_is_not_cut():
    pts = ([(f, 100 + 10 * f, 200, 40) for f in range(20)]
           + [(20 + f, 300, 200, 40) for f in range(30)]
           + [(50 + f, 300 + 10 * f, 200, 40) for f in range(20)])
    out, n = split_reversals(_rows(pts), FPS, _cfg())
    assert n == 0


def test_shipped_default_on():
    assert cfg.THEFT_SPLIT is True               # arm ts1, 2026-10-01
