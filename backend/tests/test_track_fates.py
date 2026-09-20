"""THE JOURNEY FATE LEDGER (2026-09-20, config TRACK_FATE_LEDGER).

vehicle_events explains every journey we counted or rejected. Nothing explained
the ~18% of tracks that produce no event at all — they all landed in one
`insufficient_data` counter (the fleet log's `dropped=`), which is why the
UNDERCOUNTS were not diagnosable. This writes one `track_fates` row per
finalized track at each of the six silent-return sites in
_finalize_vehicle_data plus the counted path.

Generalises scripts/cam5_sbinsuf_diag.py, which did this for one cell on one
camera by monkeypatching the finalize method and diffing a counter.

The contract these tests hold: the ledger is DIAGNOSTICS ONLY. A run with it
off must be identical in the counts.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from backend.database import SCHEMA
from backend.services.pipeline import ProcessingPipeline

_LEGS = {1: ("N", "N", 180.0), 2: ("E", "E", 270.0), 3: ("S", "S", 0.0)}


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for lid, (label, card, head) in _LEGS.items():
        conn.execute(
            "INSERT INTO legs (leg_id, label, cardinal_direction, sort_order, "
            "origin_zone, reference_heading) VALUES (?, ?, ?, ?, ?, ?)",
            (lid, label, card, lid, json.dumps([[0, 0], [10, 0]]), head))
    conn.commit()
    conn.close()


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "project.db")
        _make_db(db)
        yield {"dir": tmp, "db": db,
               "legs": [{"leg_id": lid, "label": lb, "cardinal_direction": cd,
                         "origin_zone": [[0, 0], [10, 0]], "reference_heading": hd}
                        for lid, (lb, cd, hd) in _LEGS.items()]}


P_THRU = {"path_id": 1, "origin_leg_id": 1, "destination_leg_id": 3,
          "movement_label": "through", "supporting_count": 40,
          "polyline": [[500, 0], [500, 800]]}


def _vehicle(**over):
    v = {"origin_leg_id": 1, "reference_heading": 180.0, "origin_frame": 5,
         "trajectory": [(500.0, 100.0 + 30.0 * i) for i in range(20)],
         "confidences": [0.9] * 20, "last_center": (500, 700), "class_id": 2,
         "class_name": "car", "bbox_width": 100.0, "bbox_height": 60.0,
         "bbox_area": 6000.0, "start_frame": 3, "last_seen_frame": 22}
    v.update(over)
    return v


def _pipe(env, paths=(P_THRU,), **kw):
    return ProcessingPipeline(project_id="test", db_path=env["db"],
                              video_path="unused.mp4", legs=env["legs"],
                              fps=10.0, paths=list(paths), **kw)


def _fates(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM track_fates ORDER BY fate_id")]
    conn.close()
    return rows


def _events(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM vehicle_events ORDER BY event_id")]
    conn.close()
    return rows


def _no_dest(monkeypatch, plmod):
    """Cancel the whole destination chain -> derive_movement(origin, None)."""
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


class TestEveryExitLeavesARow:
    def test_counted(self, env, monkeypatch):
        p = _pipe(env)
        p.active_vehicles[1] = _vehicle()
        p._finalize_vehicle(1, frame_number=30)
        rows = _fates(env["db"])
        assert len(rows) == 1
        r = rows[0]
        assert r["disposition"] == "counted"
        assert r["reason"] == "counted"
        assert r["vehicle_track_id"] == 1
        assert r["movement"] is not None
        assert len(_events(env["db"])) == 1

    def test_no_origin(self, env, monkeypatch):
        monkeypatch.setattr(ProcessingPipeline, "_origin_rescue",
                            lambda self, birth, prefix, **kw: None)
        p = _pipe(env)
        p.active_vehicles[2] = _vehicle(origin_leg_id=None)
        p._finalize_vehicle(2, frame_number=30)
        rows = _fates(env["db"])
        assert [r["reason"] for r in rows] == ["no_origin"]
        assert rows[0]["disposition"] == "dropped"
        assert _events(env["db"]) == []

    def test_no_origin_short_track_was_counted_by_nothing(self, env, monkeypatch):
        """A track under ORIGIN_ASSIGN_MIN_FRAMES has always dropped here and
        incremented no counter at all. The ledger is the first thing to see it."""
        monkeypatch.setattr(ProcessingPipeline, "_origin_rescue",
                            lambda self, birth, prefix, **kw: None)
        p = _pipe(env)
        p.active_vehicles[3] = _vehicle(origin_leg_id=None,
                                        trajectory=[(500.0, 100.0)])
        p._finalize_vehicle(3, frame_number=30)
        assert [r["reason"] for r in _fates(env["db"])] == ["no_origin"]
        assert p.n_no_origin_short == 1
        assert p.n_insufficient_data == 0

    def test_empty_trajectory(self, env):
        p = _pipe(env)
        p.active_vehicles[4] = _vehicle(trajectory=[])
        p._finalize_vehicle(4, frame_number=30)
        rows = _fates(env["db"])
        assert [r["reason"] for r in rows] == ["empty_trajectory"]
        assert rows[0]["n_points"] == 0
        assert p.n_empty_trajectory == 1

    def test_quality_filtered(self, env, monkeypatch):
        import backend.services.pipeline as plmod
        monkeypatch.setattr(plmod, "track_quality",
                            lambda traj, confs: (False, "clutter"))
        p = _pipe(env, calibration_params={"track_quality_filter": 1})
        p.active_vehicles[5] = _vehicle()
        p._finalize_vehicle(5, frame_number=30)
        assert [r["reason"] for r in _fates(env["db"])] == ["quality_filtered"]
        assert p.n_quality_filtered == 1

    def test_classifier_insufficient(self, env, monkeypatch):
        import backend.services.pipeline as plmod
        monkeypatch.setattr(plmod, "classify_trajectory",
                            lambda *a, **kw: {"movement": "insufficient_data",
                                              "confidence": 0.0,
                                              "net_heading_change": 0.0,
                                              "cumulative_curvature": 0.0,
                                              "path_straightness": 0.99,
                                              "path_distance": 12.0,
                                              "num_points": 3})
        p = _pipe(env)
        p.active_vehicles[6] = _vehicle()
        p._finalize_vehicle(6, frame_number=30)
        rows = _fates(env["db"])
        assert [r["reason"] for r in rows] == ["classifier_insufficient"]
        # the classifier's shape factors ride along so a dropped population
        # can be characterised without re-reading the dump
        assert rows[0]["path_straightness"] == pytest.approx(0.99)
        assert rows[0]["path_distance"] == pytest.approx(12.0)

    def test_derive_insufficient(self, env, monkeypatch):
        import backend.services.pipeline as plmod
        _no_dest(monkeypatch, plmod)
        p = _pipe(env)
        p.active_vehicles[7] = _vehicle()
        p._finalize_vehicle(7, frame_number=30)
        assert [r["reason"] for r in _fates(env["db"])] == ["derive_insufficient"]
        assert p.n_insufficient_data == 1

    def test_straight_fragment_drop(self, env, monkeypatch):
        """The rule has its own suite; this asserts only that its drop leaves
        a row — it was the least-instrumented exit in the function."""
        monkeypatch.setattr(ProcessingPipeline, "_straight_fragment_reroute",
                            lambda self, *a, **kw: "drop")
        p = _pipe(env)
        p.active_vehicles[8] = _vehicle()
        p._finalize_vehicle(8, frame_number=30)
        assert [r["reason"] for r in _fates(env["db"])] == ["straight_fragment_drop"]
        assert _events(env["db"]) == []


class TestLedgerIsDiagnosticsOnly:
    def test_off_writes_nothing(self, env, monkeypatch):
        import backend.services.pipeline as plmod
        monkeypatch.setattr(plmod, "TRACK_FATE_LEDGER", False)
        p = _pipe(env)
        p.active_vehicles[1] = _vehicle()
        p._finalize_vehicle(1, frame_number=30)
        assert _fates(env["db"]) == []
        assert len(_events(env["db"])) == 1

    def test_events_are_identical_with_the_ledger_on_and_off(self, env, monkeypatch):
        """The whole contract in one test: same track, two databases, the only
        difference being the flag. Every vehicle_events column must match."""
        import backend.services.pipeline as plmod
        other = os.path.join(env["dir"], "other.db")
        _make_db(other)

        monkeypatch.setattr(plmod, "TRACK_FATE_LEDGER", True)
        p_on = _pipe(env)
        p_on.active_vehicles[1] = _vehicle()
        p_on._finalize_vehicle(1, frame_number=30)

        monkeypatch.setattr(plmod, "TRACK_FATE_LEDGER", False)
        p_off = ProcessingPipeline(project_id="test", db_path=other,
                                   video_path="unused.mp4", legs=env["legs"],
                                   fps=10.0, paths=[P_THRU])
        p_off.active_vehicles[1] = _vehicle()
        p_off._finalize_vehicle(1, frame_number=30)

        on, off = _events(env["db"]), _events(other)
        assert len(on) == 1 and on == off
        assert p_on.n_insufficient_data == p_off.n_insufficient_data
        assert p_on.vehicle_count == p_off.vehicle_count
        assert len(_fates(env["db"])) == 1 and _fates(other) == []

    def test_table_is_created_on_a_db_that_predates_it(self, env):
        """Pass-2 replay copies project.db with shutil.copy2 and never runs the
        migration pass, so the write path has to be able to create the table."""
        legacy = os.path.join(env["dir"], "legacy.db")
        _make_db(legacy)
        conn = sqlite3.connect(legacy)
        conn.execute("DROP TABLE track_fates")
        conn.commit()
        conn.close()
        p = ProcessingPipeline(project_id="test", db_path=legacy,
                               video_path="unused.mp4", legs=env["legs"],
                               fps=10.0, paths=[P_THRU])
        p.active_vehicles[1] = _vehicle()
        p._finalize_vehicle(1, frame_number=30)
        assert [r["reason"] for r in _fates(legacy)] == ["counted"]
