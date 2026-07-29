"""Stage-2 auto-resolution + 5/95 bin re-key tests
(docs/plan_stage2_labor_levers_2026-07-29.md, steps 2.2 + 2.3).

Covers the pure rule core (decide), the rebuild-path adapter, the
in-place production sweep, the machine-state semantics (cleared on
rebuild, reopenable, never operator-worked), and the 2.3 scripted
dry-run of the operator flow over bin-keyed cards (GATE 2.3).
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import (
    flag_summary, get_connection, insert_flag, list_flags, update_flag_status,
)
from backend.services import queue_autoresolve as qa
from backend.services.flag_feeders import rebuild_flags

client = TestClient(app)

REC_START = "2026-04-30T06:00:00"      # camera clock: video sec 0 == 06:00
REC = 6 * 3600


def _mk_site(pid, *, trims=((7, 9),), det_conf=0.2, event_walls=()):
    """Intersection (+optional trims) + camera (+video with a recording
    start so wall-clock is derivable) + one leg + one low-det event per
    wall-clock second in event_walls (all flag as low_det_conf)."""
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES ('QA', '2026-04-30', 0, 4, '2026-04-30')").lastrowid
        for i, (lo, hi) in enumerate(trims or ()):
            conn.execute(
                "INSERT INTO trims (intersection_id, start_wallclock, "
                "end_wallclock, sort_order) VALUES (?, ?, ?, ?)",
                (iid, f"{lo:02d}:00:00", f"{hi:02d}:00:00", i))
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'cam', 0, '2026-04-30')", (iid,)).lastrowid
        conn.execute(
            "INSERT INTO videos (camera_id, sort_order, path, filename, fps, "
            "width, height, total_frames, duration_seconds, file_size_bytes, "
            "recording_start_datetime, added_at) VALUES (?, 0, 'x.mp4', "
            "'x.mp4', 10, 640, 480, 864000, 86400, 1, ?, '2026-04-30')",
            (cid, REC_START))
        lid = conn.execute(
            "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
            "origin_zone, reference_heading) VALUES (?, 'S leg', 'S', 0, "
            "'[[320,460]]', 0)", (cid,)).lastrowid
        eids = []
        for i, wall in enumerate(event_walls):
            eid = conn.execute(
                "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                "origin_leg_id, destination_leg_id, movement, trajectory_data, "
                "trajectory_confidence, vehicle_class, detection_confidence, "
                "timestamp_video, frame_number) VALUES (?, ?, ?, ?, 'through', "
                "'[[1,2],[3,4]]', 0.9, 'car', ?, ?, ?)",
                (cid, i, lid, lid, det_conf, wall - REC, int((wall - REC) * 10))
            ).lastrowid
            eids.append(eid)
    conn.close()
    return iid, cid, lid, eids


@pytest.fixture()
def project():
    pid = client.post("/api/projects", json={"name": "qa-test"}).json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


# --- the pure rule core -----------------------------------------------------

class TestDecide:
    WINDOWS = [(7 * 3600, 9 * 3600)]
    RECS = {1: REC}

    def _ev(self, wall, sev=0.0, appr="S", mv="through"):
        return {"subtype": "low_det_conf", "camera_id": 1, "has_event": True,
                "ev_ts": wall - REC, "approach": appr, "movement": mv,
                "impact": 1.0, "severity": sev}

    def test_r5_out_of_scope_resolves_inside_stays(self):
        recs = [self._ev(10 * 3600), self._ev(8 * 3600)]
        d = qa.decide(recs, self.WINDOWS, self.RECS)
        assert d[0]["status"] == qa.AUTO_STATUS and d[0]["rule"] == "R5_scope"
        assert d[1]["status"] == "open"

    def test_cap_keeps_most_severe_exemplar_with_cluster_impact(self):
        base = 7 * 3600 + 900                      # the 07:15 bin
        recs = [self._ev(base + 10, sev=0.1), self._ev(base + 20, sev=0.9),
                self._ev(base + 30, sev=0.5)]
        d = qa.decide(recs, self.WINDOWS, self.RECS)
        assert [x["status"] for x in d] == [qa.AUTO_STATUS, "open", qa.AUTO_STATUS]
        assert d[1]["impact"] == 3.0               # suspected max delta
        assert all(x["batch_key"] == "bin|1|S-through|07:15" for x in d)
        assert all(x["cluster_n"] == 3 for x in d)
        assert d[0]["rule"] == d[2]["rule"] == "R_cap"

    def test_different_bins_and_cells_not_clustered(self):
        recs = [self._ev(7 * 3600 + 10), self._ev(7 * 3600 + 1000),
                self._ev(7 * 3600 + 20, mv="left")]
        d = qa.decide(recs, self.WINDOWS, self.RECS)
        assert all(x["status"] == "open" for x in d)
        assert d[0]["batch_key"] == "bin|1|S-through|07:00"
        assert d[1]["batch_key"] == "bin|1|S-through|07:15"
        assert d[2]["batch_key"] == "bin|1|S-left|07:00"

    def test_r2_hole_threshold(self):
        holes = [{"subtype": "bank_coverage_hole", "camera_id": 1,
                  "has_event": False, "ev_ts": None, "approach": "E",
                  "movement": "through", "impact": imp, "severity": 0.0}
                 for imp in (5.0, 6.0)]
        d = qa.decide(holes, self.WINDOWS, self.RECS)
        assert d[0]["status"] == qa.AUTO_STATUS and d[0]["rule"] == "R2_hole"
        assert d[1]["status"] == "open"

    def test_unclockable_camera_left_untouched(self):
        d = qa.decide([self._ev(23 * 3600)], self.WINDOWS, {1: None})
        assert d[0]["status"] == "open" and d[0]["batch_key"] is None

    def test_broad_flag_left_untouched(self):
        rec = {"subtype": "merge_borderline", "camera_id": 1, "has_event": False,
               "ev_ts": None, "approach": "N", "movement": None,
               "impact": 87.0, "severity": 0.0}
        d = qa.decide([rec], self.WINDOWS, self.RECS)
        assert d[0]["status"] == "open" and d[0]["batch_key"] is None


# --- rebuild path (feeders -> rules -> insert) ------------------------------

class TestRebuildPath:
    def test_rebuild_applies_rules_and_bin_keys(self, project):
        # 3 events in the 07:15 bin (in-trim), 1 at 10:00 (out of trims)
        base = 7 * 3600 + 900
        iid, cid, lid, eids = _mk_site(
            project, trims=((7, 9),),
            event_walls=(base + 10, base + 20, base + 30, 10 * 3600))
        res = rebuild_flags(project, iid)
        assert res["created"] == 4
        assert res["auto_resolved_by_rule"] == {"R_cap": 2, "R5_scope": 1}
        assert res["open"] == 1 and res["auto_resolved"] == 3
        opens = list_flags(project, iid)
        assert len(opens) == 1
        assert opens[0]["batch_key"] == f"bin|{cid}|N-through|07:15"
        assert opens[0]["impact"] == 3.0
        assert opens[0]["evidence"]["bin_cluster_n"] == 3
        auto = list_flags(project, iid, status="auto_resolved")
        assert {a["evidence"]["auto_resolved"]["rule"] for a in auto} == \
            {"R_cap", "R5_scope"}
        assert all(a["resolved_at"] is not None for a in auto)

    def test_daylight_fallback_when_no_trims(self, project):
        iid, cid, lid, eids = _mk_site(
            project, trims=(), event_walls=(21 * 3600, 12 * 3600))
        res = rebuild_flags(project, iid)
        assert res["auto_resolved_by_rule"] == {"R5_scope": 1}   # 21:00 is night
        assert res["open"] == 1

    def test_rebuild_self_heals_machine_state(self, project):
        iid, cid, lid, eids = _mk_site(project, event_walls=(10 * 3600,))
        rebuild_flags(project, iid)
        assert flag_summary(project, iid)["auto_resolved"] == 1
        rebuild_flags(project, iid)                    # no duplicate history
        s = flag_summary(project, iid)
        assert s["auto_resolved"] == 1 and s["open"] == 0

    def test_reopen_hands_back_to_operator(self, project):
        iid, cid, lid, eids = _mk_site(project, event_walls=(10 * 3600,))
        rebuild_flags(project, iid)
        fid = list_flags(project, iid, status="auto_resolved")[0]["flag_id"]
        r = client.patch(f"/api/projects/{project}/flags/{fid}",
                         json={"status": "open"})
        assert r.status_code == 200
        f = list_flags(project, iid)[0]
        assert f["flag_id"] == fid and f["resolved_at"] is None


# --- the in-place production sweep ------------------------------------------

class TestSweep:
    def test_sweep_updates_in_place_and_is_idempotent(self, project):
        base = 7 * 3600 + 900
        iid, cid, lid, eids = _mk_site(
            project, trims=((7, 9),),
            event_walls=(base + 10, base + 20, 10 * 3600))
        # simulate a pre-existing queue (old-style keys), incl. an
        # S5-style broad flag that a rebuild would LOSE but sweep keeps
        for eid, sev in zip(eids, (0.9, 0.1, 0.5)):
            insert_flag(project, intersection_id=iid, kind="uncertain_event",
                        subtype="low_det_conf", camera_id=cid, event_id=eid,
                        approach="S", movement="through",
                        evidence={"severity": sev},
                        batch_key=f"lowdet|{cid}|S-through")
        insert_flag(project, intersection_id=iid, kind="suspected_gap",
                    subtype="merge_borderline", camera_id=cid, approach="N",
                    impact=87.0)
        res = qa.sweep(project, iid)
        assert res["open_before"] == 4 and res["open_after"] == 2
        assert res["by_rule"] == {"R_cap": 1, "R5_scope": 1}
        opens = list_flags(project, iid)
        by_sub = {f["subtype"]: f for f in opens}
        assert by_sub["merge_borderline"]["impact"] == 87.0     # untouched
        ex = by_sub["low_det_conf"]
        assert ex["batch_key"] == f"bin|{cid}|S-through|07:15"
        assert ex["impact"] == 2.0 and ex["evidence"]["severity"] == 0.9
        res2 = qa.sweep(project, iid)                           # idempotent
        assert res2["open_before"] == 2 and res2["open_after"] == 2
        assert res2["by_rule"] == {}

    def test_sweep_preserves_operator_statuses(self, project):
        iid, cid, lid, eids = _mk_site(project, event_walls=(10 * 3600,))
        fid = insert_flag(project, intersection_id=iid, kind="uncertain_event",
                          subtype="low_det_conf", camera_id=cid,
                          event_id=eids[0], approach="S", movement="through")
        update_flag_status(project, fid, "accepted")
        res = qa.sweep(project, iid)
        assert res["open_before"] == 0
        assert list_flags(project, iid, status="accepted")[0]["flag_id"] == fid


# --- 2.3 scripted dry-run: the operator flow over bin cards (GATE 2.3) ------

class TestBinCardFlow:
    def test_worklist_flow_end_to_end(self, project):
        base = 7 * 3600 + 900
        walls = (base + 10, base + 20, base + 30,          # 07:15 x3
                 7 * 3600 + 10,                            # 07:00 x1
                 8 * 3600 + 10, 8 * 3600 + 20)             # 08:00 x2
        iid, cid, lid, eids = _mk_site(project, trims=((7, 9),),
                                       event_walls=walls)
        rebuild_flags(project, iid)
        r = client.get(f"/api/projects/{project}/intersections/{iid}/flags")
        opens, summary = r.json()["flags"], r.json()["summary"]
        # one exemplar per bin = one card per suspect cell-bin
        assert summary["open"] == 3 and summary["open_cards"] == 3
        assert summary["auto_resolved"] == 3
        # impact ordering: the 3-event bin leads the worklist
        assert [f["impact"] for f in opens] == [3.0, 2.0, 1.0]
        assert opens[0]["batch_key"] == f"bin|{cid}|N-through|07:15"
        # /next serves the highest-impact bin card enriched
        nxt = client.get(
            f"/api/projects/{project}/intersections/{iid}/flags/next").json()
        assert nxt["flag"]["batch_key"] == f"bin|{cid}|N-through|07:15"
        # batch-resolve the bin card ("fix this bin" -> done)
        rb = client.post(
            f"/api/projects/{project}/intersections/{iid}/flags/batch",
            json={"batch_key": f"bin|{cid}|N-through|07:15",
                  "status": "resolved"})
        assert rb.status_code == 200 and rb.json()["affected"] == 1
        assert rb.json()["summary"]["open"] == 2
        # undo (the worklist's revert path): reopen via PATCH
        fid = rb.json()["changes"][0]["flag_id"]
        client.patch(f"/api/projects/{project}/flags/{fid}",
                     json={"status": "open"})
        assert flag_summary(project, iid)["open"] == 3

    def test_machine_closed_members_visible_under_same_card_key(self, project):
        base = 7 * 3600 + 900
        iid, cid, lid, eids = _mk_site(
            project, trims=((7, 9),),
            event_walls=(base + 10, base + 20, base + 30))
        rebuild_flags(project, iid)
        conn = get_connection(project)
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM review_flags WHERE batch_key = ? "
            "GROUP BY status", (f"bin|{cid}|N-through|07:15",)).fetchall()
        conn.close()
        assert dict(rows) == {"open": 1, "auto_resolved": 2}
