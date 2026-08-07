"""Phase-1 apply gate (plan_v2_apply_gate_2026-08-07): dispositions as
product state + per-window candidate-vs-incumbent adjudication under the
blind guards. No Miovision anywhere in here — the gate reads gate-evidence
censuses and counted tables only.
"""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import (
    get_connection,
    get_disposition,
    list_adjudications,
    record_adjudication,
    set_disposition,
)

client = TestClient(app)


@pytest.fixture()
def proj():
    pid = client.post("/api/projects",
                      json={"name": "apply-gate-test"}).json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _mk_cam(pid):
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, "
            "created_at) VALUES ('T', '2026-05-12', 0, 4, '2026-05-12')"
        ).lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, "
            "created_at) VALUES (?, 'c', 0, '2026-05-12')", (iid,)).lastrowid
    conn.close()
    return iid, cid


class TestDispositions:
    def test_default_is_auto_and_roundtrip(self, proj):
        _, cid = _mk_cam(proj)
        assert get_disposition(proj, cid, "study_0700") == "auto"
        set_disposition(proj, cid, "study_0700", "hold", note="cam4 lesson")
        assert get_disposition(proj, cid, "study_0700") == "hold"
        # window-scoped, not camera-scoped
        assert get_disposition(proj, cid, "study_1600") == "auto"
        set_disposition(proj, cid, "study_0700", "force_once")
        assert get_disposition(proj, cid, "study_0700") == "force_once"

    def test_auto_reset_deletes_the_row(self, proj):
        _, cid = _mk_cam(proj)
        set_disposition(proj, cid, "study_0700", "hold")
        set_disposition(proj, cid, "study_0700", "auto")
        conn = get_connection(proj)
        n = conn.execute("SELECT COUNT(*) FROM dispositions").fetchone()[0]
        conn.close()
        assert n == 0
        assert get_disposition(proj, cid, "study_0700") == "auto"

    def test_invalid_disposition_rejected_by_schema(self, proj):
        import sqlite3
        _, cid = _mk_cam(proj)
        with pytest.raises(sqlite3.IntegrityError):
            set_disposition(proj, cid, "study_0700", "maybe")

    def test_adjudication_audit_trail(self, proj):
        _, cid = _mk_cam(proj)
        record_adjudication(proj, cid, "study_0700", "stand_down",
                            ["event_flood"], {"flood_share_cand": 0.33})
        record_adjudication(proj, cid, "study_0700", "apply",
                            ["gate_pass"], {"flood_share_cand": 0.07})
        rows = list_adjudications(proj, camera_id=cid, variant="study_0700")
        assert [r["decision"] for r in rows] == ["apply", "stand_down"]
        assert rows[1]["reasons"] == ["event_flood"]
        assert rows[0]["metrics"]["flood_share_cand"] == 0.07
        assert list_adjudications(proj, camera_id=cid + 1) == []


CENSUS = {(1, 2): 100.0, (2, 1): 100.0}          # t = 200


def _spread(n12, n21):
    return {(1, 2): n12, (2, 1): n21}


class TestAdjudicateCounts:
    """The pure rule, every branch (plan constants: h=3%, F=15%, sat=0.25)."""

    def test_fresh_window_applies_ungated(self):
        from backend.services.apply_gate import adjudicate_counts
        d, r, m = adjudicate_counts({}, _spread(500, 500), CENSUS, 0.9)
        assert (d, r) == ("apply", ["fresh_window"])   # even saturated/flooded

    def test_no_census_abstains_to_legacy_apply(self):
        from backend.services.apply_gate import adjudicate_counts
        d, r, _ = adjudicate_counts(_spread(50, 50), _spread(60, 60), {}, 0.0)
        assert (d, r) == ("apply", ["not_adjudicable"])

    def test_gate_pass(self):
        from backend.services.apply_gate import adjudicate_counts
        # incumbent 15% under census; candidate recovers within the envelope
        d, r, m = adjudicate_counts(_spread(85, 85), _spread(95, 95),
                                    CENSUS, 0.1)
        assert (d, r) == ("apply", ["gate_pass"])
        assert m["R_inc"] == -0.15 and m["d_cov"] == 20

    def test_no_headroom_stands_down(self):
        from backend.services.apply_gate import adjudicate_counts
        # incumbent already at 99% of census: nothing missing to recover
        d, r, _ = adjudicate_counts(_spread(99, 99), _spread(100, 100),
                                    CENSUS, 0.1)
        assert d == "stand_down" and "no_headroom" in r

    def test_event_flood_stands_down(self):
        from backend.services.apply_gate import adjudicate_counts
        # candidate manufactures 35 beyond cell (1,2)'s census: 17.5% > 15%
        d, r, _ = adjudicate_counts(_spread(85, 85), _spread(135, 50),
                                    CENSUS, 0.1)
        assert d == "stand_down" and "event_flood" in r

    def test_flood_is_per_cell_not_net(self):
        from backend.services.apply_gate import adjudicate_counts
        # net total equals the incumbent's, but 40 sits beyond one cell's
        # evidence — starved cells must not cancel flooded ones
        d, r, _ = adjudicate_counts(_spread(85, 85), _spread(140, 30),
                                    CENSUS, 0.1)
        assert d == "stand_down" and "event_flood" in r

    def test_saturated_geometry_stands_down(self):
        from backend.services.apply_gate import adjudicate_counts
        # cam1's class: confusion ceiling — census not trustworthy there
        d, r, _ = adjudicate_counts(_spread(85, 85), _spread(95, 95),
                                    CENSUS, 0.73)
        assert d == "stand_down" and r == ["saturated_geometry"]

    def test_no_recovery_stands_down(self):
        from backend.services.apply_gate import adjudicate_counts
        # candidate adds ONLY excess (12.5% — inside the envelope): covered
        # mass unchanged, so no_recovery is the lone failing guard
        d, r, _ = adjudicate_counts(_spread(100, 60), _spread(125, 60),
                                    CENSUS, 0.1)
        assert d == "stand_down" and r == ["no_recovery"]

    def test_every_failed_guard_is_reported(self):
        from backend.services.apply_gate import adjudicate_counts
        # saturated + at census + flooding + losing covered mass: all four
        d, r, _ = adjudicate_counts(_spread(100, 100), _spread(150, 90),
                                    CENSUS, 0.5)
        assert d == "stand_down"
        assert set(r) == {"saturated_geometry", "no_headroom",
                          "event_flood", "no_recovery"}

    def test_directional_sanity_swap_stands_down(self):
        from backend.services.apply_gate import adjudicate_counts
        # a pair the gate applies must NOT walk back when sides swap:
        # the old starved table has no headroom claim against the new one
        inc, cand = _spread(85, 85), _spread(95, 95)
        assert adjudicate_counts(inc, cand, CENSUS, 0.1)[0] == "apply"
        assert adjudicate_counts(cand, inc, CENSUS, 0.1)[0] == "stand_down"

    def test_saturation_lower_median_convention(self):
        from backend.services.apply_gate import saturation_from_confusion
        # cam2's signature: one entangled origin vs clean others -> low
        assert saturation_from_confusion(
            {26: 0.05, 27: 0.08, 28: 0.98, 29: 0.11}) < 0.25
        # cam1's signature: the ceiling everywhere -> saturated
        assert saturation_from_confusion(
            {22: 0.73, 23: 0.78, 25: 1.0, 28: 0.05}) >= 0.25
        # unmeasurable contrast fails closed (shipped demotion convention)
        assert saturation_from_confusion({}) == 1.0
        assert saturation_from_confusion({26: 0.0}) == 1.0


def _mk_events_db(path, rows):
    """Minimal vehicle_events table: (camera_id, rejected, origin, dest, ts)."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE vehicle_events (event_id INTEGER PRIMARY KEY, "
                 "camera_id INT, rejected INT, origin_leg_id INT, "
                 "destination_leg_id INT, timestamp_video REAL)")
    conn.executemany("INSERT INTO vehicle_events (camera_id, rejected, "
                     "origin_leg_id, destination_leg_id, timestamp_video) "
                     "VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


class TestWindowCellCounts:
    def test_scoping(self, tmp_path):
        from backend.services.apply_gate import window_cell_counts
        db = tmp_path / "w.db"
        _mk_events_db(db, [
            (1, 0, 10, 11, 100.0),      # counted
            (1, 0, 10, 11, 150.0),      # counted
            (1, 1, 10, 11, 100.0),      # rejected -> out
            (1, 0, 10, None, 100.0),    # no destination -> out
            (2, 0, 10, 11, 100.0),      # other camera -> out
            (1, 0, 10, 11, 99.9),       # before window -> out
            (1, 0, 10, 11, 200.0),      # at t_hi (half-open) -> out
        ])
        assert window_cell_counts(db, 1, 100.0, 200.0) == {(10, 11): 2}


class TestAdjudicateApply:
    """The orchestrator: disposition ladder + audit trail + consumption."""

    def _dbs(self, tmp_path, cam):
        inc, cand = tmp_path / "inc.db", tmp_path / "cand.db"
        # incumbent 85+85 of a 100+100 census; candidate 95+95, no excess
        _mk_events_db(inc, [(cam, 0, 1, 2, 10.0)] * 85
                      + [(cam, 0, 2, 1, 10.0)] * 85)
        _mk_events_db(cand, [(cam, 0, 1, 2, 10.0)] * 95
                      + [(cam, 0, 2, 1, 10.0)] * 95)
        return inc, cand

    def test_hold_blocks_before_any_db_read(self, proj, tmp_path):
        from backend.services.apply_gate import adjudicate_apply
        _, cid = _mk_cam(proj)
        set_disposition(proj, cid, "study_0700", "hold", note="cam4 lesson")
        v = adjudicate_apply(proj, cid, "study_0700",
                             incumbent_db=tmp_path / "nonexistent-a.db",
                             candidate_db=tmp_path / "nonexistent-b.db",
                             t_lo=0.0, t_hi=100.0, census={}, confusion={})
        assert v["decision"] == "stand_down"
        assert v["reasons"] == ["operator_hold"]
        trail = list_adjudications(proj, camera_id=cid)
        assert trail[0]["decision"] == "stand_down"

    def test_force_once_applies_then_reverts_to_auto(self, proj, tmp_path):
        from backend.services.apply_gate import adjudicate_apply
        _, cid = _mk_cam(proj)
        inc, cand = self._dbs(tmp_path, cid)
        set_disposition(proj, cid, "study_0700", "force_once")
        v = adjudicate_apply(proj, cid, "study_0700", incumbent_db=inc,
                             candidate_db=cand, t_lo=0.0, t_hi=100.0,
                             census={}, confusion={})
        assert (v["decision"], v["reasons"]) == ("apply", ["operator_force"])
        assert get_disposition(proj, cid, "study_0700") == "auto"

    def test_auto_adjudicates_and_records(self, proj, tmp_path):
        from backend.services.apply_gate import adjudicate_apply
        _, cid = _mk_cam(proj)
        inc, cand = self._dbs(tmp_path, cid)
        census = {(1, 2): 100.0, (2, 1): 100.0}
        confusion = {1: 0.05, 2: 0.08}
        v = adjudicate_apply(proj, cid, "study_0700", incumbent_db=inc,
                             candidate_db=cand, t_lo=0.0, t_hi=100.0,
                             census=census, confusion=confusion)
        assert (v["decision"], v["reasons"]) == ("apply", ["gate_pass"])
        assert v["metrics"]["R_inc"] == -0.15
        trail = list_adjudications(proj, camera_id=cid)
        assert trail[0]["metrics"]["d_cov"] == 20

    def test_record_false_leaves_no_trail(self, proj, tmp_path):
        from backend.services.apply_gate import adjudicate_apply
        _, cid = _mk_cam(proj)
        inc, cand = self._dbs(tmp_path, cid)
        adjudicate_apply(proj, cid, "study_0700", incumbent_db=inc,
                         candidate_db=cand, t_lo=0.0, t_hi=100.0,
                         census={(1, 2): 100.0, (2, 1): 100.0},
                         confusion={1: 0.05, 2: 0.08}, record=False)
        assert list_adjudications(proj) == []
