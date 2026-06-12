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
