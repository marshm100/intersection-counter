"""G-EX-2, the observed-exit binding (declared 2026-09-12, built 2026-09-20).

A track born past its entry gate whose EXIT crossing WAS observed is tagged
exit_only, which by construction carries no gate origin. The rescue block was
guarded on `gate_origin is not None`, so the journey dropped as
insufficient_data although the box side it left over was witnessed — against
CLAUDE.md's "the box sides ARE origin/destination gates", which the code
already honours for 'full' (gate supremacy) and 'entry_only' (rescue_supports).

Measured population on the vl3 basis: cam4 study_0700 had 637 exit_only tracks,
466 of them with no event at all, 445 exiting over N against a -360 NB_thru
shortfall.

Harness mirrors test_gate_supremacy.py: temp DB from SCHEMA, canned gate
evidence, and the destination chain canned to fail so the rescue block is the
thing under test.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from backend.database import SCHEMA
from backend.services.pipeline import ProcessingPipeline

# N / E / S, the test_gate_supremacy geometry.
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


def _vehicle(origin=1):
    """A far-field track: an origin from the heading tier, no gate entry."""
    return {"origin_leg_id": origin, "reference_heading": 0.0,
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


def _run(env, monkeypatch, gate, *, binding, paths=(P_THRU, P_LEFT), origin=1):
    """Drive one track through finalize with the destination chain canned to
    fail, so `movement` reaches the rescue block as insufficient_data."""
    import backend.services.pipeline as plmod
    monkeypatch.setattr(plmod, "ORIGIN_EVIDENCE_GATE_ENABLED", True)
    monkeypatch.setattr(plmod, "ORIGIN_POSTERIOR_ENABLED", True)
    monkeypatch.setattr(plmod, "GATE_EXIT_ONLY_BINDING", binding)
    monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                        lambda self, v: gate)
    # No path fit, no polyline destination, no softmax destination ->
    # derive_movement(origin_leg, None) == "insufficient_data".
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
                           fps=10.0, paths=list(paths))
    p.active_vehicles[9] = _vehicle(origin)
    p._finalize_vehicle(9, frame_number=250)
    return p, _events(env["db"])


class TestExitOnlyBinding:
    def test_off_by_default_the_journey_still_drops(self, env, monkeypatch):
        """The behaviour this rule exists to change: an observed exit, a
        refused destination, and the whole journey on the floor."""
        p, evs = _run(env, monkeypatch, gate=(None, 2, "exit_only"),
                      binding=False)
        assert evs == []
        assert p.n_exit_only_bound == 0
        assert p.n_insufficient_data == 1

    def test_binds_the_observed_exit(self, env, monkeypatch):
        """Gates saw the track leave over leg 2 and nothing else placed it.
        The exit binds; movement is the (1,2) cell path's own label."""
        p, evs = _run(env, monkeypatch, gate=(None, 2, "exit_only"),
                      binding=True)
        assert len(evs) == 1
        e = evs[0]
        assert e["destination_leg_id"] == 2
        assert e["origin_leg_id"] == 1
        assert e["movement"] == "left"           # P_LEFT's label for (1, 2)
        assert e["posterior_source"] == "rescue_exit"
        assert e["destination_confidence"] == 1.0
        assert p.n_exit_only_bound == 1
        assert p.n_insufficient_data == 0

    def test_bins_at_the_start_frame_not_the_finalize_frame(self, env, monkeypatch):
        """These tracks have no witnessed entry, so their birth is the best
        crossing estimate. Binning off the finalize frame would push the
        vehicle into a later 15-minute period (problem 7 is already a per-bin
        dispersion problem; this rule must not deepen it)."""
        _, evs = _run(env, monkeypatch, gate=(None, 2, "exit_only"),
                      binding=True)
        # start_frame 7 at 10 fps, NOT finalize frame 250.
        assert evs[0]["timestamp_video"] == pytest.approx(0.7)

    def test_refuses_a_u_turn(self, env, monkeypatch):
        """classify_pair's exit_only path never runs the u-turn admission
        tests, so a heading-tier origin equal to the exit leg would mint
        exactly the phantom u-turns the first-exit ruling killed."""
        p, evs = _run(env, monkeypatch, gate=(None, 2, "exit_only"),
                      binding=True, origin=2)
        assert evs == []
        assert p.n_exit_only_bound == 0

    def test_derives_movement_when_the_cell_has_no_path(self, env, monkeypatch):
        """No bank path for the cell -> derive_movement from the geometry,
        the rescue_full convention verbatim."""
        p, evs = _run(env, monkeypatch, gate=(None, 3, "exit_only"),
                      binding=True, paths=(P_LEFT,))
        assert len(evs) == 1
        assert evs[0]["destination_leg_id"] == 3
        assert evs[0]["movement"] not in (None, "insufficient_data")
        assert p.n_exit_only_bound == 1

    def test_other_tags_are_untouched(self, env, monkeypatch):
        """no_crossing is the other big dropped population (84-92% of those
        tracks on the vl3 windows) and this rule deliberately does not reach
        it: nothing was witnessed, so there is nothing to bind."""
        p, evs = _run(env, monkeypatch, gate=(None, None, "no_crossing"),
                      binding=True)
        assert evs == []
        assert p.n_exit_only_bound == 0

    def test_straight_fragment_rule_does_not_police_these(self, env, monkeypatch):
        """DOCUMENTING A DESIGN CONSEQUENCE, not asserting a guard. The
        trajectory here is dead straight and the movement is a LEFT, which is
        the straight-fragment rule's exact target — but that rule requires
        `posterior_source is None` and `destination_leg_id != gate_dest`, and a
        bound journey fails both. Evidence outranks the shape rule, the same
        way it does for gate_full. So the watch cells in the arm are the only
        check on turn inflation from this branch; the rule is not a backstop.
        """
        import backend.config as cfg
        assert cfg.STRAIGHT_FRAGMENT_RULE is True
        p, evs = _run(env, monkeypatch, gate=(None, 2, "exit_only"),
                      binding=True)
        assert len(evs) == 1
        assert evs[0]["movement"] == "left"
        assert getattr(p, "n_straight_dropped", 0) == 0
