"""Anti-theft campaign (2026-09-06) — the emergence guard.

Operator emergence law: when a hidden vehicle emerges beside a
tracked one, the newcomer gets a NEW track; a moving track may only
claim a detection its own motion reaches. Each test is one ruling
made executable (docs/plan_anti_theft_2026-09-06.md, G-LT-1).
"""
from __future__ import annotations

import pytest

import backend.config as cfg
from backend.services.tracker import create_tracker_backend

FPS = 25


def det(x, y, w=30.0, h=20.0, conf=0.9, cid=2):
    return {"bbox": [x - w / 2, y - h / 2, x + w / 2, y + h / 2],
            "confidence": conf, "class_id": cid}


def backend(name="botsort_locked", buffer=750):
    return create_tracker_backend(
        name, track_activation_threshold=0.25,
        minimum_matching_threshold=0.9, frame_rate=FPS,
        lost_track_buffer=buffer)


def run(be, frames):
    out = {}
    for f in range(1, max(frames) + 1):
        res = be.update(frames.get(f, []), f)
        out[f] = [r["track_id"] for r in res]
    return out


@pytest.fixture
def guard_on(monkeypatch):
    monkeypatch.setattr(cfg, "EMERGENCE_GUARD", True)


class TestEmergenceGuard:
    def test_emergent_neighbor_births_new_track(self, guard_on):
        # A drives east at 4 px/f. At f=40 vehicle B emerges adjacent
        # (one lane over, stationary at first detection burst then
        # moving). A's own detection continues on its line. Without
        # the guard the widened/adjacent box can win A's row on IoU;
        # with it, B must appear under a NEW id and A keeps its line.
        frames = {}
        for f in range(1, 81):
            ds = [det(100.0 + 4.0 * f, 300.0)]
            if f >= 40:
                ds.append(det(100.0 + 4.0 * 40 + 2.0 * (f - 40), 340.0))
            frames[f] = ds
        be = backend()
        out = run(be, frames)
        tid = out[30][0]
        assert tid in out[80]                    # A kept its identity
        assert len(out[80]) == 2                 # B exists...
        assert len(set(out[80])) == 2            # ...as a DIFFERENT id

    def test_smooth_turn_survives_guard(self, guard_on):
        # the over-eager-veto canary: a quarter-circle turn's own
        # detections must never be vetoed away from it
        import math
        frames = {}
        for f in range(1, 31):
            frames[f] = [det(100.0, 420.0 - 4.0 * f)]
        for k in range(1, 41):
            ang = (k / 40.0) * (math.pi / 2)
            frames[30 + k] = [det(100.0 + 80.0 * math.sin(ang),
                                  300.0 - 80.0 * (1 - math.cos(ang)))]
        be = backend()
        out = run(be, frames)
        tid = out[20][0]
        assert out[70] == [tid]
        assert not be.bot.gate_breaks

    def test_stopped_track_exempt(self, guard_on):
        # a dwelling vehicle has no direction to defend — the guard
        # never applies, and the dwell keeps its identity
        frames = {f: [det(200.0, 300.0)] for f in range(1, 61)}
        be = backend()
        out = run(be, frames)
        assert out[60] == [out[10][0]]

    def test_all_veto_goes_lost_not_stolen(self, guard_on):
        # an all-vetoed row goes LOST (recoverable), never claims the
        # suspicious detection; the jitter line continues tracked
        # under some identity (measured: the starvation unveto
        # re-enabled the theft, so it was removed)
        frames = {}
        for f in range(1, 41):
            frames[f] = [det(100.0 + 6.0 * f, 300.0)]
        for f in range(41, 51):                  # 60px lateral jump
            frames[f] = [det(100.0 + 6.0 * f, 360.0)]
        be = backend()
        out = run(be, frames)
        assert out[50], "the jitter line lost all coverage"

    def test_van_occlusion_original_keeps_identity(self, monkeypatch):
        # THE FILMED THEFT (scene 1): A occluded by a van for 7
        # frames while the dark follower B sits behind. Stock swaps
        # identities (A's id rides B; A reborn new). Guard: B births
        # its own id, A re-found under its ORIGINAL id.
        import backend.config as cfg
        monkeypatch.setattr(cfg, "EMERGENCE_GUARD", True)
        frames = {}
        for f in range(1, 81):
            ds = []
            if f < 40 or f > 46:
                ds.append(det(100.0 + 6.0 * f, 300.0, w=60.0, h=40.0))
            if f >= 40:
                # the follower sits a half car-length behind and one
                # lane over — beyond the box-size direction floor
                ds.append(det(100.0 + 6.0 * 38 - 30.0, 340.0,
                              w=60.0, h=40.0))
            frames[f] = ds
        be = create_tracker_backend(
            "botsort", track_activation_threshold=0.25,
            minimum_matching_threshold=0.8, frame_rate=FPS)
        out = {}
        pos = {}
        for f in range(1, 81):
            res = be.update(frames.get(f, []), f)
            out[f] = sorted(r["track_id"] for r in res)
            pos[f] = {r["track_id"]: r["bbox"][0] for r in res}
        tid = out[30][0]
        assert tid in out[80]                    # A kept its identity
        assert len(out[80]) == 2                 # B has its own
        assert pos[80][tid] > 500                # ...and A is far east
        assert be.bot.emergence_vetoes >= 1

    def test_theft_scene_guard_on(self, guard_on):
        # the flip-split theft shape: with the guard the southbound
        # thief detection is vetoed off A's row (wrong direction), so
        # A is never handed over — either the thief runs under a new
        # id or the old id never appears on the southbound leg
        frames = {f: [det(100.0, 400.0 - 4.0 * f)] for f in range(1, 41)}
        frames.update({f: [det(100.0, 240.0 + 4.0 * (f - 40))]
                       for f in range(41, 90)})
        be = backend()
        out = run(be, frames)
        tid = out[30][0]
        assert out[89] and tid not in out[89]
        assert be.bot.emergence_vetoes >= 1 or len(be.bot.gate_breaks) >= 1

    def test_flag_off_identical_to_stock(self):
        # byte-identical flag-off: same scenario twice, guard off —
        # output equals the pinned legacy behavior (theft then sever)
        frames = {f: [det(100.0, 400.0 - 4.0 * f)] for f in range(1, 41)}
        frames.update({f: [det(100.0, 240.0 + 4.0 * (f - 40))]
                       for f in range(41, 90)})
        be = backend()
        out = run(be, frames)
        assert be.bot.emergence_vetoes == 0
        assert len(be.bot.gate_breaks) >= 1      # legacy post-hoc sever


class TestConcealerOrigin:
    def _pipe(self):
        import numpy as np

        from backend.services.pipeline import ProcessingPipeline
        p = ProcessingPipeline.__new__(ProcessingPipeline)
        p._paths = []
        p.legs = [{"leg_id": 7, "gate_segment": None, "origin_zone": None,
                   "reference_heading": 0.0}]
        p.n_origin_flow_inferred = 0
        p.n_origin_concealer_inherited = 0
        # newborn at (100, 100) starting frame 50; concealer tid=1
        # alive there moving the same way (east)
        p._concealer_rows = np.array(
            [[45.0, 1.0, 80.0, 100.0], [50.0, 1.0, 100.0, 100.0],
             [55.0, 1.0, 120.0, 100.0]])
        p._origin_by_track = {1: (7, True)}
        p.active_vehicles = {}
        return p

    def test_unique_claimant_inherits(self):
        p = self._pipe()
        o = p._origin_concealer_infer(
            (100.0, 100.0), [(100.0, 100.0), (120.0, 100.0)],
            {"start_frame": 50}, 99)
        assert o == 7
        assert p.n_origin_concealer_inherited == 1

    def test_disagreeing_claimants_refused(self):
        import numpy as np
        p = self._pipe()
        p._concealer_rows = np.vstack([
            p._concealer_rows,
            [[45.0, 2.0, 100.0, 120.0], [50.0, 2.0, 120.0, 120.0],
             [55.0, 2.0, 140.0, 120.0]]])
        p._concealer_rows = p._concealer_rows[
            p._concealer_rows[:, 0].argsort(kind="stable")]
        p._origin_by_track = {1: (7, True), 2: (8, True)}
        p.legs.append({"leg_id": 8, "gate_segment": None,
                       "origin_zone": None, "reference_heading": 0.0})
        assert p._origin_concealer_infer(
            (100.0, 100.0), [(100.0, 100.0), (120.0, 100.0)],
            {"start_frame": 50}, 99) is None

    def test_inferred_origin_never_inherited(self):
        p = self._pipe()
        p._origin_by_track = {1: (7, False)}     # rescued/inferred origin
        assert p._origin_concealer_infer(
            (100.0, 100.0), [(100.0, 100.0), (120.0, 100.0)],
            {"start_frame": 50}, 99) is None

    def test_wrong_direction_concealer_refused(self):
        import numpy as np
        p = self._pipe()
        p._concealer_rows = np.array(              # concealer moves WEST
            [[45.0, 1.0, 120.0, 100.0], [50.0, 1.0, 100.0, 100.0],
             [55.0, 1.0, 80.0, 100.0]])
        assert p._origin_concealer_infer(
            (100.0, 100.0), [(100.0, 100.0), (120.0, 100.0)],
            {"start_frame": 50}, 99) is None

    def test_no_index_inert(self):
        p = self._pipe()
        del p._concealer_rows
        assert p._origin_concealer_infer(
            (100.0, 100.0), [(100.0, 100.0), (120.0, 100.0)],
            {"start_frame": 50}, 99) is None
