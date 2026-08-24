"""Gate supremacy (operator ruling 2026-08-24): a track with observed entry AND
exit gate crossings (tag='full') is classified by those crossings — path
matching may not override an observed exit. Measured before the change: path
matching overrode 146/176/247 full journeys per cam2 window on the control
basis, the top flip being gate-said-through vehicles relabeled right.

Mirrors test_partial_evidence.py's pipeline-wiring pattern: temp DB from
SCHEMA, canned gate evidence + canned joint scorer.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from backend.database import SCHEMA
from backend.services.pipeline import ProcessingPipeline


@pytest.fixture
def env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "project.db")
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        for lid, (label, card, head) in {1: ("N", "N", 180.0), 2: ("E", "E", 270.0),
                                         3: ("S", "S", 0.0)}.items():
            conn.execute(
                "INSERT INTO legs (leg_id, label, cardinal_direction, sort_order, "
                "origin_zone, reference_heading) VALUES (?, ?, ?, ?, ?, ?)",
                (lid, label, card, lid, json.dumps([[0, 0], [10, 0]]), head))
        conn.commit(); conn.close()
        yield {"db": db,
               "legs": [{"leg_id": 1, "label": "N", "cardinal_direction": "N",
                         "origin_zone": [[0, 0], [10, 0]], "reference_heading": 180.0},
                        {"leg_id": 2, "label": "E", "cardinal_direction": "E",
                         "origin_zone": [[0, 0], [10, 0]], "reference_heading": 270.0},
                        {"leg_id": 3, "label": "S", "cardinal_direction": "S",
                         "origin_zone": [[0, 0], [10, 0]], "reference_heading": 0.0}]}


P_A = {"path_id": 1, "origin_leg_id": 1, "destination_leg_id": 3,
       "movement_label": "through", "supporting_count": 10,
       "polyline": [[500, 0], [500, 800]]}
P_B = {"path_id": 2, "origin_leg_id": 2, "destination_leg_id": 3,
       "movement_label": "right", "supporting_count": 30,
       "polyline": [[0, 400], [500, 800]]}
P_C = {"path_id": 3, "origin_leg_id": 1, "destination_leg_id": 2,
       "movement_label": "left", "supporting_count": 50,
       "polyline": [[500, 0], [800, 400]]}

JOINT_A = {  # the path match: N -> S through
    "origin_leg_id": 1, "destination_leg_id": 3, "movement_label": "through",
    "path_id": 1, "distance": 5.0, "coverage": 0.5, "considered": 3,
    "entry_tiebreak_applied": False, "speed_tiebreak_applied": False,
    "candidates": [{"path": P_A, "cost": 5.0, "coverage": 0.5, "composite": 0.9}],
}


def _vehicle(origin=1):
    return {"origin_leg_id": origin, "reference_heading": 0.0, "origin_frame": 5,
            "trajectory": [(500.0, 100.0 + 30.0 * i) for i in range(20)],
            "confidences": [0.9] * 20, "last_center": (500, 700), "class_id": 2,
            "class_name": "car", "bbox_width": 100.0, "bbox_height": 60.0,
            "bbox_area": 6000.0, "start_frame": 0}


def _mk_pipe(env, paths):
    return ProcessingPipeline(project_id="test", db_path=env["db"],
                              video_path="unused.mp4", legs=env["legs"],
                              fps=10.0, paths=paths)


def _events(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM vehicle_events")]
    conn.close()
    return rows


def _enable(monkeypatch, **extra):
    import backend.services.pipeline as plmod
    monkeypatch.setattr(plmod, "ORIGIN_EVIDENCE_GATE_ENABLED", True)
    monkeypatch.setattr(plmod, "ORIGIN_POSTERIOR_ENABLED", True)
    for k, v in extra.items():
        monkeypatch.setattr(plmod, k, v)
    return plmod


def _canned(monkeypatch, plmod, gate, joint):
    monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                        lambda self, v: gate)
    monkeypatch.setattr(plmod, "score_path_joint",
                        lambda trajectory, paths, **kw: dict(joint))


def _run(env, monkeypatch, gate, joint=JOINT_A, paths=(P_A, P_B, P_C), **flags):
    plmod = _enable(monkeypatch, **flags)
    _canned(monkeypatch, plmod, gate, joint)
    p = _mk_pipe(env, list(paths))
    p.active_vehicles[9] = _vehicle()
    p._finalize_vehicle(9, frame_number=25)
    return p, _events(env["db"])


class TestGateSupremacy:
    def test_full_journey_exit_overrides_path_dest(self, env, monkeypatch):
        """Gates saw exit at leg 2; the path match says leg 3. Gates win, and
        movement comes from the (1,2) cell path's label (P_C: left)."""
        p, evs = _run(env, monkeypatch, gate=(1, 2, "full"))
        assert len(evs) == 1
        e = evs[0]
        assert e["destination_leg_id"] == 2
        assert e["movement"] == "left"          # P_C's label for cell (1,2)
        assert e["posterior_source"] == "gate_full"
        assert p.n_gate_supremacy == 1

    def test_gate_origin_also_overrides(self, env, monkeypatch):
        """Gates saw (2 -> 3); joint claimed (1 -> 3). Both legs follow gates;
        movement = P_B's label for cell (2,3)."""
        p, evs = _run(env, monkeypatch, gate=(2, 3, "full"))
        e = evs[0]
        assert e["origin_leg_id"] == 2
        assert e["destination_leg_id"] == 3
        assert e["movement"] == "right"
        assert e["posterior_source"] == "gate_full"
        assert p.n_gate_supremacy == 1

    def test_pathless_cell_derives_movement(self, env, monkeypatch):
        """Gates saw (2 -> 1) — no applied path for that cell. Movement is
        derived from leg geometry instead of dropped."""
        p, evs = _run(env, monkeypatch, gate=(2, 1, "full"))
        e = evs[0]
        assert e["destination_leg_id"] == 1
        assert e["movement"] in ("left", "right", "through", "u_turn")
        assert e["posterior_source"] == "gate_full"

    def test_agreeing_full_journey_is_untouched(self, env, monkeypatch):
        """Gates agree with the path match: no override, no counter, source
        stays None — byte-identical to pre-change behavior."""
        p, evs = _run(env, monkeypatch, gate=(1, 3, "full"))
        e = evs[0]
        assert e["destination_leg_id"] == 3 and e["movement"] == "through"
        assert e["posterior_source"] is None
        assert p.n_gate_supremacy == 0

    def test_entry_only_not_touched(self, env, monkeypatch):
        """Supremacy applies to FULL journeys only — an entry_only track keeps
        the path decision (that population belongs to the divergence work)."""
        p, evs = _run(env, monkeypatch, gate=(1, None, "entry_only"))
        e = evs[0]
        assert e["destination_leg_id"] == 3 and e["movement"] == "through"
        assert p.n_gate_supremacy == 0

    def test_flag_off_is_legacy(self, env, monkeypatch):
        """GATE_FULL_SUPREMACY off: the disagreeing full journey keeps the
        path decision exactly as before the change."""
        p, evs = _run(env, monkeypatch, gate=(1, 2, "full"),
                      GATE_FULL_SUPREMACY=False)
        e = evs[0]
        assert e["destination_leg_id"] == 3 and e["movement"] == "through"
        assert e["posterior_source"] is None
        assert p.n_gate_supremacy == 0
