"""Partial-evidence posterior (item-8 mechanism 1, posterior half) — stage-2
tests: the pure math, the score_path_joint candidates contract, and the
pipeline wiring for all three branches (canned scorer/evidence so geometry
can't flake; real-geometry behavior is stage 4's ablation on the corpus).
docs/plan_posterior_half_2026-07-15.md."""
import json
import os
import sqlite3
import tempfile

import pytest

from backend.database import SCHEMA
from backend.services import partial_evidence as pe
from backend.services.pipeline import ProcessingPipeline
from backend.services.trajectory_classifier import score_path_joint


# --- pure math --------------------------------------------------------------

def _cand(origin, dest, support, cost, path_id=None, movement="through"):
    return {"path": {"path_id": path_id, "origin_leg_id": origin,
                     "destination_leg_id": dest, "movement_label": movement,
                     "supporting_count": support},
            "cost": cost, "coverage": 0.5, "composite": 0.5}


class TestPosteriorMath:
    def test_origin_posterior_supports_dominate_equal_shape(self):
        marg, best = pe.origin_posterior(
            [_cand(1, 3, 10, 5.0), _cand(2, 3, 30, 5.0)])
        assert marg[2] > marg[1]
        assert abs(sum(marg.values()) - 1.0) < 1e-9
        assert best[2]["path"]["origin_leg_id"] == 2

    def test_origin_posterior_shape_can_overrule_supports(self):
        # a much better shape fit beats a modest support edge
        marg, _ = pe.origin_posterior(
            [_cand(1, 3, 20, 2.0), _cand(2, 3, 30, 40.0)])
        assert marg[1] > marg[2]

    def test_add_one_smoothing_keeps_zero_support_alive(self):
        marg, _ = pe.origin_posterior(
            [_cand(1, 3, 0, 5.0), _cand(2, 3, 5, 5.0)])
        assert marg[1] > 0.0
        assert marg[2] > marg[1]

    def test_marginalize_groups_same_leg(self):
        # two paths from the same origin pool their weight
        marg, best = pe.origin_posterior(
            [_cand(1, 3, 10, 5.0), _cand(1, 4, 10, 5.0), _cand(2, 3, 15, 5.0)])
        assert marg[1] > marg[2]
        assert best[1]["path"]["destination_leg_id"] in (3, 4)

    def test_tied_candidates_ratio_band(self):
        cands = [_cand(1, 2, 5, 10.0), _cand(1, 3, 5, 11.0), _cand(1, 4, 5, 13.0)]
        tied = pe.tied_candidates(cands, 10.0, 0.15)
        assert {c["path"]["destination_leg_id"] for c in tied} == {2, 3}

    def test_tied_candidates_subpixel_winner(self):
        cands = [_cand(1, 2, 5, 0.2), _cand(1, 3, 5, 0.8), _cand(1, 4, 5, 9.0)]
        tied = pe.tied_candidates(cands, 0.2, 0.15)
        assert {c["path"]["destination_leg_id"] for c in tied} == {2, 3}

    def test_supports_posterior_proportions(self):
        paths = [{"destination_leg_id": 2, "supporting_count": 30,
                  "movement_label": "through"},
                 {"destination_leg_id": 3, "supporting_count": 10,
                  "movement_label": "right"}]
        marg, best = pe.supports_posterior(paths)
        assert marg[2] == pytest.approx(31.0 / 42.0)
        assert best[3]["movement_label"] == "right"

    def test_supports_posterior_empty(self):
        assert pe.supports_posterior([]) == ({}, {})


# --- score_path_joint candidates contract ------------------------------------

STRAIGHT = [{"path_id": 7, "origin_leg_id": 1, "destination_leg_id": 3,
             "movement_label": "through", "supporting_count": 9,
             "polyline": [[500, 0], [500, 400], [500, 800]]}]
# The partial-Frechet match is a polyline SUFFIX — the trajectory must reach
# the polyline's end to align (mid-turn ENTRY is forgiven, not early death).
TRAJ = [(500.0, 400.0 + 20.0 * i) for i in range(20)]


class TestCandidatesContract:
    def test_default_has_no_candidates_key(self):
        out = score_path_joint(TRAJ, STRAIGHT)
        assert "candidates" not in out

    def test_candidates_returned_and_admitted(self):
        out = score_path_joint(TRAJ, STRAIGHT, return_candidates=True)
        assert out["destination_leg_id"] == 3
        assert len(out["candidates"]) == 1
        c = out["candidates"][0]
        assert c["path"]["path_id"] == 7
        assert c["cost"] <= 35.0 and 0.0 < c["coverage"] <= 1.0

    def test_candidates_empty_on_short_trajectory(self):
        out = score_path_joint(TRAJ[:2], STRAIGHT, return_candidates=True)
        assert out["candidates"] == [] and out["destination_leg_id"] is None


# --- pipeline wiring (canned evidence + scorer; temp DB from SCHEMA) ---------

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


def _canned_joint(monkeypatch, plmod, result):
    monkeypatch.setattr(plmod, "score_path_joint",
                        lambda trajectory, paths, **kw: dict(result))


class TestPipelineWiring:
    def test_flags_off_is_legacy(self, env):
        """Default flags OFF: no posterior columns, no counter movement."""
        p = _mk_pipe(env, [P_A, P_B])
        p.active_vehicles[9] = _vehicle()
        p._finalize_vehicle(9, frame_number=25)
        evs = _events(env["db"])
        assert len(evs) == 1
        assert evs[0]["origin_posterior_json"] is None
        assert evs[0]["origin_margin"] is None
        assert evs[0]["posterior_source"] is None
        assert (p.n_posterior_origin, p.n_posterior_dest,
                p.n_posterior_rescued, p.n_origin_ambiguous) == (0, 0, 0, 0)

    def test_branch1_unevidenced_origin_posterior(self, env, monkeypatch):
        """Unevidenced track: origin re-picked at the posterior max (supports
        beat the composite's flip pick), posterior + margin persisted. The
        rival is a THROUGH from the other origin — a straight track keeps
        through candidates (the collinear-flip class branch 1 exists for);
        turn candidates on straight tracks are the veto test below."""
        plmod = _enable(monkeypatch)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (None, None, "no_crossing"))
        pb_thru = {**P_B, "movement_label": "through"}
        _canned_joint(monkeypatch, plmod, {
            "origin_leg_id": 1, "destination_leg_id": 3, "movement_label":
            "through", "path_id": 1, "distance": 5.0, "coverage": 0.5,
            "considered": 2, "entry_tiebreak_applied": False,
            "speed_tiebreak_applied": False,
            "candidates": [{"path": P_A, "cost": 5.0, "coverage": 0.5,
                            "composite": 0.9},
                           {"path": pb_thru, "cost": 5.0, "coverage": 0.5,
                            "composite": 0.8}]})
        p = _mk_pipe(env, [P_A, pb_thru])
        p.active_vehicles[9] = _vehicle()
        p._finalize_vehicle(9, frame_number=25)
        evs = _events(env["db"])
        assert len(evs) == 1
        e = evs[0]
        assert e["origin_leg_id"] == 2          # pb_thru: 31/41 of the weight
        assert e["movement"] == "through"
        post = json.loads(e["origin_posterior_json"])
        assert set(post) == {"1", "2"} and post["2"] > post["1"]
        assert 0.0 < e["origin_margin"] < 1.0
        assert p.n_posterior_origin == 1
        assert p.n_origin_ambiguous == 0        # margin ~0.49 > floor 0.25
        assert e["posterior_source"] == "branch1"

    def test_branch1_exit_evidence_filters_candidates(self, env, monkeypatch):
        """exit_only evidence pins the destination before the posterior."""
        plmod = _enable(monkeypatch)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (None, 2, "exit_only"))
        _canned_joint(monkeypatch, plmod, {
            "origin_leg_id": 2, "destination_leg_id": 3, "movement_label":
            "right", "path_id": 2, "distance": 5.0, "coverage": 0.5,
            "considered": 3, "entry_tiebreak_applied": False,
            "speed_tiebreak_applied": False,
            "candidates": [{"path": P_B, "cost": 5.0, "coverage": 0.5,
                            "composite": 0.9},
                           {"path": P_C, "cost": 6.0, "coverage": 0.5,
                            "composite": 0.8}]})
        p = _mk_pipe(env, [P_A, P_B, P_C])
        p.active_vehicles[9] = _vehicle()
        p._finalize_vehicle(9, frame_number=25)
        e = _events(env["db"])[0]
        # only P_C exits at leg 2 -> the posterior pool collapses to it
        assert e["destination_leg_id"] == 2 and e["movement"] == "left"
        assert json.loads(e["origin_posterior_json"]) == {"1": 1.0}
        assert e["origin_margin"] == 1.0

    def test_branch1_ambiguous_flag_counter(self, env, monkeypatch):
        """Near-equal supports -> margin under the floor -> ambiguous counter."""
        plmod = _enable(monkeypatch, ORIGIN_POSTERIOR_MARGIN_FLOOR=0.25)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (None, None, "no_crossing"))
        pa = {**P_A, "supporting_count": 10}
        pb = {**P_B, "movement_label": "through", "supporting_count": 12}
        _canned_joint(monkeypatch, plmod, {
            "origin_leg_id": 1, "destination_leg_id": 3, "movement_label":
            "through", "path_id": 1, "distance": 5.0, "coverage": 0.5,
            "considered": 2, "entry_tiebreak_applied": False,
            "speed_tiebreak_applied": False,
            "candidates": [{"path": pa, "cost": 5.0, "coverage": 0.5,
                            "composite": 0.9},
                           {"path": pb, "cost": 5.0, "coverage": 0.5,
                            "composite": 0.8}]})
        p = _mk_pipe(env, [pa, pb])
        p.active_vehicles[9] = _vehicle()
        p._finalize_vehicle(9, frame_number=25)
        e = _events(env["db"])[0]
        assert e["origin_margin"] < 0.25
        assert p.n_origin_ambiguous == 1

    def test_branch2_truncated_dest_tie(self, env, monkeypatch):
        """Evidenced entry_only track with cost-tied candidates to different
        destinations: supports re-pick the cell; posterior flows through the
        existing destination columns."""
        plmod = _enable(monkeypatch, DEST_TIE_BAND=0.15)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (1, None, "entry_only"))
        _canned_joint(monkeypatch, plmod, {
            "origin_leg_id": 1, "destination_leg_id": 3, "movement_label":
            "through", "path_id": 1, "distance": 10.0, "coverage": 0.5,
            "considered": 2, "entry_tiebreak_applied": False,
            "speed_tiebreak_applied": False,
            "candidates": [{"path": P_A, "cost": 10.0, "coverage": 0.5,
                            "composite": 0.9},
                           {"path": P_C, "cost": 10.5, "coverage": 0.5,
                            "composite": 0.85}]})
        p = _mk_pipe(env, [P_A, P_C])
        p.active_vehicles[9] = _vehicle()
        p._finalize_vehicle(9, frame_number=25)
        e = _events(env["db"])[0]
        assert e["destination_leg_id"] == 2     # P_C: 51 supports vs 11
        assert e["movement"] == "left"
        post = json.loads(e["destination_posterior_json"])
        assert set(post) == {"2", "3"} and post["2"] > post["3"]
        assert e["destination_margin"] < 1.0
        assert p.n_posterior_dest == 1
        assert e["origin_posterior_json"] is None   # branch 1 did not fire

    def test_branch2_out_of_band_rival_no_fire(self, env, monkeypatch):
        plmod = _enable(monkeypatch, DEST_TIE_BAND=0.15)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (1, None, "entry_only"))
        _canned_joint(monkeypatch, plmod, {
            "origin_leg_id": 1, "destination_leg_id": 3, "movement_label":
            "through", "path_id": 1, "distance": 10.0, "coverage": 0.5,
            "considered": 2, "entry_tiebreak_applied": False,
            "speed_tiebreak_applied": False,
            "candidates": [{"path": P_A, "cost": 10.0, "coverage": 0.5,
                            "composite": 0.9},
                           {"path": P_C, "cost": 20.0, "coverage": 0.5,
                            "composite": 0.5}]})
        p = _mk_pipe(env, [P_A, P_C])
        p.active_vehicles[9] = _vehicle()
        p._finalize_vehicle(9, frame_number=25)
        e = _events(env["db"])[0]
        assert e["destination_leg_id"] == 3 and p.n_posterior_dest == 0

    def test_rescue_full_journey_counts_hard(self, env, monkeypatch):
        """Evidenced box-full track the whole chain fails to place is counted
        at the evidenced cell instead of dropped (phase-0's unclaimed pool)."""
        plmod = _enable(monkeypatch)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (1, 3, "full"))
        _canned_joint(monkeypatch, plmod, {
            "origin_leg_id": None, "destination_leg_id": None,
            "movement_label": None, "path_id": None, "distance": float("inf"),
            "coverage": 0.0, "considered": 2,
            "entry_tiebreak_applied": False, "speed_tiebreak_applied": False,
            "candidates": []})
        monkeypatch.setattr(plmod, "score_destination_by_polyline",
                            lambda *a, **k: None)
        monkeypatch.setattr(plmod, "score_destination_leg",
                            lambda *a, **k: {"destination_leg_id": None,
                                             "confidence": 0.0, "posterior": {}})
        p = _mk_pipe(env, [P_A, P_B])
        p.active_vehicles[9] = _vehicle()
        p._finalize_vehicle(9, frame_number=25)
        evs = _events(env["db"])
        assert len(evs) == 1
        e = evs[0]
        assert (e["origin_leg_id"], e["destination_leg_id"]) == (1, 3)
        assert e["movement"] == "through"       # P_A's label at the cell
        assert p.n_posterior_rescued == 1
        assert p.n_insufficient_data == 0
        assert e["posterior_source"] == "rescue_full"

    def test_rescue_entry_only_supports_posterior(self, env, monkeypatch):
        plmod = _enable(monkeypatch)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (1, None, "entry_only"))
        _canned_joint(monkeypatch, plmod, {
            "origin_leg_id": None, "destination_leg_id": None,
            "movement_label": None, "path_id": None, "distance": float("inf"),
            "coverage": 0.0, "considered": 2,
            "entry_tiebreak_applied": False, "speed_tiebreak_applied": False,
            "candidates": []})
        monkeypatch.setattr(plmod, "score_destination_by_polyline",
                            lambda *a, **k: None)
        monkeypatch.setattr(plmod, "score_destination_leg",
                            lambda *a, **k: {"destination_leg_id": None,
                                             "confidence": 0.0, "posterior": {}})
        p = _mk_pipe(env, [P_A, P_C])         # origin-1 cells: ->3 (10), ->2 (50)
        p.active_vehicles[9] = _vehicle()
        p._finalize_vehicle(9, frame_number=25)
        e = _events(env["db"])[0]
        assert e["destination_leg_id"] == 2     # supports pick P_C's cell
        assert e["movement"] == "left"
        post = json.loads(e["destination_posterior_json"])
        assert post["2"] == pytest.approx(51.0 / 62.0, abs=1e-3)
        assert p.n_posterior_rescued == 1
        assert e["posterior_source"] == "rescue_supports"

    def test_branch1_straight_track_turn_veto(self, env, monkeypatch):
        """The cam1 sweep defect (2026-07-15): a STRAIGHT unevidenced track
        whose only admitted candidate is a wrong-origin TURN must not be
        counted there by the posterior — the rewrite-gate rule applies
        per-candidate, the pool empties, and legacy fallback proceeds."""
        plmod = _enable(monkeypatch)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (None, None, "no_crossing"))
        # as the real chain would look: the winner-only rewrite gate already
        # nulled the composite pick; the vetoed turn is still in candidates
        _canned_joint(monkeypatch, plmod, {
            "origin_leg_id": 2, "destination_leg_id": None, "movement_label":
            None, "path_id": None, "distance": 5.0, "coverage": 0.5,
            "considered": 1, "entry_tiebreak_applied": False,
            "speed_tiebreak_applied": False,
            "candidates": [{"path": P_B, "cost": 5.0, "coverage": 0.5,
                            "composite": 0.9}]})
        monkeypatch.setattr(plmod, "score_destination_by_polyline",
                            lambda *a, **k: None)
        monkeypatch.setattr(plmod, "score_destination_leg",
                            lambda *a, **k: {"destination_leg_id": 3,
                                             "confidence": 0.5,
                                             "posterior": {3: 1.0}})
        p = _mk_pipe(env, [P_A, P_B])
        # distinct zones so the straight track's nearest origin is leg 1
        p.legs = [dict(l) for l in env["legs"]]
        p.legs[0]["origin_zone"] = [[500, 80], [510, 80]]
        p.legs[1]["origin_zone"] = [[0, 400], [10, 400]]
        p.legs[2]["origin_zone"] = [[500, 900], [510, 900]]
        p.active_vehicles[9] = _vehicle()          # straight, starts (500,100)
        p._finalize_vehicle(9, frame_number=25)
        evs = _events(env["db"])
        assert len(evs) == 1
        e = evs[0]
        assert e["origin_posterior_json"] is None  # branch 1 stood down
        assert e["origin_leg_id"] == 1             # legacy provisional origin
        assert p.n_posterior_vetoed == 1
        assert p.n_posterior_origin == 0

    def test_branch1_curved_track_turn_not_vetoed(self, env, monkeypatch):
        """A genuinely CURVED track keeps its turn candidates — the veto is
        straightness-gated, same constant as the rewrite gate."""
        plmod = _enable(monkeypatch)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (None, None, "no_crossing"))
        _canned_joint(monkeypatch, plmod, {
            "origin_leg_id": 2, "destination_leg_id": 3, "movement_label":
            "right", "path_id": 2, "distance": 5.0, "coverage": 0.5,
            "considered": 1, "entry_tiebreak_applied": False,
            "speed_tiebreak_applied": False,
            "candidates": [{"path": P_B, "cost": 5.0, "coverage": 0.5,
                            "composite": 0.9}]})
        p = _mk_pipe(env, [P_A, P_B])
        import math
        veh = _vehicle()
        veh["trajectory"] = [(500.0 + 300.0 * math.cos(math.pi * (1.5 + t / 40.0)),
                              400.0 + 300.0 * math.sin(math.pi * (1.5 + t / 40.0)))
                             for t in range(20)]          # quarter-arc: curved
        p.active_vehicles[9] = veh
        p._finalize_vehicle(9, frame_number=25)
        e = _events(env["db"])[0]
        assert e["origin_posterior_json"] is not None
        assert e["movement"] == "right"
        assert p.n_posterior_vetoed == 0
        assert p.n_posterior_origin == 1

    def test_unevidenced_drop_stays_dropped(self, env, monkeypatch):
        """No evidence + nothing admitted -> still dropped (the popularity-
        snap guard: rescue never fires without an evidenced origin)."""
        plmod = _enable(monkeypatch)
        monkeypatch.setattr(ProcessingPipeline, "_gate_evidence",
                            lambda self, v: (None, None, "no_crossing"))
        _canned_joint(monkeypatch, plmod, {
            "origin_leg_id": None, "destination_leg_id": None,
            "movement_label": None, "path_id": None, "distance": float("inf"),
            "coverage": 0.0, "considered": 2,
            "entry_tiebreak_applied": False, "speed_tiebreak_applied": False,
            "candidates": []})
        monkeypatch.setattr(plmod, "score_destination_by_polyline",
                            lambda *a, **k: None)
        monkeypatch.setattr(plmod, "score_destination_leg",
                            lambda *a, **k: {"destination_leg_id": None,
                                             "confidence": 0.0, "posterior": {}})
        p = _mk_pipe(env, [P_A, P_B])
        p.active_vehicles[9] = _vehicle()
        p._finalize_vehicle(9, frame_number=25)
        assert _events(env["db"]) == []
        assert p.n_insufficient_data == 1
        assert p.n_posterior_rescued == 0
