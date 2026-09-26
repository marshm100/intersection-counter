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

    def test_default_off(self):
        assert cfg.NOCROSS_NO_FALLBACK is False
