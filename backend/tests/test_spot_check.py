"""Tests for backend/services/spot_check.py + the Phase-4 QA endpoints.

Reuses the conservation-QA synthetic fixture style: one project, one
intersection, cardinal legs, events inserted directly.
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection
from backend.services.spot_check import katz_ci

client = TestClient(app)


# ---- statistics ------------------------------------------------------------

class TestKatzCi:
    def test_exact_match_centers_on_zero(self):
        point, lo, hi = katz_ci(400, 400)
        assert point == 0.0
        assert lo < 0 < hi
        assert hi - lo < 0.30          # ~+/-14% at n=400

    def test_ci_tightens_with_volume(self):
        _, lo1, hi1 = katz_ci(50, 50)
        _, lo2, hi2 = katz_ci(2000, 2000)
        assert (hi2 - lo2) < (hi1 - lo1)

    def test_overcount_detected(self):
        point, lo, hi = katz_ci(600, 400)
        assert point == pytest.approx(0.5)
        assert lo > 0.30                # CI excludes "accurate"

    def test_zero_counts_stay_finite(self):
        point, lo, hi = katz_ci(0, 10)
        assert point == -1.0
        assert lo > -1.01 and hi < 0.5


# ---- fixture ----------------------------------------------------------------

def _mk(pid):
    conn = get_connection(pid)
    with conn:
        cur = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES ('Spot Int', '2026-06-12', 0, 4, '2026-06-12')")
        iid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'cam', 0, '2026-06-12')", (iid,))
        cid = cur.lastrowid
        legs = {}
        for card, (x, y) in {"N": (320, 460), "S": (320, 20),
                             "E": (20, 240), "W": (620, 240)}.items():
            cur = conn.execute(
                "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
                "origin_zone, reference_heading) VALUES (?, ?, ?, 0, ?, 0)",
                (cid, card, card, json.dumps([[x, y]])))
            legs[card] = cur.lastrowid
        i = 0
        # 1200 total — above NEEDED_TOTAL_FOR_CI (~850) so an accurate count
        # can actually certify the +/-10% CI and PASS.
        for (a, b), n in {("N", "S"): 600, ("S", "N"): 560, ("N", "E"): 40}.items():
            for _ in range(n):
                ts = 600.0 + 600.0 * i / 1200    # all inside [600, 1200)
                conn.execute(
                    "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                    "origin_leg_id, destination_leg_id, movement, trajectory_data, "
                    "trajectory_confidence, vehicle_class, detection_confidence, "
                    "timestamp_video, frame_number) "
                    "VALUES (?, ?, ?, ?, 'through', '[]', 1.0, 'car', 0.9, ?, ?)",
                    (cid, i, legs[a], legs[b], ts, int(ts * 10)))
                i += 1
    conn.close()
    return iid, cid


@pytest.fixture()
def spot_project():
    r = client.post("/api/projects", json={"name": "spot-test"})
    pid = r.json()["project_id"]
    iid, cid = _mk(pid)
    yield pid, iid, cid
    client.delete(f"/api/projects/{pid}")


def _mk_two_block(pid):
    """Two processed blocks (AM + PM trims) separated by a >20-min hole, so the
    run has TWO coverage segments. 900 veh/block so a full-block count certifies
    the +/-10% CI and can PASS."""
    conn = get_connection(pid)
    with conn:
        cur = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES ('TwoBlk', '2026-06-12', 0, 4, '2026-06-12')")
        iid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'cam', 0, '2026-06-12')", (iid,))
        cid = cur.lastrowid
        legs = {}
        for card, (x, y) in {"N": (320, 460), "S": (320, 20),
                             "E": (20, 240), "W": (620, 240)}.items():
            cur = conn.execute(
                "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
                "origin_zone, reference_heading) VALUES (?, ?, ?, 0, ?, 0)",
                (cid, card, card, json.dumps([[x, y]])))
            legs[card] = cur.lastrowid
        i = 0
        for base in (600.0, 30000.0):     # AM block, then PM block (28500s gap)
            for (a, b), n in {("N", "S"): 500, ("S", "N"): 400}.items():
                for k in range(n):
                    ts = base + 900.0 * (k / n)   # spread across the block's 900s
                    conn.execute(
                        "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                        "origin_leg_id, destination_leg_id, movement, trajectory_data, "
                        "trajectory_confidence, vehicle_class, detection_confidence, "
                        "timestamp_video, frame_number) "
                        "VALUES (?, ?, ?, ?, 'through', '[]', 1.0, 'car', 0.9, ?, ?)",
                        (cid, i, legs[a], legs[b], ts, int(ts * 10)))
                    i += 1
    conn.close()
    return iid, cid


@pytest.fixture()
def spot_two_block():
    r = client.post("/api/projects", json={"name": "spot-2blk"})
    pid = r.json()["project_id"]
    iid, cid = _mk_two_block(pid)
    yield pid, iid, cid
    client.delete(f"/api/projects/{pid}")


# ---- endpoints ---------------------------------------------------------------

class TestSpotWorkflow:
    def test_propose_window_inside_processed_range(self, spot_project):
        pid, _, cid = spot_project
        r = client.get(f"/api/projects/{pid}/cameras/{cid}/qa/spot-window?minutes=5")
        assert r.status_code == 200
        w = r.json()
        assert w["processed_range"][0] >= 599.0
        assert w["start_seconds"] >= w["processed_range"][0]

    def test_accurate_spot_count_passes(self, spot_project):
        pid, _, cid = spot_project
        # Window covers all events; manual matches system exactly.
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                        json={"start_seconds": 600, "duration_seconds": 600,
                              "manual_counts": {"N through": 600, "S through": 560,
                                                "N left": 40}})
        assert r.status_code == 200
        rep = r.json()
        assert rep["total"]["manual"] == 1200 and rep["total"]["system"] == 1200
        assert rep["verdict"] == "pass"

    def test_small_accurate_count_reviews_with_guidance(self, spot_project):
        pid, _, cid = spot_project
        # Accurate but only ~240 vehicles: CI too wide to certify -> review,
        # and the note tells the operator how much more to count.
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                        json={"start_seconds": 600, "duration_seconds": 120,
                              "manual_counts": {"N through": 120, "S through": 112,
                                                "N left": 8}})
        rep = r.json()
        assert rep["verdict"] == "review"
        assert "extend the count" in rep["note"]

    def test_bad_count_fails(self, spot_project):
        pid, _, cid = spot_project
        # Manual says far more vehicles existed than the system counted.
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                        json={"start_seconds": 600, "duration_seconds": 600,
                              "manual_counts": {"N through": 950, "S through": 900}})
        rep = r.json()
        assert rep["verdict"] == "fail"
        assert rep["total"]["rel_err"] < -0.2

    def test_tiny_window_reviews_not_passes(self, spot_project):
        pid, _, cid = spot_project
        # 30s window holds ~60 events (fixture inserts N-thru first, spread
        # over [600, 900)). Manual agrees exactly — but 60 vehicles can never
        # certify +/-10%, so the verdict must be review, not pass.
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                        json={"start_seconds": 600, "duration_seconds": 30,
                              "manual_counts": {"N through": 60}})
        rep = r.json()
        assert rep["verdict"] == "review"
        assert rep["total"]["ci95"][1] > 0.10 or rep["total"]["ci95"][0] < -0.10

    def test_acceptance_gate_aggregates(self, spot_project):
        pid, iid, cid = spot_project
        # No spot count yet -> review.
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/qa/acceptance")
        assert r.status_code == 200
        gate = r.json()
        assert gate["overall"] in ("review", "fail")
        items = {i["item"]: i["verdict"] for i in gate["items"]}
        assert items["spot_count"] == "review"
        # Record an accurate spot count -> spot item passes.
        client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                    json={"start_seconds": 600, "duration_seconds": 600,
                          "manual_counts": {"N through": 600, "S through": 560,
                                            "N left": 40}})
        gate2 = client.get(f"/api/projects/{pid}/intersections/{iid}/qa/acceptance").json()
        items2 = {i["item"]: i["verdict"] for i in gate2["items"]}
        assert items2["spot_count"] == "pass"

    def test_negative_counts_rejected(self, spot_project):
        pid, _, cid = spot_project
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                        json={"start_seconds": 600, "duration_seconds": 600,
                              "manual_counts": {"N through": -5}})
        assert r.status_code == 422


# ---- stratified spot windows + segment-coverage gate (MASTER_PLAN §5) --------

class TestStratifiedSpot:
    def test_propose_windows_stratifies_across_blocks(self, spot_two_block):
        pid, _, cid = spot_two_block
        r = client.get(f"/api/projects/{pid}/cameras/{cid}/qa/spot-windows?minutes=5")
        assert r.status_code == 200
        w = r.json()
        assert w["n_segments"] == 2 and len(w["windows"]) == 2
        segs = w["processed_segments"]
        for win in w["windows"]:                 # each window sits in its segment
            seg = segs[win["segment_index"]]
            assert seg[0] <= win["start_seconds"] < seg[1]
        starts = sorted(win["start_seconds"] for win in w["windows"])
        assert starts[1] - starts[0] > 20000     # AM and PM, genuinely apart

    def test_gate_reviews_until_every_segment_covered(self, spot_two_block):
        pid, iid, cid = spot_two_block
        # Spot-count the AM block only.
        client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                    json={"start_seconds": 600, "duration_seconds": 900,
                          "manual_counts": {"S through": 500, "N through": 400}})
        gate = client.get(f"/api/projects/{pid}/intersections/{iid}/qa/acceptance").json()
        spot = next(i for i in gate["items"] if i["item"] == "spot_count")
        assert spot["verdict"] == "review"       # PM block still unsampled
        d = spot["detail"][0]
        assert d["segments"] == 2 and d["covered"] == 1
        assert "also sample" in d["note"]
        # Now cover the PM block too.
        client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                    json={"start_seconds": 30000, "duration_seconds": 900,
                          "manual_counts": {"S through": 500, "N through": 400}})
        gate2 = client.get(f"/api/projects/{pid}/intersections/{iid}/qa/acceptance").json()
        spot2 = next(i for i in gate2["items"] if i["item"] == "spot_count")
        assert spot2["detail"][0]["covered"] == 2
        assert spot2["verdict"] == "pass"

    def test_single_block_run_needs_one_window(self, spot_project):
        # A single processed block (the standard fixture) => one segment, one
        # window — the stratification must not over-demand on a simple run.
        pid, _, cid = spot_project
        w = client.get(f"/api/projects/{pid}/cameras/{cid}/qa/spot-windows").json()
        assert w["n_segments"] == 1 and len(w["windows"]) == 1


# ---- 3-B validation additions (plan_3b_validation_2026-07-28) ---------------

class TestApproachBindingAndScope:
    def test_approach_outside_target_demotes_pass_to_review(self, spot_project):
        pid, _, cid = spot_project
        # Cancellation shape: S-approach undercount (-20%) offset by an
        # N-approach overcount so the TOTAL passes (-4%, CI within 10%).
        # The per-approach binding must withhold certification (phase-0
        # finding 1: cam5 false-passed exactly this way).
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                        json={"start_seconds": 600, "duration_seconds": 600,
                              "manual_counts": {"S through": 750,
                                                "N through": 460,
                                                "S left": 40}})
        assert r.status_code == 200
        rep = r.json()
        assert abs(rep["total"]["rel_err"]) <= 0.05        # total alone would pass
        assert rep["verdict"] == "review"                  # ...but approaches bind
        assert "approach" in rep["note"]
        outside = {a["approach"] for a in rep["approaches"] if a["outside_target"]}
        assert "S" in outside
    def test_small_approach_cannot_bind(self, spot_project):
        pid, _, cid = spot_project
        # An E-approach cell with only 10 manual vehicles (way off, system 0)
        # stays below APPROACH_MIN_MANUAL and must NOT demote the verdict.
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts",
                        json={"start_seconds": 600, "duration_seconds": 600,
                              "manual_counts": {"S through": 600,
                                                "N through": 560,
                                                "S left": 40,
                                                "E through": 10}})
        assert r.status_code == 200
        rep = r.json()
        e_row = next(a for a in rep["approaches"] if a["approach"] == "E")
        assert e_row["outside_target"] is False
        assert rep["verdict"] == "pass"
    def test_trims_scope_segments_to_reporting_windows(self, spot_two_block):
        pid, iid, cid = spot_two_block
        from backend.services.spot_check import _processed_segments
        before = _processed_segments(pid, cid)
        assert len(before) == 2                            # AM + PM blocks
        conn = get_connection(pid)
        with conn:
            conn.execute(
                "INSERT INTO videos (camera_id, sort_order, path, filename, fps, "
                "width, height, total_frames, duration_seconds, file_size_bytes, "
                "recording_start_datetime, added_at) VALUES (?, 0, 'x.mp4', 'x.mp4', "
                "10, 640, 480, 400000, 40000, 1, '2026-06-12T07:00:00', '2026-06-12')",
                (cid,))
            # Reporting window covers ONLY the AM block: 07:10-07:26 wall-clock
            # = video seconds [600, 1560) given the 07:00:00 recording start.
            conn.execute(
                "INSERT INTO trims (intersection_id, start_wallclock, "
                "end_wallclock, sort_order) VALUES (?, '07:10:00', '07:26:00', 0)",
                (iid,))
        conn.close()
        after = _processed_segments(pid, cid)
        assert len(after) == 1                             # PM block out of scope
        s, e = after[0]
        assert s >= 599.0 and e <= 1600.0


# ---- Stage-4 4.1 tally support (plan_stage4_childtest_ux_2026-07-29) --------

class TestTallySupport:
    def test_windows_payload_static_floor_and_no_system_numbers(self, spot_project):
        """The tally meter consumes ONLY this payload before save — the
        independence rule is enforced by its shape: the static volume
        floor, and nothing system-derived in the windows."""
        pid, iid, cid = spot_project
        r = client.get(
            f"/api/projects/{pid}/cameras/{cid}/qa/spot-windows").json()
        assert r["needed_total_for_ci"] >= 100
        assert r["windows"]
        for w in r["windows"]:
            assert set(w) <= {"segment_index", "segment",
                              "start_seconds", "duration_seconds"}

    def test_save_upserts_by_window(self, spot_project):
        pid, iid, cid = spot_project
        url = f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts"
        client.post(url, json={"start_seconds": 600, "duration_seconds": 600,
                               "manual_counts": {"S through": 300}})
        client.post(url, json={"start_seconds": 600, "duration_seconds": 600,
                               "manual_counts": {"S through": 590,
                                                 "N through": 555}})
        client.post(url, json={"start_seconds": 100, "duration_seconds": 60,
                               "manual_counts": {"S through": 1}})
        spots = client.get(url).json()["spot_counts"]
        same = [s for s in spots if s["start_seconds"] == 600]
        assert len(same) == 1                       # replaced, not stacked
        assert same[0]["manual_counts"]["S through"] == 590
        assert len(spots) == 2                      # the other window kept

    def test_dry_run_flow_extend_then_certify(self, spot_project):
        """The scripted tally flow: save a short accurate count (review +
        extend guidance), re-save the same window fuller (upsert) — the
        report reflects the new count."""
        pid, iid, cid = spot_project
        url = f"/api/projects/{pid}/cameras/{cid}/qa/spot-counts"
        r1 = client.post(url, json={
            "start_seconds": 600, "duration_seconds": 300,
            "manual_counts": {"S through": 300, "N through": 280}}).json()
        assert r1["verdict"] in ("review", "pass")
        assert "approaches" in r1 and r1["total"]["manual"] == 580
        r2 = client.post(url, json={
            "start_seconds": 600, "duration_seconds": 600,
            "manual_counts": {"S through": 640, "N through": 560}}).json()
        assert r2["total"]["manual"] == 1200
        assert r2["verdict"] == "pass"              # exact + enough volume
        spots = client.get(url).json()["spot_counts"]
        # the 600s re-save OVERLAPS the 300s row -> replaced, one row stands
        assert len([s for s in spots if s["start_seconds"] == 600]) == 1
        assert [s for s in spots if s["start_seconds"] == 600][0][
            "duration_seconds"] == 600
