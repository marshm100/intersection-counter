"""Tests for the §3-A export gate (backend/services/spot_check.export_gate +
the gated backend/routers/export.py download).

Reuses the conservation-QA synthetic fixture style (one project, cardinal legs,
events inserted directly), adding fhwa_class (the classification precondition)
and an intersection_paths row (the bank precondition)."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection

client = TestClient(app)


def _mk_intersection(pid, name, sort_order, *, with_bank=True, with_class=True):
    """Build one intersection (1 camera, 4 cardinal legs, N<->S throughs).
    with_bank inserts an intersection_paths row; with_class sets fhwa_class."""
    conn = get_connection(pid)
    with conn:
        cur = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES (?, '2026-06-30', ?, 4, '2026-06-30')", (name, sort_order))
        iid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'cam', 0, '2026-06-30')", (iid,))
        cid = cur.lastrowid
        legs = {}
        for card, (x, y) in {"N": (320, 460), "S": (320, 20),
                             "E": (20, 240), "W": (620, 240)}.items():
            cur = conn.execute(
                "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
                "origin_zone, reference_heading) VALUES (?, ?, ?, 0, ?, 0)",
                (cid, card, card, json.dumps([[x, y]])))
            legs[card] = cur.lastrowid
        fhwa = 2 if with_class else None
        i = 0
        for (a, b), n in {("N", "S"): 200, ("S", "N"): 190}.items():
            for _ in range(n):
                ts = 600.0 + 30.0 * i / 400    # short window -> reverse-balance info
                conn.execute(
                    "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                    "origin_leg_id, destination_leg_id, movement, fhwa_class, rejected, "
                    "trajectory_data, trajectory_confidence, vehicle_class, "
                    "detection_confidence, timestamp_video, frame_number) "
                    "VALUES (?, ?, ?, ?, 'through', ?, 0, '[]', 1.0, 'car', 0.9, ?, ?)",
                    (cid, i, legs[a], legs[b], fhwa, ts, int(ts * 10)))
                i += 1
        if with_bank:
            conn.execute(
                "INSERT INTO intersection_paths (camera_id, origin_leg_id, "
                "destination_leg_id, polyline, movement_label, supporting_count, "
                "source, created_at) "
                "VALUES (?, ?, ?, ?, 'through', 100, 'test', '2026-06-30')",
                (cid, legs["N"], legs["S"],
                 json.dumps([[320, 460], [320, 240], [320, 20]])))
    conn.close()
    return iid, cid


@pytest.fixture()
def gated_project():
    r = client.post("/api/projects", json={"name": "export-gate-test"})
    pid = r.json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


class TestExportGate:
    def test_review_allows_draft_download(self, gated_project):
        pid = gated_project
        _mk_intersection(pid, "A", 0, with_bank=True, with_class=True)
        g = client.get(f"/api/projects/{pid}/export/gate").json()
        assert g["blocking"] is False
        assert g["overall"] in ("review", "ship")
        ix = g["intersections"][0]
        assert ix["bank_exists"] is True and ix["classified"] is True
        # a draft is allowed at 'review' (no override needed)
        r = client.get(f"/api/projects/{pid}/export/download")
        assert r.status_code == 200

    def test_missing_bank_blocks_download(self, gated_project):
        pid = gated_project
        _mk_intersection(pid, "A", 0, with_bank=False, with_class=True)
        g = client.get(f"/api/projects/{pid}/export/gate").json()
        assert g["blocking"] is True and g["overall"] == "fail"
        assert any("no path bank" in r for r in g["blocking_reasons"])
        assert client.get(f"/api/projects/{pid}/export/download").status_code == 409
        # explicit override streams the file anyway
        assert client.get(
            f"/api/projects/{pid}/export/download?override=true").status_code == 200

    def test_missing_classification_blocks_download(self, gated_project):
        pid = gated_project
        _mk_intersection(pid, "A", 0, with_bank=True, with_class=False)
        g = client.get(f"/api/projects/{pid}/export/gate").json()
        assert g["blocking"] is True
        assert any("classification" in r for r in g["blocking_reasons"])
        assert client.get(f"/api/projects/{pid}/export/download").status_code == 409

    def test_worst_wins_across_intersections(self, gated_project):
        pid = gated_project
        _mk_intersection(pid, "A_good", 0, with_bank=True, with_class=True)
        _mk_intersection(pid, "B_nobank", 1, with_bank=False, with_class=True)
        g = client.get(f"/api/projects/{pid}/export/gate").json()
        assert g["overall"] == "fail" and g["blocking"] is True
        assert any("B_nobank" in r for r in g["blocking_reasons"])
        # both intersections are reported; the bank state is per-intersection
        by_name = {i["name"]: i for i in g["intersections"]}
        assert by_name["A_good"]["bank_exists"] is True
        assert by_name["B_nobank"]["bank_exists"] is False
