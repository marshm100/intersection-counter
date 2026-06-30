"""Tests for the Phase B review flag queue (database helpers + flags router).

B1 ships the plumbing only — the feeders are stubbed (rebuild creates 0 flags),
so these tests exercise the helpers/endpoints by inserting flags directly, the
same way test_conservation_qa.py builds a synthetic project and inserts events.
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import (
    clear_open_flags, flag_summary, get_flag, insert_flag, list_flags,
    update_flag_status,
)
from backend.database import get_connection
from backend.services.flag_feeders import (
    DEST_MARGIN_FLOOR, DET_CONF_FLOOR, feed_suspected_gaps,
    feed_uncertain_events,
)
from backend.services.spot_check import acceptance

client = TestClient(app)


def _mk_site(pid, name="Int", sort_order=0):
    """One intersection, one camera, one leg, two events. Returns
    (intersection_id, camera_id, leg_id, [event_id, ...])."""
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES (?, '2026-06-29', ?, 4, '2026-06-29')", (name, sort_order)
        ).lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, ?, 0, '2026-06-29')", (iid, name)
        ).lastrowid
        lid = conn.execute(
            "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
            "origin_zone, reference_heading) VALUES (?, 'S leg', 'S', 0, '[[320,460]]', 0)",
            (cid,)
        ).lastrowid
        eids = []
        for i, conf in enumerate((0.3, 0.95)):
            eid = conn.execute(
                "INSERT INTO vehicle_events (camera_id, vehicle_track_id, origin_leg_id, "
                "destination_leg_id, movement, trajectory_data, trajectory_confidence, "
                "vehicle_class, detection_confidence, timestamp_video, frame_number) "
                "VALUES (?, ?, ?, ?, 'through', '[[1,2],[3,4]]', ?, 'car', 0.9, ?, ?)",
                (cid, i, lid, lid, conf, 100.0 + i, int((100.0 + i) * 10))
            ).lastrowid
            eids.append(eid)
    conn.close()
    return iid, cid, lid, eids


@pytest.fixture()
def site():
    pid = client.post("/api/projects", json={"name": "flags-test"}).json()["project_id"]
    iid, cid, lid, eids = _mk_site(pid)
    yield pid, iid, cid, lid, eids
    client.delete(f"/api/projects/{pid}")


# --- DB helpers -------------------------------------------------------------

class TestFlagHelpers:
    def test_list_orders_by_impact_desc(self, site):
        pid, iid, cid, lid, eids = site
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="coverage_sag", impact=5)
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="coverage_sag", impact=20)
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="coverage_sag", impact=1)
        flags = list_flags(pid, iid)
        assert [f["impact"] for f in flags] == [20, 5, 1]

    def test_status_and_kind_filters(self, site):
        pid, iid, cid, lid, eids = site
        insert_flag(pid, intersection_id=iid, kind="uncertain_event",
                    subtype="low_traj_conf", event_id=eids[0])
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="coverage_sag", status="accepted")
        assert len(list_flags(pid, iid)) == 1                       # default open only
        assert len(list_flags(pid, iid, status="all")) == 2
        assert len(list_flags(pid, iid, status="accepted")) == 1
        assert len(list_flags(pid, iid, kind="uncertain_event")) == 1

    def test_clear_open_keeps_worked_history(self, site):
        pid, iid, cid, lid, eids = site
        insert_flag(pid, intersection_id=iid, kind="suspected_gap", subtype="coverage_sag")
        insert_flag(pid, intersection_id=iid, kind="suspected_gap", subtype="coverage_sag")
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="coverage_sag", status="accepted")
        assert clear_open_flags(pid, iid) == 2
        remaining = list_flags(pid, iid, status="all")
        assert len(remaining) == 1 and remaining[0]["status"] == "accepted"

    def test_update_status_stamps_resolved_at(self, site):
        pid, iid, cid, lid, eids = site
        fid = insert_flag(pid, intersection_id=iid, kind="uncertain_event",
                          subtype="low_traj_conf", event_id=eids[0])
        assert get_flag(pid, fid)["resolved_at"] is None
        update_flag_status(pid, fid, "resolved")
        f = get_flag(pid, fid)
        assert f["status"] == "resolved" and f["resolved_at"] is not None
        update_flag_status(pid, fid, "open")          # reopen clears the stamp
        assert get_flag(pid, fid)["resolved_at"] is None

    def test_evidence_roundtrips_as_dict(self, site):
        pid, iid, cid, lid, eids = site
        fid = insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                          subtype="coverage_sag",
                          evidence={"baseline": 50, "observed": 30})
        assert get_flag(pid, fid)["evidence"] == {"baseline": 50, "observed": 30}

    def test_summary_counts_and_open_impact(self, site):
        pid, iid, cid, lid, eids = site
        insert_flag(pid, intersection_id=iid, kind="uncertain_event",
                    subtype="low_traj_conf", impact=5)
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="coverage_sag", impact=20)
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="coverage_sag", impact=99, status="accepted")
        s = flag_summary(pid, iid)
        assert s["open"] == 2 and s["accepted"] == 1
        assert s["open_impact"] == 25.0                 # accepted impact excluded
        assert s["by_kind"] == {"uncertain_event": 1, "suspected_gap": 1}


# --- API --------------------------------------------------------------------

class TestFlagsApi:
    def test_rebuild_creates_zero_with_stub_feeders(self, site):
        pid, iid, cid, lid, eids = site
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/flags/rebuild")
        assert r.status_code == 200
        assert r.json()["created"] == 0 and r.json()["open"] == 0

    def test_rebuild_clears_prior_open_flags(self, site):
        pid, iid, cid, lid, eids = site
        insert_flag(pid, intersection_id=iid, kind="suspected_gap", subtype="coverage_sag")
        client.post(f"/api/projects/{pid}/intersections/{iid}/flags/rebuild")
        assert client.get(
            f"/api/projects/{pid}/intersections/{iid}/flags").json()["flags"] == []

    def test_list_returns_flags_and_summary(self, site):
        pid, iid, cid, lid, eids = site
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="coverage_sag", impact=7)
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/flags")
        body = r.json()
        assert len(body["flags"]) == 1 and body["summary"]["open_impact"] == 7.0

    def test_next_enriches_event_anchored_flag(self, site):
        pid, iid, cid, lid, eids = site
        insert_flag(pid, intersection_id=iid, kind="uncertain_event",
                    subtype="low_traj_conf", camera_id=cid, event_id=eids[0],
                    impact=1, reason="trajectory confidence 0.30 below 0.50")
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/flags/next")
        flag = r.json()["flag"]
        assert flag["event"]["leg_label"] == "S leg"
        assert flag["event"]["trajectory_data"] == "[[1,2],[3,4]]"
        assert flag["clip"]["center_seconds"] == 100.0
        assert flag["clip"]["start_seconds"] == 98.0
        assert flag["clip"]["end_seconds"] == 102.0

    def test_next_gap_flag_has_no_event(self, site):
        pid, iid, cid, lid, eids = site
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="coverage_sag", approach="NB", movement="through",
                    interval_start_seconds=3600, interval_end_seconds=4500, impact=40)
        flag = client.get(
            f"/api/projects/{pid}/intersections/{iid}/flags/next").json()["flag"]
        assert flag["event"] is None and flag["clip"] is None
        assert flag["approach"] == "NB" and flag["interval_start_seconds"] == 3600

    def test_next_empty_queue(self, site):
        pid, iid, cid, lid, eids = site
        body = client.get(
            f"/api/projects/{pid}/intersections/{iid}/flags/next").json()
        assert body["flag"] is None

    def test_patch_status_flips_and_updates_summary(self, site):
        pid, iid, cid, lid, eids = site
        fid = insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                          subtype="coverage_sag", impact=10)
        r = client.patch(f"/api/projects/{pid}/flags/{fid}", json={"status": "resolved"})
        assert r.status_code == 200 and r.json()["status"] == "resolved"
        assert flag_summary(pid, iid)["open"] == 0

    def test_patch_bad_status_422(self, site):
        pid, iid, cid, lid, eids = site
        fid = insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                          subtype="coverage_sag")
        assert client.patch(
            f"/api/projects/{pid}/flags/{fid}", json={"status": "bogus"}).status_code == 422

    def test_patch_missing_flag_404(self, site):
        pid, iid, cid, lid, eids = site
        assert client.patch(
            f"/api/projects/{pid}/flags/999999", json={"status": "resolved"}).status_code == 404

    def test_unknown_intersection_404(self, site):
        pid, iid, cid, lid, eids = site
        assert client.get(
            f"/api/projects/{pid}/intersections/999999/flags").status_code == 404

    def test_unknown_project_404(self, site):
        assert client.get(
            "/api/projects/nope/intersections/1/flags").status_code == 404

    def test_get_one_flag_enriches_event(self, site):
        pid, iid, cid, lid, eids = site
        fid = insert_flag(pid, intersection_id=iid, kind="uncertain_event",
                          subtype="low_traj_conf", camera_id=cid, event_id=eids[0])
        f = client.get(f"/api/projects/{pid}/flags/{fid}").json()
        assert f["event"]["leg_label"] == "S leg"
        assert f["clip"]["center_seconds"] == 100.0

    def test_get_one_flag_404(self, site):
        pid = site[0]
        assert client.get(f"/api/projects/{pid}/flags/999999").status_code == 404


# --- Feeder 1: uncertain events ---------------------------------------------

def _mk_multileg_site(pid, name="U"):
    """Intersection + camera + 4 cardinal legs (no events). Returns
    (intersection_id, camera_id, {cardinal: leg_id})."""
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES (?, '2026-06-29', 0, 4, '2026-06-29')", (name,)).lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, ?, 0, '2026-06-29')", (iid, name)).lastrowid
        legs = {}
        for card in ("N", "S", "E", "W"):
            legs[card] = conn.execute(
                "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
                "origin_zone, reference_heading) VALUES (?, ?, ?, 0, '[[0,0]]', 0)",
                (cid, f"{card} leg", card)).lastrowid
    conn.close()
    return iid, cid, legs


def _add_ev(pid, cid, lid, *, det=0.9, traj=0.9, dest_conf=0.9, posterior=None,
            vclass="car", movement="through", ts=10.0, rejected=0, edited=0):
    conn = get_connection(pid)
    with conn:
        eid = conn.execute(
            "INSERT INTO vehicle_events (camera_id, vehicle_track_id, origin_leg_id, "
            "destination_leg_id, movement, trajectory_data, trajectory_confidence, "
            "vehicle_class, detection_confidence, destination_confidence, "
            "destination_posterior_json, timestamp_video, frame_number, rejected, "
            "manually_edited) VALUES (?, 0, ?, ?, ?, '[[1,2]]', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, lid, lid, movement, traj, vclass, det, dest_conf,
             json.dumps(posterior) if posterior else None, ts, int(ts * 10),
             rejected, edited)).lastrowid
    conn.close()
    return eid


@pytest.fixture()
def usite():
    pid = client.post("/api/projects", json={"name": "uncertain-test"}).json()["project_id"]
    iid, cid, legs = _mk_multileg_site(pid)
    yield pid, iid, cid, legs
    client.delete(f"/api/projects/{pid}")


class TestUncertainFeeder:
    def test_clean_event_not_flagged(self, usite):
        pid, iid, cid, legs = usite
        _add_ev(pid, cid, legs["S"])                       # all high, no posterior
        assert feed_uncertain_events(pid, iid) == []

    def test_low_traj_alone_does_not_flag(self, usite):
        # The key data-driven decision: trajectory_confidence is corroborating
        # only — a low value alone (it's poorly calibrated) must NOT create work.
        pid, iid, cid, legs = usite
        _add_ev(pid, cid, legs["S"], traj=0.1)
        assert feed_uncertain_events(pid, iid) == []

    def test_low_detection_flags_phantom(self, usite):
        pid, iid, cid, legs = usite
        _add_ev(pid, cid, legs["S"], det=0.30)
        flags = feed_uncertain_events(pid, iid)
        assert len(flags) == 1
        f = flags[0]
        assert f["subtype"] == "low_det_conf" and f["kind"] == "uncertain_event"
        assert f["approach"] == "N"          # origin cardinal S -> NB approach
        assert f["impact"] == 1.0 and f["batch_key"] is None
        assert f["evidence"]["signals"] == ["low_det_conf"]
        assert "phantom" in f["reason"]

    def test_ambiguous_destination_flags_with_batch_key(self, usite):
        pid, iid, cid, legs = usite
        _add_ev(pid, cid, legs["S"],
                posterior={str(legs["N"]): 0.46, str(legs["E"]): 0.41})
        flags = feed_uncertain_events(pid, iid)
        assert len(flags) == 1
        f = flags[0]
        assert f["subtype"] == "ambiguous_dest"
        assert f["batch_key"] == "dest|N|E-N"     # approach N, contested exits E & N
        assert {t["cardinal"] for t in f["evidence"]["top2"]} == {"N", "E"}
        assert f["evidence"]["destination_margin"] < DEST_MARGIN_FLOOR

    def test_traj_corroborates_detection_flag(self, usite):
        pid, iid, cid, legs = usite
        _add_ev(pid, cid, legs["S"], det=0.30, traj=0.4)
        f = feed_uncertain_events(pid, iid)[0]
        assert f["evidence"]["traj_corroborates"] is True
        assert "weak track" in f["reason"]

    def test_combined_signals_one_flag_existence_first(self, usite):
        pid, iid, cid, legs = usite
        _add_ev(pid, cid, legs["S"], det=0.30,
                posterior={str(legs["N"]): 0.46, str(legs["E"]): 0.41})
        flags = feed_uncertain_events(pid, iid)
        assert len(flags) == 1                       # one flag per event
        f = flags[0]
        assert f["subtype"] == "low_det_conf"        # existence-first primary
        assert set(f["evidence"]["signals"]) == {"low_det_conf", "ambiguous_dest"}

    def test_rejected_and_edited_skipped(self, usite):
        pid, iid, cid, legs = usite
        _add_ev(pid, cid, legs["S"], det=0.30, rejected=1)
        _add_ev(pid, cid, legs["S"], det=0.30, edited=1)
        assert feed_uncertain_events(pid, iid) == []

    def test_worked_event_skipped(self, usite):
        pid, iid, cid, legs = usite
        eid = _add_ev(pid, cid, legs["S"], det=0.30)
        insert_flag(pid, intersection_id=iid, kind="uncertain_event",
                    subtype="low_det_conf", event_id=eid, status="accepted")
        assert feed_uncertain_events(pid, iid) == []     # already worked -> not re-flagged

    def test_same_batch_key_groups_dest_ties(self, usite):
        pid, iid, cid, legs = usite
        for ts in (10.0, 20.0):
            _add_ev(pid, cid, legs["S"], ts=ts,
                    posterior={str(legs["N"]): 0.45, str(legs["E"]): 0.42})
        flags = feed_uncertain_events(pid, iid)
        assert len(flags) == 2
        assert flags[0]["batch_key"] == flags[1]["batch_key"] == "dest|N|E-N"

    def test_rebuild_creates_uncertain_flags(self, usite):
        pid, iid, cid, legs = usite
        _add_ev(pid, cid, legs["S"], det=0.30)
        _add_ev(pid, cid, legs["W"],
                posterior={str(legs["N"]): 0.46, str(legs["S"]): 0.43})
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/flags/rebuild")
        body = r.json()
        assert body["created"] == 2
        assert body["by_kind"].get("uncertain_event") == 2


# --- Feeder 2: suspected gaps (coverage QA) ---------------------------------

def _mk_corridor_site(pid, name, sort_order, rec="2026-04-30T16:00:00"):
    """Intersection + camera + video (with recording_start) + 4 cardinal legs."""
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES (?, '2026-04-30', ?, 4, 'x')", (name, sort_order)).lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, ?, 0, 'x')", (iid, name)).lastrowid
        vid = conn.execute(
            "INSERT INTO videos (camera_id, sort_order, path, filename, fps, width, "
            "height, total_frames, duration_seconds, file_size_bytes, "
            "recording_start_datetime, added_at) "
            "VALUES (?, 0, ?, ?, 30, 640, 360, 100000, 3600, 1000, ?, 'x')",
            (cid, f"/v/{name}.mp4", f"{name}.mp4", rec)).lastrowid
        legs = {}
        for card in ("N", "S", "E", "W"):
            legs[card] = conn.execute(
                "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
                "origin_zone, reference_heading) VALUES (?, ?, ?, 0, '[[0,0]]', 0)",
                (cid, f"{card} leg", card)).lastrowid
    conn.close()
    return iid, cid, vid, legs


def _bulk_events(pid, specs):
    """specs: list of (cid, vid, origin_leg, dest_leg, tsv)."""
    conn = get_connection(pid)
    with conn:
        conn.executemany(
            "INSERT INTO vehicle_events (camera_id, video_id, vehicle_track_id, "
            "origin_leg_id, destination_leg_id, movement, trajectory_data, "
            "trajectory_confidence, vehicle_class, detection_confidence, "
            "timestamp_video, frame_number) "
            "VALUES (?, ?, 0, ?, ?, 'through', '[]', 0.9, 'car', 0.9, ?, ?)",
            [(c, v, o, d, t, int(t * 10)) for (c, v, o, d, t) in specs])
    conn.close()


class TestSuspectedGapsFeeder:
    def test_s1_corridor_gap_flags_undercounter(self):
        pid = client.post("/api/projects", json={"name": "cg"}).json()["project_id"]
        try:
            s_iid, s_cid, s_vid, s_legs = _mk_corridor_site(pid, "South", 0)
            n_iid, n_cid, n_vid, n_legs = _mk_corridor_site(pid, "North", 1)
            # 60 NB through sent at South (origin S -> dest N), only 30 arrive North.
            _bulk_events(pid, [(s_cid, s_vid, s_legs["S"], s_legs["N"], i * 10) for i in range(60)])
            _bulk_events(pid, [(n_cid, n_vid, n_legs["S"], n_legs["N"], i * 10) for i in range(30)])
            flags = feed_suspected_gaps(pid, n_iid)
            s1 = [f for f in flags if f["subtype"] == "interval_corridor"]
            assert len(s1) == 1
            assert s1[0]["impact"] == 30.0           # 60 sent - 30 received
            assert s1[0]["approach"] == "N"          # NB approach (origin south arm)
            assert s1[0]["camera_id"] == n_cid
            # South (the sending, well-counted end) gets no flag for this link.
            assert [f for f in feed_suspected_gaps(pid, s_iid)
                    if f["subtype"] == "interval_corridor"] == []
        finally:
            client.delete(f"/api/projects/{pid}")

    def test_s1_conserving_corridor_no_flag(self):
        pid = client.post("/api/projects", json={"name": "cc"}).json()["project_id"]
        try:
            s_iid, s_cid, s_vid, s_legs = _mk_corridor_site(pid, "South", 0)
            n_iid, n_cid, n_vid, n_legs = _mk_corridor_site(pid, "North", 1)
            _bulk_events(pid, [(s_cid, s_vid, s_legs["S"], s_legs["N"], i * 10) for i in range(60)])
            _bulk_events(pid, [(n_cid, n_vid, n_legs["S"], n_legs["N"], i * 10) for i in range(58)])
            assert [f for f in feed_suspected_gaps(pid, n_iid)
                    if f["subtype"] == "interval_corridor"] == []
        finally:
            client.delete(f"/api/projects/{pid}")

    def test_s2_abrupt_asymmetric_drop_flags(self):
        pid = client.post("/api/projects", json={"name": "s2"}).json()["project_id"]
        try:
            iid, cid, vid, legs = _mk_corridor_site(pid, "S2", 0)
            specs = []
            plan = {0: 30, 1: 30, 2: 3, 3: 30, 4: 30}     # NB dips hard in bin 2
            for b, n in plan.items():
                specs += [(cid, vid, legs["S"], legs["N"], b * 900 + i) for i in range(n)]
                specs += [(cid, vid, legs["N"], legs["S"], b * 900 + i) for i in range(30)]  # SB steady
            _bulk_events(pid, specs)
            s2 = [f for f in feed_suspected_gaps(pid, iid) if f["subtype"] == "interval_anomaly"]
            assert len(s2) == 1
            assert s2[0]["approach"] == "N"                       # NB approach (origin S)
            assert s2[0]["interval_start_seconds"] == 1800.0      # bin 2
            assert s2[0]["impact"] == 27.0                        # ~30 baseline - 3 observed
        finally:
            client.delete(f"/api/projects/{pid}")

    def test_s2_smooth_decline_no_flag(self):
        pid = client.post("/api/projects", json={"name": "sm"}).json()["project_id"]
        try:
            iid, cid, vid, legs = _mk_corridor_site(pid, "SM", 0)
            specs = []
            for b, n in {0: 40, 1: 35, 2: 30, 3: 25, 4: 20}.items():    # smooth ramp-down
                specs += [(cid, vid, legs["S"], legs["N"], b * 900 + i) for i in range(n)]
                specs += [(cid, vid, legs["N"], legs["S"], b * 900 + i) for i in range(30)]
            _bulk_events(pid, specs)
            assert [f for f in feed_suspected_gaps(pid, iid)
                    if f["subtype"] == "interval_anomaly"] == []
        finally:
            client.delete(f"/api/projects/{pid}")

    def test_s2_symmetric_low_bin_no_flag(self):
        # Both directions drop together = a real lull, not a coverage gap.
        pid = client.post("/api/projects", json={"name": "sl"}).json()["project_id"]
        try:
            iid, cid, vid, legs = _mk_corridor_site(pid, "SL", 0)
            specs = []
            for b, n in {0: 30, 1: 30, 2: 3, 3: 30, 4: 30}.items():
                specs += [(cid, vid, legs["S"], legs["N"], b * 900 + i) for i in range(n)]
                specs += [(cid, vid, legs["N"], legs["S"], b * 900 + i) for i in range(n)]  # SB drops too
            _bulk_events(pid, specs)
            assert [f for f in feed_suspected_gaps(pid, iid)
                    if f["subtype"] == "interval_anomaly"] == []
        finally:
            client.delete(f"/api/projects/{pid}")

    def test_uniform_offset_no_fabricated_catch(self):
        # The FM51 case: an approach uniformly lower than truth, but no dips and
        # the partner is similar. Internal consistency CANNOT see it — assert we
        # don't fabricate a flag we have no basis for.
        pid = client.post("/api/projects", json={"name": "uo"}).json()["project_id"]
        try:
            iid, cid, vid, legs = _mk_corridor_site(pid, "UO", 0)
            specs = []
            for b in range(5):
                specs += [(cid, vid, legs["S"], legs["N"], b * 900 + i) for i in range(80)]   # NB steady-low
                specs += [(cid, vid, legs["N"], legs["S"], b * 900 + i) for i in range(100)]  # SB steady-high
            _bulk_events(pid, specs)
            assert feed_suspected_gaps(pid, iid) == []
        finally:
            client.delete(f"/api/projects/{pid}")

    def test_get_one_flag_enriches_gap_clip(self):
        pid = client.post("/api/projects", json={"name": "ge"}).json()["project_id"]
        try:
            iid, cid, vid, legs = _mk_corridor_site(pid, "G", 0)
            fid = insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                              subtype="interval_corridor", camera_id=cid,
                              interval_start_seconds=300, interval_end_seconds=1200,
                              approach="N", impact=40)
            f = client.get(f"/api/projects/{pid}/flags/{fid}").json()
            assert f["clip"]["video_id"] == vid
            assert f["clip"]["center_seconds"] == 300
            assert f["event"] is None
        finally:
            client.delete(f"/api/projects/{pid}")


# --- B4: acceptance gate folds the queue ------------------------------------

def _n_events(pid, cid, origin_lid, dest_lid, n, *, t0=0.0):
    """Bulk-insert n minimal active events (high confidence so they don't trip
    the uncertain feeder)."""
    conn = get_connection(pid)
    with conn:
        conn.executemany(
            "INSERT INTO vehicle_events (camera_id, vehicle_track_id, origin_leg_id, "
            "destination_leg_id, movement, trajectory_data, trajectory_confidence, "
            "vehicle_class, detection_confidence, timestamp_video, frame_number) "
            "VALUES (?, 0, ?, ?, 'through', '[]', 0.9, 'car', 0.9, ?, ?)",
            [(cid, origin_lid, dest_lid, t0 + i, int(t0 + i)) for i in range(n)])
    conn.close()


def _gate_item(pid, iid):
    return {i["item"]: i for i in acceptance(pid, iid)["items"]}["review_flags"]


class TestAcceptanceGate:
    def test_no_flags_is_info(self, usite):
        pid, iid, cid, legs = usite
        _n_events(pid, cid, legs["S"], legs["N"], 100)
        assert _gate_item(pid, iid)["verdict"] == "info"

    def test_material_gap_triggers_review(self, usite):
        pid, iid, cid, legs = usite
        _n_events(pid, cid, legs["S"], legs["N"], 100)
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="interval_corridor", impact=6)   # 6% of 100
        item = _gate_item(pid, iid)
        assert item["verdict"] == "review"
        assert item["detail"]["estimated_missed_pct"] == 6.0

    def test_small_gap_is_ok(self, usite):
        pid, iid, cid, legs = usite
        _n_events(pid, cid, legs["S"], legs["N"], 100)
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="interval_corridor", impact=3)   # 3% of 100
        item = _gate_item(pid, iid)
        assert item["verdict"] == "ok"
        assert item["detail"]["estimated_missed_pct"] == 3.0

    def test_uncertain_flags_are_backlog_not_error(self, usite):
        # THE reconciliation: 50 uncertain flags (impact 50) must NOT drive the
        # gate to review — only gap impact counts as estimated error.
        pid, iid, cid, legs = usite
        _n_events(pid, cid, legs["S"], legs["N"], 100)
        for _ in range(50):
            insert_flag(pid, intersection_id=iid, kind="uncertain_event",
                        subtype="low_det_conf", impact=1)
        item = _gate_item(pid, iid)
        assert item["verdict"] == "ok"
        assert item["detail"]["uncertain_to_confirm"] == 50
        assert item["detail"]["estimated_missed"] == 0.0

    def test_resolving_gaps_clears_gate_item(self, usite):
        pid, iid, cid, legs = usite
        _n_events(pid, cid, legs["S"], legs["N"], 100)
        fid = insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                          subtype="interval_corridor", impact=6)
        assert _gate_item(pid, iid)["verdict"] == "review"
        update_flag_status(pid, fid, "resolved")
        assert _gate_item(pid, iid)["verdict"] == "ok"   # gap gone; not info (a row exists)

    def test_flags_do_not_mask_a_spot_fail(self, usite):
        # review_flags can only be info/ok/review, so it can never remove a hard
        # fail from elsewhere (overall = fail > review > ship).
        pid, iid, cid, legs = usite
        _n_events(pid, cid, legs["S"], legs["N"], 200)        # 200 NB-through
        client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                    json={"start_seconds": 0, "duration_seconds": 300,
                          "manual_counts": {"N through": 20}})   # wildly low -> fail
        assert acceptance(pid, iid)["overall"] == "fail"
