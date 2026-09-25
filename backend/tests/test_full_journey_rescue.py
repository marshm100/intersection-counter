"""THE FULL-JOURNEY RESCUE (config.FULL_JOURNEY_RESCUE, arm fr1, 2026-09-25).

classify_trajectory reads a near-field-to-far-field right turn as a ~142 deg
heading change under perspective, sends it down the u-turn branch, and the
u-turn displacement test returns insufficient_data — so a track WITNESSED
entering one gate and exiting another was dropped before gate supremacy could
label it (cam5 W->S: 99/100/146 a window). The rescue lets such a journey reach
the gate labelling, except when the track doubles back (ID corruption).

Harness mirrors test_gate_exit_binding.py: canned gate evidence, the
classifier canned to the u-turn branch's insufficient_data, and the destination
chain canned to fail so the gate labelling is the thing under test.
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


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "project.db")
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        for lid, (label, card, head) in _LEGS.items():
            conn.execute(
                "INSERT INTO legs (leg_id, label, cardinal_direction, sort_order, "
                "origin_zone, reference_heading) VALUES (?, ?, ?, ?, ?, ?)",
                (lid, label, card, lid, json.dumps([[0, 0], [10, 0]]), head))
        conn.commit()
        conn.close()
        yield {"db": db,
               "legs": [{"leg_id": lid, "label": lb, "cardinal_direction": cd,
                         "origin_zone": [[0, 0], [10, 0]], "reference_heading": hd}
                        for lid, (lb, cd, hd) in _LEGS.items()]}


P_THRU = {"path_id": 1, "origin_leg_id": 1, "destination_leg_id": 3,
          "movement_label": "through", "supporting_count": 40,
          "polyline": [[500, 0], [500, 800]]}
P_LEFT = {"path_id": 3, "origin_leg_id": 1, "destination_leg_id": 2,
          "movement_label": "left", "supporting_count": 50,
          "polyline": [[500, 0], [800, 400]]}


def _vehicle():
    return {"origin_leg_id": 1, "reference_heading": 0.0,
            "trajectory": [(500.0, 100.0 + 30.0 * i) for i in range(20)],
            "confidences": [0.9] * 20, "last_center": (500, 700), "class_id": 2,
            "class_name": "car", "bbox_width": 100.0, "bbox_height": 60.0,
            "bbox_area": 6000.0, "start_frame": 7}


def _events(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM vehicle_events")]
    conn.close()
    return rows


def _run(env, monkeypatch, gate, *, rescue, straightness):
    import backend.services.pipeline as plmod
    monkeypatch.setattr(plmod, "ORIGIN_EVIDENCE_GATE_ENABLED", True)
    monkeypatch.setattr(plmod, "ORIGIN_POSTERIOR_ENABLED", True)
    monkeypatch.setattr(plmod, "FULL_JOURNEY_RESCUE", rescue)
    monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                        lambda self, v: gate)
    # the u-turn branch's insufficient_data: metrics present, movement refused
    monkeypatch.setattr(plmod, "classify_trajectory",
                        lambda traj, ref, **kw: {
                            "movement": "insufficient_data", "confidence": 0.0,
                            "net_heading_change": 142.0,
                            "cumulative_curvature": 150.0,
                            "path_straightness": straightness,
                            "path_distance": 180.0, "num_points": len(traj)})
    monkeypatch.setattr(plmod, "score_path_joint",
                        lambda trajectory, paths, **kw: {
                            "origin_leg_id": None, "destination_leg_id": None,
                            "movement_label": None, "path_id": None,
                            "distance": 999.0, "coverage": 0.0,
                            "considered": 0, "candidates": []})
    monkeypatch.setattr(plmod, "score_destination_by_polyline",
                        lambda trajectory, origin_leg_id, paths, **kw: None)
    monkeypatch.setattr(plmod, "score_destination_leg",
                        lambda trajectory, origin_leg_id, legs, **kw: {
                            "destination_leg_id": None, "confidence": 0.0,
                            "posterior": {}})
    p = ProcessingPipeline(project_id="test", db_path=env["db"],
                           video_path="unused.mp4", legs=env["legs"],
                           fps=10.0, paths=[P_THRU, P_LEFT])
    p.active_vehicles[9] = _vehicle()
    p._finalize_vehicle(9, frame_number=250)
    return p, _events(env["db"])


class TestFullJourneyRescue:
    def test_off_the_witnessed_journey_drops(self, env, monkeypatch):
        """The defect, reproduced with the flag off: entered over N, exited
        over E, and dropped as insufficient data."""
        p, evs = _run(env, monkeypatch, gate=(1, 2, "full"), rescue=False,
                      straightness=0.43)
        assert evs == []
        assert p.n_insufficient_data == 1

    def test_on_the_journey_counts_at_its_gate_cell(self, env, monkeypatch):
        p, evs = _run(env, monkeypatch, gate=(1, 2, "full"), rescue=True,
                      straightness=0.43)
        assert len(evs) == 1
        ev = evs[0]
        assert (ev["origin_leg_id"], ev["destination_leg_id"]) == (1, 2)
        assert ev["movement"] == "left"          # the cell's path label
        assert ev["posterior_source"] in ("rescue_full", "gate_full")
        assert p.n_full_journey_rescued == 1
        assert p.n_insufficient_data == 0

    def test_a_track_that_doubles_back_stays_dropped(self, env, monkeypatch):
        """Straightness ~0.04: the ID-corruption class the u-turn test exists
        to reject. Witnessed gates do not rescue it."""
        p, evs = _run(env, monkeypatch, gate=(1, 3, "full"), rescue=True,
                      straightness=0.04)
        assert evs == []
        assert p.n_insufficient_data == 1

    def test_entry_only_is_not_rescued_here(self, env, monkeypatch):
        p, evs = _run(env, monkeypatch, gate=(1, None, "entry_only"),
                      rescue=True, straightness=0.43)
        assert evs == []
        assert p.n_insufficient_data == 1

    def test_same_leg_journey_is_not_rescued(self, env, monkeypatch):
        """origin == exit is a u-turn claim; the u-turn tests stand."""
        p, evs = _run(env, monkeypatch, gate=(1, 1, "full"), rescue=True,
                      straightness=0.43)
        assert evs == []
        assert p.n_insufficient_data == 1

    def test_default_off_one_declared_constant(self):
        assert cfg.FULL_JOURNEY_RESCUE is False
        assert cfg.FULL_RESCUE_MIN_STRAIGHTNESS == 0.25
