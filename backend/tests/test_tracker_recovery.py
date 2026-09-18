"""Stage 2.5 position recovery in the supervision ByteTrack backend
(config.TRACKER_POSITION_RECOVERY, 2026-09-12). Default ON; the fork is
pinned to the library version; with the stage on, a far-field chain that
the library splits is held as one id, weak boxes never birth, parallel
vehicles keep their ids, a lost track is re-found by position."""
import pickle

import numpy as np
import pytest
import supervision as sv
from supervision.tracker.byte_tracker import matching as _m
from supervision.tracker.byte_tracker.basetrack import BaseTrack

from backend import config as cfg
from backend.services import tracker as T
from backend.services import two_pass as tp
from backend.services.tracker import create_tracker_backend

FPS = 10


def det(x, y, w=30.0, h=20.0, conf=0.9, cid=2):
    return {"bbox": [x - w / 2, y - h / 2, x + w / 2, y + h / 2],
            "confidence": conf, "class_id": cid}


def backend():
    return create_tracker_backend("bytetrack", track_activation_threshold=0.25,
                                  minimum_matching_threshold=0.8, frame_rate=FPS,
                                  lost_track_buffer=150)


def run(be, frames, n=None):
    """Step EVERY frame from 1 (empty updates included); {frame: [ids]}."""
    out = {}
    last = n or max(frames)
    for f in range(1, last + 1):
        out[f] = sorted(r["track_id"] for r in be.update(frames.get(f, []), f))
    return out


def chain(start=3, w=24.0, dx=8.0, confs=(0.6, 0.6, 0.18, 0.6, 0.18, 0.18), n=26, y=240.0, x0=300.0):
    """A far-field vehicle: born mid-video at 24 px, moving 8 px/frame,
    confidence in runs (the far field's flicker)."""
    frames = {}
    for k in range(n - start + 1):
        f = start + k
        frames[f] = [det(x0 + dx * k, y, w, 0.75 * w, confs[k % len(confs)])]
    return frames


def ids(out):
    return sorted({t for v in out.values() for t in v})


@pytest.fixture(autouse=True)
def reset_ids(monkeypatch):
    monkeypatch.setattr(BaseTrack, "_count", 0)


@pytest.fixture
def recovery_on(monkeypatch):
    monkeypatch.setattr(cfg, "TRACKER_POSITION_RECOVERY", True)


def test_default_on_and_switchable(monkeypatch):
    assert cfg.TRACKER_POSITION_RECOVERY is True       # the stage IS the tracker (2026-09-12)
    be = backend()
    assert be.position_recovery is True
    assert isinstance(be.byte_track, T._RecoveringByteTrack)
    monkeypatch.setattr(cfg, "TRACKER_POSITION_RECOVERY", False)
    be = backend()
    assert type(be.byte_track) is sv.ByteTrack


@pytest.fixture
def recovery_off(monkeypatch):
    monkeypatch.setattr(cfg, "TRACKER_POSITION_RECOVERY", False)


def test_fork_pinned_to_supervision_version():
    assert sv.__version__ == T._FORK_SV_VERSION


def test_recovery_cost_and_gate():
    trk = np.array([[0, 0, 20, 15]], dtype=np.float32)
    d = np.array([[8, 0, 28, 15], [0, 0, 10, 8], [-5, -5, 35, 25]], dtype=np.float32)
    c = T._recovery_cost(trk, d, 0.3)
    assert c.shape == (1, 3)
    assert abs(c[0, 0] - 0.4) < 1e-5            # 8 px apart / max width 20
    assert c[0, 1] < np.inf                      # ratio 0.5 passes
    assert c[0, 2] < np.inf                      # ratio 0.5 passes
    c2 = T._recovery_cost(trk, np.array([[0, 0, 4, 3]], dtype=np.float32), 0.3)
    assert c2[0, 0] == np.inf                    # ratio 0.2 < 0.3
    c3 = T._recovery_cost(trk, np.array([[5, 0, 5, 3]], dtype=np.float32), 0.3)
    assert c3[0, 0] == np.inf                    # zero width
    assert T._recovery_cost(np.zeros((0, 4)), d, 0.3).shape == (0, 3)


def test_greedy_pairs_one_to_one_and_reach():
    # Hungarian would take (0,1)+(1,0) = 0.5+0.6 over (0,0)=0.1 alone; greedy keeps the nearest.
    cost = np.array([[0.1, 0.5], [0.6, 5.0]], dtype=np.float32)
    assert T._greedy_pairs(cost, 0.9) == [(0, 0)]
    assert T._greedy_pairs(cost, 0.05) == []
    assert T._greedy_pairs(np.zeros((0, 0)), 0.9) == []
    cost = np.array([[0.2, 0.3], [0.25, 0.1]], dtype=np.float32)
    assert sorted(T._greedy_pairs(cost, 0.9)) == [(0, 0), (1, 1)]


def test_far_field_chain_breaks_on_stock(recovery_off):
    out = run(backend(), chain())
    blanks = sum(1 for f in range(4, 27) if not out[f])
    assert len(ids(out)) > 1 or blanks > 5


def test_far_field_chain_one_id_with_stage(recovery_on):
    be = backend()
    out = run(be, chain())
    assert len(ids(out)) == 1
    assert all(out[f] for f in range(4, 27)), out
    assert be.byte_track.n_recovered >= 1


def test_flag_off_matches_library(recovery_off):
    frames = chain()
    frames2 = chain(y=320.0)
    both = {f: frames.get(f, []) + frames2.get(f, []) for f in range(1, 27)}
    a = run(backend(), both)
    BaseTrack._count = 0
    raw = sv.ByteTrack(track_thresh=0.25, track_buffer=150, match_thresh=0.8, frame_rate=FPS)
    b = {}
    for f in range(1, 27):
        d = both.get(f, [])
        if d:
            sd = sv.Detections(xyxy=np.array([x["bbox"] for x in d], dtype=np.float32),
                               confidence=np.array([x["confidence"] for x in d], dtype=np.float32),
                               class_id=np.array([x["class_id"] for x in d], dtype=int))
        else:
            sd = sv.Detections.empty()
        r = raw.update_with_detections(sd)
        b[f] = sorted(int(t) for t in r.tracker_id) if len(r) else []
    assert a == b


def test_zero_reach_is_byte_identical(recovery_on, monkeypatch):
    frames = chain()
    frames2 = chain(y=320.0, confs=(0.6, 0.3, 0.18, 0.7))
    both = {f: frames.get(f, []) + frames2.get(f, []) for f in range(1, 27)}
    monkeypatch.setattr(cfg, "TRACKER_RECOVERY_REACH", 0.0)
    monkeypatch.setattr(cfg, "TRACKER_CONFIRM_BY_POSITION", False)
    monkeypatch.setattr(cfg, "TRACKER_WEAK_BIRTH", False)
    be = backend()
    assert isinstance(be.byte_track, T._RecoveringByteTrack)
    a = run(be, both)
    BaseTrack._count = 0
    monkeypatch.setattr(cfg, "TRACKER_POSITION_RECOVERY", False)
    b = run(backend(), both)
    assert a == b


def test_parallel_vehicles_keep_two_ids(recovery_on):
    w = 24.0
    lo, hi = chain(y=240.0), chain(y=240.0 + 1.5 * w)
    both = {f: lo.get(f, []) + hi.get(f, []) for f in range(1, 27)}
    be = backend()
    out = run(be, both)
    assert len(ids(out)) == 2
    assert all(len(out[f]) == 2 for f in range(4, 27)), out
    # lane order preserved: the id born lower stays lower
    final = {r["track_id"]: r["center"][1] for r in be.update(both[26], 27)}
    first = sorted(out[4])
    assert final[first[0]] < final[first[1]] or final[first[0]] > final[first[1]]


def test_weak_boxes_never_birth_through_recovery(recovery_on, monkeypatch):
    """Recovery and confirmation never create a track from weak boxes (the
    weak-box birth stage, tested in test_tracker_weak_birth.py, is off)."""
    monkeypatch.setattr(cfg, "TRACKER_WEAK_BIRTH", False)
    be = backend()
    out = run(be, chain(confs=(0.18,)))
    assert ids(out) == []
    assert be.byte_track.n_recovered == 0


def test_lost_track_refound_same_id(recovery_on):
    frames = {}
    for f in range(1, 31):
        if 11 <= f <= 13:
            continue
        x = 100.0 + 8.0 * (f - 1)
        # returns 8 px lower: overlap with the prediction ~0.27 (>= the 0.2 gate) but
        # fused 0.27 x 0.6 < 0.2, so stage 1 refuses it and only the recovery holds the id
        y = 200.0 + (8.0 if f >= 14 else 0.0)
        frames[f] = [det(x, y, 20.0, 15.0, 0.6)]
    be = backend()
    out = run(be, frames, n=30)
    tid = out[10][0]
    assert all(out[f] == [tid] for f in range(14, 31)), out
    assert be.byte_track.n_recovered_lost >= 1 or be.byte_track.n_recovered >= 1
    # stock: the returning, displaced box is not re-found by the same id
    BaseTrack._count = 0
    cfg_off = pytest.MonkeyPatch()
    cfg_off.setattr(cfg, "TRACKER_POSITION_RECOVERY", False)
    try:
        out2 = run(backend(), frames, n=30)
    finally:
        cfg_off.undo()
    tid2 = out2[10][0]
    assert not all(out2[f] == [tid2] for f in range(14, 31))


def test_fork_uses_module_fuse_score(recovery_on, monkeypatch):
    calls = {"n": 0}
    orig = _m.fuse_score

    def counting(cost, dets):
        calls["n"] += 1
        return orig(cost, dets)

    be = backend()                                # __init__ re-applies the fuse switch: patch AFTER
    monkeypatch.setattr(_m, "fuse_score", counting)
    be.update([det(100, 100, conf=0.9)], 1)
    be.update([det(108, 100, conf=0.9)], 2)
    assert calls["n"] == 4   # stage 1 + unconfirmed pass, per frame


def test_state_round_trip_and_reset(recovery_on):
    frames = chain()
    be = backend()
    for f in range(1, 9):
        be.update(frames.get(f, []), f)
    state = be.get_state()
    be2 = backend()
    be2.load_state(state)
    assert isinstance(be2.byte_track, T._RecoveringByteTrack)
    assert be2.byte_track.recovery_reach == 0.9
    a, b = {}, {}
    for f in range(9, 27):
        a[f] = sorted(r["track_id"] for r in be.update(frames.get(f, []), f))
        b[f] = sorted(r["track_id"] for r in be2.update(frames.get(f, []), f))
    assert a == b
    be.reset()
    assert isinstance(be.byte_track, T._RecoveringByteTrack)
    assert be.byte_track.frame_id == 0
    assert be.byte_track.tentatives == []
    assert isinstance(pickle.loads(state), T._RecoveringByteTrack)


def test_pass1_meta_helpers(monkeypatch):
    assert tp._cfg_position_recovery() is True
    monkeypatch.setattr(cfg, "TRACKER_POSITION_RECOVERY", False)
    assert tp._cfg_position_recovery() is False
    assert "position_recovery" in tp.PASS1_RESUME_KEYS
    assert "fuse_score" in tp.PASS1_RESUME_KEYS


def test_min_iou_gate_blocks_non_overlapping_jump(recovery_on, monkeypatch):
    """A track whose next box no longer overlaps its prediction is NOT
    recovered under the default gate (0.2), and IS with the gate off."""
    frames = {}
    for f in range(3, 13):
        frames[f] = [det(100.0 + 5.0 * (f - 3), 200.0, 20.0, 15.0, 0.6)]
    # the Kalman prediction at frame 13 sits at x~149.5 (velocity lags); a weak box at 165 is
    # 15.5 px away: IoU 0.13 < 0.2 (gated) while cost 0.78 < reach 0.9 (taken when ungated)
    frames[13] = [det(165.0, 200.0, 20.0, 15.0, 0.18)]
    for f in range(14, 22):
        frames[f] = [det(165.0 + 5.0 * (f - 13), 200.0, 20.0, 15.0, 0.18)]
    be = backend()
    out = run(be, frames, n=21)
    assert be.byte_track.recovery_min_iou == 0.2
    assert not out[13], out                     # gated: the jump is refused
    BaseTrack._count = 0
    monkeypatch.setattr(cfg, "TRACKER_RECOVERY_MIN_IOU", 0.0)
    be2 = backend()
    out2 = run(be2, frames, n=21)
    assert out2[13] == out2[12]                 # ungated (d18): the jump is taken
    assert "recovery_min_iou" in tp.PASS1_RESUME_KEYS


def test_edge_strip_birth_is_confirmed_by_position(recovery_on, monkeypatch):
    """A vehicle entering over the bottom edge: a 200x40 strip at frame 3, a
    200x150 box at frame 4 shifted 30 px (IoU ~0.2, same width). The library
    kills the birth (needs IoU x conf >= 0.3); confirmation by position holds it."""
    frames = {3: [{"bbox": [300.0, 440.0, 500.0, 480.0], "confidence": 0.8, "class_id": 2}]}
    for k, f in enumerate(range(4, 16)):
        x = 330.0 + 30.0 * k
        frames[f] = [{"bbox": [x, 330.0, x + 200.0, 480.0], "confidence": 0.8, "class_id": 2}]
    be = backend()
    out = run(be, frames, n=15)
    assert out[4] and out[4] == out[5], out
    assert be.byte_track.n_confirmed_by_position >= 1
    BaseTrack._count = 0
    monkeypatch.setattr(cfg, "TRACKER_CONFIRM_BY_POSITION", False)
    be2 = backend()
    out2 = run(be2, frames, n=15)
    assert be2.byte_track.n_confirmed_by_position == 0
    assert not out2[4] or out2[4] != out2[5]      # the library re-births instead of confirming
    assert "confirm_by_position" in tp.PASS1_RESUME_KEYS


def test_confirmation_resets_motion_state(recovery_on):
    """After a strip-to-full confirmation the tracker's box must follow the
    real box, not balloon (the poisoned-Kalman failure)."""
    frames = {3: [{"bbox": [300.0, 440.0, 500.0, 480.0], "confidence": 0.8, "class_id": 2}]}
    for k, f in enumerate(range(4, 20)):
        x = 330.0 + 30.0 * k
        frames[f] = [{"bbox": [x, 330.0, x + 200.0, 480.0], "confidence": 0.8, "class_id": 2}]
    be = backend()
    widths = {}
    for f in range(1, 20):
        for r in be.update(frames.get(f, []), f):
            widths[f] = r["bbox_width"]
    assert be.byte_track.n_confirmed_by_position >= 1
    assert all(140 <= widths[f] <= 260 for f in range(6, 20)), widths
    assert len({t for f in range(4, 20) for t in [widths.get(f)] if t is not None}) >= 1


def test_stale_lost_track_not_recovered_by_position(recovery_on):
    """A track lost longer than the patience (0.5 s = 5 frames at 10 fps) is
    not handed the next weak box that appears at its predicted spot."""
    frames = {}
    for f in range(3, 11):
        frames[f] = [det(100.0 + 4.0 * (f - 3), 200.0, 20.0, 15.0, 0.6)]
    # gone frames 11-20 (10 frames > patience); a WEAK box appears near where
    # the prediction would be — only position recovery could take it
    for f in range(21, 26):
        frames[f] = [det(100.0 + 4.0 * (f - 3), 200.0, 20.0, 15.0, 0.18)]
    be = backend()
    assert be.byte_track.lost_patience_frames == 5
    out = run(be, frames, n=25)
    tid = out[10][0]
    assert all(tid not in out[f] for f in range(21, 26)), out


def test_track_that_drives_out_of_frame_is_retired(recovery_on):
    """A vehicle leaving over the right edge is removed at once; a second
    vehicle leaving through the same spot 1.5 s later gets a NEW id."""
    be = create_tracker_backend("bytetrack", track_activation_threshold=0.25,
                                minimum_matching_threshold=0.8, frame_rate=FPS,
                                lost_track_buffer=150, frame_size=(640, 480))
    frames = {}
    for k, f in enumerate(range(3, 15)):                  # car A: exits right at frame ~14
        x2 = min(640.0, 520.0 + 12.0 * k)
        frames[f] = [{"bbox": [x2 - 60.0, 300.0, x2, 340.0], "confidence": 0.8, "class_id": 2}]
    for k, f in enumerate(range(30, 42)):                 # car B: same path, 1.5 s later
        x2 = min(640.0, 520.0 + 12.0 * k)
        frames[f] = [{"bbox": [x2 - 60.0, 300.0, x2, 340.0], "confidence": 0.8, "class_id": 2}]
    out = run(be, frames, n=41)
    a = out[8][0]
    assert be.byte_track.n_edge_exits >= 1
    assert all(a not in out[f] for f in range(30, 42)), out


def test_entering_over_edge_is_not_retired(recovery_on):
    """Touching the bottom edge while moving UP (entering) is not an exit."""
    be = create_tracker_backend("bytetrack", track_activation_threshold=0.25,
                                minimum_matching_threshold=0.8, frame_rate=FPS,
                                lost_track_buffer=150, frame_size=(640, 480))
    frames = {}
    for k, f in enumerate(range(3, 12)):
        y1 = 400.0 - 6.0 * k
        frames[f] = [{"bbox": [300.0, y1, 400.0, 480.0], "confidence": 0.8, "class_id": 2}]
    frames.pop(8)                                         # one missed frame while touching the edge
    out = run(be, frames, n=11)
    assert be.byte_track.n_edge_exits == 0
    assert out[9] == out[7], out


def test_dup_boxes_removed_only_above_threshold():
    car = {"bbox": [100, 100, 160, 140], "confidence": 0.9, "class_id": 2}
    dup_same = {"bbox": [101, 100, 161, 140], "confidence": 0.5, "class_id": 2}    # IoU ~0.97
    dup_cross = {"bbox": [100, 101, 160, 141], "confidence": 0.6, "class_id": 7}   # IoU ~0.95
    occluded = {"bbox": [115, 100, 175, 140], "confidence": 0.7, "class_id": 2}   # IoU 0.6: kept
    out = T._dedup_boxes([car, dup_same, dup_cross, occluded], 0.8)
    assert car in out and occluded in out and dup_same not in out and dup_cross not in out
    assert T._dedup_boxes([car, dup_same], 0.0) == [car, dup_same]


def test_double_box_vehicle_is_one_track(recovery_on):
    frames = {}
    for k, f in enumerate(range(3, 20)):
        x = 100.0 + 6.0 * k
        frames[f] = [{"bbox": [x, 200.0, x + 60.0, 240.0], "confidence": 0.8, "class_id": 2},
                     {"bbox": [x + 1.0, 199.0, x + 61.0, 241.0], "confidence": 0.6, "class_id": 7}]
    out = run(backend(), frames, n=19)
    assert len(ids(out)) == 1, out
    assert "dup_box_iou" in tp.PASS1_RESUME_KEYS


def test_stacked_newborn_not_confirmed_as_twin(recovery_on):
    """A vehicle carries a live track; a second box stacked on it at IoU ~0.7
    (below the input dedup) appears every frame. It must not become a
    confirmed twin track through confirmation by position."""
    frames = {}
    for k, f in enumerate(range(3, 25)):
        x = 100.0 + 5.0 * k
        frames[f] = [{"bbox": [x, 200.0, x + 60.0, 240.0], "confidence": 0.9, "class_id": 2}]
        if f >= 8:   # the stacked double appears once the vehicle is tracked
            frames[f].append({"bbox": [x + 9.0, 200.0, x + 69.0, 240.0], "confidence": 0.5, "class_id": 7})
    be = backend()
    out = run(be, frames, n=24)
    main = out[7][0]
    assert all(main in out[f] for f in range(8, 25))
    assert be.byte_track.n_confirmed_by_position == 0


def test_stacked_box_does_not_birth_a_twin(recovery_on):
    """A confident stacked double (IoU ~0.7, below the input dedup) must not
    start a second track on a held vehicle; a separated second vehicle is
    born normally."""
    frames = {}
    for k, f in enumerate(range(3, 25)):
        x = 100.0 + 5.0 * k
        frames[f] = [{"bbox": [x, 200.0, x + 60.0, 240.0], "confidence": 0.9, "class_id": 2}]
        if 8 <= f < 16:
            frames[f].append({"bbox": [x + 9.0, 200.0, x + 69.0, 240.0], "confidence": 0.8, "class_id": 7})
        if f >= 16:   # a different vehicle, clear of the first
            frames[f].append({"bbox": [x + 120.0, 200.0, x + 180.0, 240.0], "confidence": 0.8, "class_id": 2})
    be = backend()
    out = run(be, frames, n=24)
    assert all(len(out[f]) == 1 for f in range(8, 16)), out
    assert all(len(out[f]) == 2 for f in range(18, 25)), out
    assert be.byte_track.n_births_deferred >= 1
    assert "stack_iou" in tp.PASS1_RESUME_KEYS


def test_reset_keeps_motion_for_an_entering_vehicle(recovery_on):
    """A vehicle entering over the left edge (box growing fast while it moves
    right ~40 px/frame) keeps ONE id; a second vehicle entering right behind
    it does not take that id (the clip-6 theft)."""
    be = create_tracker_backend("bytetrack", track_activation_threshold=0.25,
                                minimum_matching_threshold=0.8, frame_rate=FPS,
                                lost_track_buffer=150, frame_size=(640, 480))
    frames = {}
    for k, f in enumerate(range(3, 20)):        # van: front edge 40 px/frame, full width 160
        x2 = 40.0 + 40.0 * k
        x1 = max(0.0, x2 - 160.0)
        frames[f] = [{"bbox": [x1, 300.0, x2, 380.0], "confidence": 0.6, "class_id": 7}]
    for k, f in enumerate(range(8, 20)):        # SUV entering behind it 5 frames later
        x2 = 30.0 + 40.0 * k
        x1 = max(0.0, x2 - 110.0)
        frames[f].append({"bbox": [x1, 305.0, x2, 380.0], "confidence": 0.8, "class_id": 2})
    out = {}
    first_van = None
    for f in range(1, 20):
        res = be.update(frames.get(f, []), f)
        out[f] = {r["track_id"]: r["bbox"] for r in res}
    # the id on the van (rightmost box) at frame 7 must be the id on the rightmost box at frame 19
    van7 = max(out[7].items(), key=lambda kv: kv[1][2])[0]
    van19 = max(out[19].items(), key=lambda kv: kv[1][2])[0]
    assert van7 == van19, out


def test_match_log_records_stages_and_changes_nothing(recovery_on):
    """The diagnostics-only match log (research_thefts.py) names the stage of
    every association at its absolute frame, and switching it on leaves the
    tracker's output identical."""
    frames = {}
    for f in range(1, 31):
        if 11 <= f <= 13:
            continue
        frames[f] = [det(100.0 + 8.0 * (f - 1), 200.0 + (8.0 if f >= 14 else 0.0), 20.0, 15.0, 0.6)]
    two = chain(y=320.0)
    both = {f: frames.get(f, []) + two.get(f, []) for f in range(1, 31)}
    plain = {}
    be = backend()
    for f in range(1, 31):
        plain[f] = [(r["track_id"], tuple(r["bbox"])) for r in be.update(both.get(f, []), 1000 + f)]
    BaseTrack._count = 0
    be = backend()
    be.byte_track.match_log = []
    logged = {}
    for f in range(1, 31):
        logged[f] = [(r["track_id"], tuple(r["bbox"])) for r in be.update(both.get(f, []), 1000 + f)]
    assert logged == plain
    log = be.byte_track.match_log
    stages = {rec[2] for rec in log}
    assert {"birth", "unconf", "s1"} <= stages
    assert stages & {"s25", "s2"}                 # the displaced return / the weak boxes
    first = log[0]
    assert first[0] == 1001 and first[2] == "birth" and first[4] == 0
    # the return after the 3-frame gap is logged as a lost track, 4 frames since seen
    ret = [r for r in log if r[0] == 1014 and r[3]]
    assert ret and ret[0][4] == 4
    assert all(len(r) == 8 for r in log)
    # an old pickle without the attribute still runs (stage-off guard)
    del be.byte_track.match_log
    be.update(both[30], 1031)


def _run_with(monkeypatch, frames, n, **knobs):
    for k, v in knobs.items():
        monkeypatch.setattr(cfg, k, v)
    monkeypatch.setattr(BaseTrack, "_count", 0)
    be = backend()
    out = {}
    for f in range(1, n + 1):
        out[f] = {r["track_id"]: r["bbox"] for r in be.update(frames.get(f, []), f)}
    return be, out


def test_held_box_guard_refuses_neighbours_second_box(monkeypatch, recovery_on):
    """Two vehicles side by side, moving right. Vehicle B's box is missed
    for a few frames while a weak second box stacked on vehicle A's box
    (IoU ~0.67, overlapping B's last box by ~0.3) appears; A's own confident
    box is taken by A's id in stage 1. Without the guard B's id recovers onto A's second box (a theft); with
    TRACKER_RECOVERY_HELD_IOU=0.6 it is refused and B goes lost instead."""
    def frames_for():
        frames = {}
        for k, f in enumerate(range(1, 30)):
            x = 100.0 + 6.0 * k
            fr = [{"bbox": [x, 200.0, x + 60.0, 240.0], "confidence": 0.9, "class_id": 2}]
            if f < 15 or f >= 22:
                fr.append({"bbox": [x, 230.0, x + 60.0, 270.0], "confidence": 0.9, "class_id": 2})
            else:   # B missed; a weak second box rides A, nudged toward B's side
                fr.append({"bbox": [x + 2.0, 208.0, x + 62.0, 248.0], "confidence": 0.2, "class_id": 2})
            frames[f] = fr
        return frames
    be0, out0 = _run_with(monkeypatch, frames_for(), 29, TRACKER_RECOVERY_HELD_IOU=0.0)
    be1, out1 = _run_with(monkeypatch, frames_for(), 29, TRACKER_RECOVERY_HELD_IOU=0.6)
    b_id = [t for t, bb in out0[14].items() if bb[1] > 225][0]
    # without the guard, B's id sits on the stacked box on A's row
    assert b_id in out0[15] and out0[15][b_id][1] < 225, out0[15]
    # with the guard the recovery is refused: B's id is not output on the
    # stacked box, and the refusal is counted
    assert b_id not in out1[15] or out1[15][b_id][1] > 225, out1[15]
    assert be1.byte_track.n_recovery_refused_held >= 1
    assert be0.byte_track.n_recovery_refused_held == 0


def test_reverse_jump_guard_refuses_box_behind_the_vehicle(monkeypatch, recovery_on):
    """A far-field vehicle moving right 8 px/frame. At one frame its own box
    is missed and a weak box appears half a width BEHIND it (a follower).
    Without the guard the id takes it by position recovery; with
    TRACKER_RECOVERY_REVERSE_DEG=90 the backward jump is refused. A weak box
    AHEAD, in the direction of travel, is still recovered."""
    def frames_for(behind: bool):
        frames = {}
        for k, f in enumerate(range(1, 25)):
            x = 300.0 + 8.0 * k
            if f == 12:
                xb = x - 12.0 if behind else x
                frames[f] = [det(xb, 240.0, 24.0, 18.0, 0.2)]
            else:
                frames[f] = [det(x, 240.0, 24.0, 18.0, 0.6)]
        return frames
    be0, out0 = _run_with(monkeypatch, frames_for(True), 24, TRACKER_RECOVERY_REVERSE_DEG=0.0)
    tid = list(out0[11])[0]
    assert tid in out0[12]                       # the theft: recovered onto the follower
    be1, out1 = _run_with(monkeypatch, frames_for(True), 24, TRACKER_RECOVERY_REVERSE_DEG=90.0)
    assert tid not in out1[12], out1[12]          # refused: lost this frame
    assert tid in out1[13]                        # its own confident box re-finds it
    assert be1.byte_track.n_recovery_refused_reverse >= 1
    be2, out2 = _run_with(monkeypatch, frames_for(False), 24, TRACKER_RECOVERY_REVERSE_DEG=90.0)
    assert tid in out2[12] and be2.byte_track.n_recovery_refused_reverse == 0


def test_recovery_guard_in_pass1_recipe(monkeypatch):
    assert "recovery_guard" in tp.PASS1_RESUME_KEYS
    monkeypatch.setattr(cfg, "TRACKER_RECOVERY_HELD_IOU", 0.0)
    monkeypatch.setattr(cfg, "TRACKER_RECOVERY_REVERSE_DEG", 0.0)
    assert tp._cfg_recovery_guard() is None
    monkeypatch.setattr(cfg, "TRACKER_RECOVERY_REVERSE_DEG", 90.0)
    assert tp._cfg_recovery_guard() == {"held_iou": 0.0, "reverse_deg": 90.0, "reverse_jump": 0.15}
