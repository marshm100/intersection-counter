"""Weak-box births in the recovery tracker (config.TRACKER_WEAK_BIRTH,
2026-09-12). A distant or partly hidden car's boxes stay under the birth bar
(0.35) for 0.5-1.5 s; the tracker keeps them as a tentative history.
Inheritance: the track born from the car's first confident box takes the
history as back-fill. Promotion: a tentative that held together 0.5 s and
moved 0.5 box widths, not riding a held vehicle, becomes a track."""
import pickle

import pytest
from supervision.tracker.byte_tracker.basetrack import BaseTrack

from backend import config as cfg
from backend.services.tracker import create_tracker_backend

FPS = 10


def det(x, y, w=20.0, h=15.0, conf=0.18, cid=2):
    return {"bbox": [x - w / 2, y - h / 2, x + w / 2, y + h / 2],
            "confidence": conf, "class_id": cid}


def backend(collect=True):
    return create_tracker_backend("bytetrack", track_activation_threshold=0.25,
                                  minimum_matching_threshold=0.8, frame_rate=FPS,
                                  lost_track_buffer=150, collect_backfill=collect)


def run(be, frames, n, base=1000):
    """Step frames 1..n with ABSOLUTE frame numbers base+f; {f: {id: bbox}}."""
    out = {}
    for f in range(1, n + 1):
        out[f] = {r["track_id"]: r["bbox"] for r in be.update(frames.get(f, []), base + f)}
    return out


def all_ids(out):
    return {t for v in out.values() for t in v}


@pytest.fixture(autouse=True)
def stage_on(monkeypatch):
    monkeypatch.setattr(BaseTrack, "_count", 0)
    monkeypatch.setattr(cfg, "TRACKER_POSITION_RECOVERY", True)
    monkeypatch.setattr(cfg, "TRACKER_WEAK_BIRTH", True)
    monkeypatch.setattr(cfg, "TRACKER_WEAK_BIRTH_PROMOTE", True)


def test_defaults_and_frame_conversion(monkeypatch):
    monkeypatch.undo()
    assert cfg.TRACKER_WEAK_BIRTH is True and cfg.TRACKER_WEAK_BIRTH_PROMOTE is False   # promotion off until its continuity is fixed
    assert cfg.TRACKER_WEAK_BIRTH_GAP_S < 0.5                     # under the stop-fracture grace
    from backend.services.two_pass import PASS1_SEAM_WARMUP_SECONDS
    assert cfg.TRACKER_WEAK_BIRTH_HISTORY_S < PASS1_SEAM_WARMUP_SECONDS
    bt = backend().byte_track
    assert (bt.wb_persist_frames, bt.wb_gap_frames, bt.wb_history_frames) == (5, 2, 100)


def test_weak_moving_chain_births_once_with_backfill():
    frames = {f: [det(100.0 + 4.0 * f, 200.0)] for f in range(3, 25)}
    be = backend()
    out = run(be, frames, 24)
    ids = all_ids(out)
    assert len(ids) == 1
    tid = next(iter(ids))
    first = min(f for f, v in out.items() if v)
    rows = be.pop_backfill()
    assert rows and {r["track_id"] for r in rows} == {tid}
    assert all(r["promoted_at"] == 1000 + first for r in rows)
    assert sorted(r["frame"] for r in rows) == list(range(1003, 1000 + first))
    assert rows[0]["class_id"] == 2
    assert be.pop_backfill() == []                                 # rows come out once
    assert be.byte_track.n_weak_births == 1


def test_weak_static_chain_never_births_and_history_is_capped():
    frames = {f: [det(100.0 + (1.0 if f % 2 else -1.0), 200.0)] for f in range(3, 160)}
    be = backend()
    out = run(be, frames, 159)
    assert not any(out.values())
    assert len(be.byte_track.tentatives) == 1
    assert len(be.byte_track.tentatives[0]["obs"]) <= be.byte_track.wb_history_frames


def test_static_then_moving_promotes_with_capped_backfill():
    frames = {f: [det(100.0, 200.0)] for f in range(3, 153)}
    for k, f in enumerate(range(153, 175)):
        frames[f] = [det(100.0 + 4.0 * (k + 1), 200.0)]
    be = backend()
    out = run(be, frames, 174)
    assert len(all_ids(out)) == 1
    rows = be.pop_backfill()
    assert 0 < len(rows) <= be.byte_track.wb_history_frames
    fr = sorted(r["frame"] for r in rows)
    assert fr == list(range(fr[0], fr[0] + len(fr)))               # contiguous


@pytest.mark.parametrize("dx", [3.0, 7.0])                         # IoU ~0.7 stacked; ~0.5 covered
def test_weak_box_riding_a_tracked_vehicle_never_births_a_twin(dx):
    frames = {}
    for k, f in enumerate(range(3, 30)):
        x = 100.0 + 4.0 * k
        frames[f] = [det(x, 200.0, 40.0, 30.0, 0.9), det(x + dx, 200.0, 40.0, 30.0, 0.18, 7)]
    be = backend()
    out = run(be, frames, 29)
    assert len(all_ids(out)) == 1, out
    assert be.byte_track.n_weak_births == 0


def test_two_overlapping_weak_boxes_promote_once():
    frames = {}
    for k, f in enumerate(range(3, 25)):
        x = 100.0 + 4.0 * k
        frames[f] = [det(x, 200.0, 20.0, 15.0, 0.18), det(x + 5.0, 200.0, 20.0, 15.0, 0.15, 7)]
    be = backend()
    out = run(be, frames, 24)
    assert len(all_ids(out)) == 1
    assert be.byte_track.n_weak_births == 1


def test_queue_car_inherits_its_weak_history():
    """The hand-off reel's clip 5: a car beside a static neighbour, weak for
    15 frames, then a confident box starts it; its 15 weak frames plus the
    birth frame come back as back-fill under the new id."""
    frames = {}
    for f in range(3, 40):
        frames[f] = [det(100.0, 200.0, 40.0, 30.0, 0.9)]           # neighbour, static
    for f in range(10, 25):
        frames[f].append(det(128.0, 200.0, 40.0, 30.0, 0.2))      # weak, static, beside it
    for f in range(25, 40):
        frames[f].append(det(128.0 + 2.0 * (f - 24), 200.0, 40.0, 30.0, 0.6))
    be = backend()
    out = run(be, frames, 39)
    assert be.byte_track.n_weak_births == 0                        # never promoted while static
    assert be.byte_track.n_weak_inherited == 1
    new = [t for t in all_ids(out) if t not in out[5]]
    assert len(new) == 1
    rows = [r for r in be.pop_backfill() if r["track_id"] == new[0]]
    assert sorted(r["frame"] for r in rows) == list(range(1010, 1026))   # 15 weak + the birth frame


def test_no_collection_without_opt_in():
    frames = {f: [det(100.0 + 4.0 * f, 200.0)] for f in range(3, 25)}
    be = backend(collect=False)
    out = run(be, frames, 24)
    assert len(all_ids(out)) == 1
    assert be.byte_track.backfill is None and be.pop_backfill() == []


def test_pickle_round_trip_mid_tentative():
    frames = {f: [det(100.0 + 4.0 * f, 200.0)] for f in range(3, 25)}
    be = backend()
    for f in range(1, 7):
        be.update(frames.get(f, []), 1000 + f)
    assert be.byte_track.tentatives
    be2 = backend()
    be2.load_state(be.get_state())
    c0 = BaseTrack._count                                          # ids come from one process counter
    a = {f: sorted(r["track_id"] for r in be.update(frames.get(f, []), 1000 + f)) for f in range(7, 25)}
    rows_a = be.pop_backfill()
    BaseTrack._count = c0
    b = {f: sorted(r["track_id"] for r in be2.update(frames.get(f, []), 1000 + f)) for f in range(7, 25)}
    assert a == b
    assert rows_a and rows_a == be2.pop_backfill()


def test_old_pickle_without_the_stage_still_updates():
    be = backend()
    for f in range(1, 4):
        be.update([det(100.0 + 4.0 * f, 200.0, conf=0.9)], 1000 + f)
    old = be.byte_track
    for a in ("tentatives", "backfill", "weak_birth", "_abs_now"):
        delattr(old, a)
    be2 = backend()
    be2.load_state(pickle.dumps(old))
    res = be2.update([det(116.0, 200.0, conf=0.9)], 1004)
    assert res and be2.pop_backfill() == []


def test_newborn_does_not_inherit_a_history_that_rode_a_held_vehicle():
    """Weak boxes riding inside a tracked car (a double box, IoU ~0.5) form a
    tentative; when one of them turns confident and is born, it must not
    take that history (no twin coverage back-filled beside the car)."""
    frames = {}
    for k, f in enumerate(range(3, 30)):
        x = 100.0 + 4.0 * k
        conf2 = 0.18 if f < 20 else 0.5
        frames[f] = [det(x, 200.0, 40.0, 30.0, 0.9), det(x + 7.0, 200.0, 40.0, 30.0, conf2, 7)]
    be = backend()
    run(be, frames, 29)
    assert be.byte_track.n_weak_inherited == 0
    assert be.pop_backfill() == []
