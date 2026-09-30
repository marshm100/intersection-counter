"""THE GLOBAL TRACKLET LINKER (config.TRACKLET_LINKER, 2026-09-30): one global
assignment of piece tails to piece heads, gates in seconds and box units, the
follower test, and birth / death costs from the gate lines."""
import numpy as np
import pytest

from backend.services.entry_gates import build_gates
from backend.services.tracklet_linker import link_rows

# the synthetic box from test_fracture_dedup: 4 legs, N-S + W-E channels
LEGS = {1: (50.0, 0.0), 2: (100.0, 50.0), 3: (50.0, 100.0), 4: (0.0, 50.0)}
PATHS = [{"origin_leg_id": 1, "destination_leg_id": 3,
          "polyline": [[50, -20], [50, 120]]},
         {"origin_leg_id": 4, "destination_leg_id": 2,
          "polyline": [[-20, 50], [120, 50]]}]
HEAD = {1: 180.0, 2: 270.0, 3: 0.0, 4: 90.0}
BOX = 10.0


@pytest.fixture(scope="module")
def gates():
    return build_gates(LEGS, PATHS, HEAD)


def _rows(tid, pts, box=BOX):
    return [(float(tid), f, x, y, box, box, 0.9, 2.0) for f, x, y in pts]


def _run(gates, *tracks, fps=10.0):
    rows = np.array([r for t in tracks for r in t], dtype=float)
    out, fams, stats = link_rows(rows, fps, gates, frame_size=(400, 400))
    ids = {int(t) for t in np.unique(out[:, 0])}
    return out, fams, stats, ids


# A: in over gate 1 at 20 px/s (2 px a frame), lost mid-box at frame 29, y 53
A = [(float(f), 50.0, -5.0 + 2.0 * f) for f in range(30)]
# B: the same car re-found 1.5 s later where A WOULD BE (53 + 2 x 15 = 83),
# carrying on out over gate 3
B = [(44.0 + f, 50.0, 83.0 + 2.0 * f) for f in range(25)]


def test_an_occluded_car_becomes_one_track(gates):
    out, fams, stats, ids = _run(gates, _rows(1, A), _rows(2, B))
    assert ids == {1} and fams == {1: [1, 2]}
    assert stats["absorbed"] == 1


def test_the_next_car_in_the_queue_is_not_linked(gates):
    # born where A WAS (its death point), 1.5 s later: the follower
    follower = [(44.0 + f, 50.0, 53.0 + 2.0 * f) for f in range(30)]
    out, fams, stats, ids = _run(gates, _rows(1, A), _rows(2, follower))
    assert ids == {1, 2} and fams == {}


def test_two_complete_journeys_are_never_joined(gates):
    full1 = [(float(f), 50.0, -5.0 + 6.0 * f) for f in range(20)]      # in 1, out 3
    full2 = [(21.0 + f, 50.0, -5.0 + 6.0 * f) for f in range(20)]      # the next car
    out, fams, stats, ids = _run(gates, _rows(1, full1), _rows(2, full2))
    assert ids == {1, 2}


def test_opposite_heading_is_not_linked(gates):
    back = [(44.0 + f, 50.0, 83.0 - 2.0 * f) for f in range(25)]
    out, fams, stats, ids = _run(gates, _rows(1, A), _rows(2, back))
    assert ids == {1, 2}


def test_a_car_stopped_at_a_red_light_is_rejoined_across_the_wait(gates, monkeypatch):
    import backend.config as cfg
    monkeypatch.setattr(cfg, "LINKER_STOPPED_LEVEL", True)     # shipped OFF
    stop = [(float(f), 50.0, min(-5.0 + 2.0 * f, 40.0)) for f in range(60)]  # stopped at y 40
    go = [(260.0 + f, 50.0, 40.0 + 3.0 * f) for f in range(25)]            # 20 s later, same spot
    out, fams, stats, ids = _run(gates, _rows(1, stop), _rows(2, go))
    assert ids == {1} and stats["bridged_links"] == 1
    fr = np.sort(out[:, 1])
    assert np.max(np.diff(fr)) <= 10              # held rows keep the replay from splitting it


def test_the_same_scene_at_25_fps_gives_the_same_answer(gates):
    k = 2.5
    a25 = [(f * k, x, y) for f, x, y in A]
    b25 = [(f * k, x, y) for f, x, y in B]
    rows = np.array(_rows(1, a25) + _rows(2, b25), dtype=float)
    # resample to whole frames at 25 fps
    rows[:, 1] = np.round(rows[:, 1])
    out, fams, stats = link_rows(rows, 25.0, gates, frame_size=(400, 400))
    assert set(np.unique(out[:, 0]).astype(int)) == {1}


def test_a_three_piece_car_is_one_track(gates):
    a = [(float(f), 50.0, -5.0 + 2.0 * f) for f in range(20)]            # y to 33
    b = [(28.0 + f, 50.0, 49.0 + 2.0 * f) for f in range(8)]             # y 49..63
    c_ = [(44.0 + f, 50.0, 81.0 + 2.0 * f) for f in range(20)]           # y 81.. out
    out, fams, stats, ids = _run(gates, _rows(1, a), _rows(2, b), _rows(3, c_))
    assert ids == {1} and fams == {1: [1, 2, 3]}


def test_shipped_default(gates):
    import backend.config as cfg
    assert cfg.TRACKLET_LINKER is True and cfg.TRACKLET_LINKER_EXCLUSIVE is True
    assert cfg.LINKER_STOPPED_LEVEL is False                   # lk1 broke cam3
    # with the stopped level off, the red-light case stays two pieces
    stop = [(float(f), 50.0, min(-5.0 + 2.0 * f, 40.0)) for f in range(60)]
    go = [(260.0 + f, 50.0, 40.0 + 3.0 * f) for f in range(25)]
    out, fams, stats, ids = _run(gates, _rows(1, stop), _rows(2, go))
    assert ids == {1, 2}
