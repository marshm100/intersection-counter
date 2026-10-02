"""THE NO-CROSSING SIDE DOOR (config.NOCROSS_NO_FALLBACK, arm nf1, 2026-09-26).

A track that crossed no gate and that the joint shape scorer refused was still
given a destination by the nearest-line fallbacks. When ON, it drops.
Harness mirrors test_full_journey_rescue.py: canned gate evidence, the joint
scorer canned to refuse, and a polyline fallback that WOULD name a destination.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

import backend.config as cfg
from backend.database import SCHEMA
from backend.services.pipeline import ProcessingPipeline
from backend.services.trajectory_classifier import (
    score_destination_by_polyline as plain,
    score_destination_by_polyline_extent as extent)

_LEGS = {1: ("N", "N", 180.0), 2: ("E", "E", 270.0), 3: ("S", "S", 0.0)}
P_LEFT = {"path_id": 3, "origin_leg_id": 1, "destination_leg_id": 2,
          "movement_label": "left", "supporting_count": 50,
          "polyline": [[500, 0], [800, 400]]}


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "project.db")
        conn = sqlite3.connect(db)
        conn.executescript(SCHEMA)
        for lid, (label, card, head) in _LEGS.items():
            conn.execute(
                "INSERT INTO legs (leg_id, label, cardinal_direction, sort_order, "
                "origin_zone, reference_heading) VALUES (?, ?, ?, ?, ?, ?)",
                (lid, label, card, lid, json.dumps([[0, 0], [10, 0]]), head))
        conn.commit(); conn.close()
        yield {"db": db,
               "legs": [{"leg_id": lid, "label": lb, "cardinal_direction": cd,
                         "origin_zone": [[0, 0], [10, 0]], "reference_heading": hd}
                        for lid, (lb, cd, hd) in _LEGS.items()]}


def _run(env, monkeypatch, gate, *, rule):
    import backend.services.pipeline as plmod
    monkeypatch.setattr(plmod, "ORIGIN_EVIDENCE_GATE_ENABLED", True)
    monkeypatch.setattr(plmod, "ORIGIN_POSTERIOR_ENABLED", True)
    monkeypatch.setattr(plmod, "NOCROSS_NO_FALLBACK", rule)
    monkeypatch.setattr(ProcessingPipeline, "_gate_evidence", lambda self, v: gate)
    monkeypatch.setattr(plmod, "score_path_joint", lambda trajectory, paths, **kw: {
        "origin_leg_id": None, "destination_leg_id": None, "movement_label": None,
        "path_id": None, "distance": 999.0, "coverage": 0.0, "considered": 0,
        "candidates": []})
    monkeypatch.setattr(plmod, "score_destination_by_polyline",
                        lambda trajectory, origin_leg_id, paths, **kw: {
                            "destination_leg_id": 2, "movement_label": "left",
                            "distance": 5.0, "path_id": 3, "considered": 1})
    p = ProcessingPipeline(project_id="test", db_path=env["db"], video_path="unused.mp4",
                           legs=env["legs"], fps=10.0, paths=[P_LEFT])
    p.active_vehicles[9] = {
        "origin_leg_id": 1, "reference_heading": 0.0,
        "trajectory": [(500.0, 100.0 + 30.0 * i) for i in range(20)],
        "confidences": [0.9] * 20, "last_center": (500, 700), "class_id": 2,
        "class_name": "car", "bbox_width": 100.0, "bbox_height": 60.0,
        "bbox_area": 6000.0, "start_frame": 7}
    p._finalize_vehicle(9, frame_number=250)
    conn = sqlite3.connect(env["db"])
    evs = conn.execute("SELECT movement FROM vehicle_events").fetchall()
    conn.close()
    return p, evs


class TestNoCrossNoFallback:
    def test_off_the_fallback_counts_it(self, env, monkeypatch):
        p, evs = _run(env, monkeypatch, (None, None, "no_crossing"), rule=False)
        assert len(evs) == 1       # the side door: counted with no evidence

    def test_on_a_no_crossing_track_drops(self, env, monkeypatch):
        p, evs = _run(env, monkeypatch, (None, None, "no_crossing"), rule=True)
        assert evs == []
        assert p.n_nocross_refused == 1

    def test_on_an_exit_witnessed_track_keeps_its_fallback(self, env, monkeypatch):
        # scope: ONLY tracks with no crossing at all
        p, evs = _run(env, monkeypatch, (None, 2, "exit_only"), rule=True)
        assert len(evs) == 1

    def test_shipped_default_on(self):
        assert cfg.NOCROSS_NO_FALLBACK is True        # arm nf1b, 2026-09-30


class TestExtentAwareFallback:
    """arm nf2: a path line only votes where it runs alongside the track."""
    # cam5's shape: the left line begins ~28 px further upstream than the through
    THRU = {"path_id": 1, "origin_leg_id": 9, "destination_leg_id": 7,
            "movement_label": "through", "supporting_count": 100,
            "polyline": [[508, 183], [300, 190], [13, 242]]}
    LEFT = {"path_id": 2, "origin_leg_id": 9, "destination_leg_id": 8,
            "movement_label": "left", "supporting_count": 20,
            "polyline": [[536, 184], [460, 190], [500, 300], [599, 375]]}
    STUB = [(568.0 - 4.0 * i, 182.0) for i in range(14)]   # x 568 -> 516

    def test_plain_fallback_calls_the_upstream_stub_left(self):
        r = plain(self.STUB, 9, [self.THRU, self.LEFT])
        assert r["movement_label"] == "left"          # the defect

    def test_extent_fallback_gives_the_upstream_stub_nothing(self):
        r = extent(self.STUB, 9, [self.THRU, self.LEFT])
        assert r["destination_leg_id"] is None

    def test_extent_fallback_keeps_a_track_on_the_turn(self):
        turn = [(470.0 + 3.0 * i, 215.0 + 10.0 * i) for i in range(8)]
        r = extent(turn, 9, [self.THRU, self.LEFT])
        assert r["movement_label"] == "left"

    def test_default_off(self):
        assert cfg.NOCROSS_EXTENT_FALLBACK is False


class TestExtentWiring:
    def _go(self, env, monkeypatch, verdict):
        import backend.services.pipeline as plmod
        monkeypatch.setattr(plmod, "NOCROSS_EXTENT_FALLBACK", True)
        monkeypatch.setattr(plmod, "score_destination_by_polyline_extent",
                            lambda traj, o, paths, **kw: verdict)
        return _run(env, monkeypatch, (None, None, "no_crossing"), rule=False)

    def test_no_shared_stretch_drops(self, env, monkeypatch):
        p, evs = self._go(env, monkeypatch, {"destination_leg_id": None,
                                             "movement_label": None,
                                             "distance": float("inf"),
                                             "path_id": None, "considered": 1})
        assert evs == [] and p.n_nocross_refused == 1

    def test_a_decision_on_the_shared_stretch_counts(self, env, monkeypatch):
        p, evs = self._go(env, monkeypatch, {"destination_leg_id": 2,
                                             "movement_label": "left",
                                             "distance": 5.0, "path_id": 3,
                                             "considered": 1})
        assert len(evs) == 1


class TestNoGateNoCount:
    """arm nc1 (config.NOCROSS_DROP_ALL): even a no_crossing track whose
    path shape the joint scorer DID match is not counted."""

    def _shape_matched(self, env, monkeypatch, drop_all):
        import backend.services.pipeline as plmod
        monkeypatch.setattr(plmod, "NOCROSS_DROP_ALL", drop_all)
        monkeypatch.setattr(plmod, "NOCROSS_NO_FALLBACK", False)
        monkeypatch.setattr(plmod, "ORIGIN_EVIDENCE_GATE_ENABLED", True)
        monkeypatch.setattr(plmod, "ORIGIN_POSTERIOR_ENABLED", True)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (None, None, "no_crossing"))
        monkeypatch.setattr(plmod, "score_destination_by_polyline",
                            lambda trajectory, origin_leg_id, paths, **kw: {
                                "destination_leg_id": 2, "movement_label": "left",
                                "distance": 5.0, "path_id": 3, "considered": 1})
        p = ProcessingPipeline(project_id="test", db_path=env["db"], video_path="unused.mp4",
                               legs=env["legs"], fps=10.0, paths=[P_LEFT])
        p.active_vehicles[9] = {
            "origin_leg_id": 1, "reference_heading": 0.0,
            "trajectory": [(500.0, 100.0 + 30.0 * i) for i in range(20)],
            "confidences": [0.9] * 20, "last_center": (500, 700), "class_id": 2,
            "class_name": "car", "bbox_width": 100.0, "bbox_height": 60.0,
            "bbox_area": 6000.0, "start_frame": 7}
        p._finalize_vehicle(9, frame_number=250)
        conn = sqlite3.connect(env["db"])
        evs = conn.execute("SELECT movement FROM vehicle_events").fetchall()
        conn.close()
        return evs

    def test_off_a_shape_matched_no_crossing_track_counts(self, env, monkeypatch):
        assert len(self._shape_matched(env, monkeypatch, False)) == 1

    def test_on_a_shape_matched_no_crossing_track_is_dropped(self, env, monkeypatch):
        assert self._shape_matched(env, monkeypatch, True) == []

    def test_an_exit_only_track_is_untouched(self, env, monkeypatch):
        import backend.services.pipeline as plmod
        monkeypatch.setattr(plmod, "NOCROSS_DROP_ALL", True)
        p, evs = _run(env, monkeypatch, (None, 2, "exit_only"), rule=True)
        assert len(evs) == 1

    def test_default_off(self):
        assert cfg.NOCROSS_DROP_ALL is False


class TestSmallBoxesNoGate:
    """arm nc2 (config.NOCROSS_DROP_SMALL): only SMALL no_crossing tracks
    (median box width < 5% of the frame width) are dropped."""

    def _run_width(self, env, monkeypatch, width, on=True):
        import backend.services.pipeline as plmod
        monkeypatch.setattr(plmod, "NOCROSS_DROP_SMALL", on)
        monkeypatch.setattr(plmod, "NOCROSS_NO_FALLBACK", False)
        monkeypatch.setattr(plmod, "ORIGIN_EVIDENCE_GATE_ENABLED", True)
        monkeypatch.setattr(plmod, "ORIGIN_POSTERIOR_ENABLED", True)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (None, None, "no_crossing"))
        monkeypatch.setattr(plmod, "score_destination_by_polyline",
                            lambda trajectory, origin_leg_id, paths, **kw: {
                                "destination_leg_id": 2, "movement_label": "left",
                                "distance": 5.0, "path_id": 3, "considered": 1})
        p = ProcessingPipeline(project_id="test", db_path=env["db"], video_path="unused.mp4",
                               legs=env["legs"], fps=10.0, paths=[P_LEFT])
        p._nocross_fw = 640                      # the corridor's frame width
        p.active_vehicles[9] = {
            "origin_leg_id": 1, "reference_heading": 0.0,
            "trajectory": [(500.0, 100.0 + 30.0 * i) for i in range(20)],
            "confidences": [0.9] * 20, "last_center": (500, 700), "class_id": 2,
            "class_name": "car", "bbox_width": width, "bbox_height": width * 0.6,
            "bbox_widths": [width] * 20,
            "bbox_area": width * width * 0.6, "start_frame": 7}
        p._finalize_vehicle(9, frame_number=250)
        conn = sqlite3.connect(env["db"])
        evs = conn.execute("SELECT movement FROM vehicle_events").fetchall()
        conn.close()
        return evs

    def test_a_small_far_no_crossing_track_drops(self, env, monkeypatch):
        assert self._run_width(env, monkeypatch, 18.0) == []

    def test_a_near_no_crossing_track_still_counts(self, env, monkeypatch):
        assert len(self._run_width(env, monkeypatch, 60.0)) == 1

    def test_off_the_small_track_counts(self, env, monkeypatch):
        assert len(self._run_width(env, monkeypatch, 18.0, on=False)) == 1

    def test_default_off(self):
        assert cfg.NOCROSS_DROP_SMALL is False and cfg.NOCROSS_SMALL_FRAC == 0.05
