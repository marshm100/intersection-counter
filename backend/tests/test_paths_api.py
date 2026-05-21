"""CRUD tests for /api/projects/{p}/cameras/{c}/paths — Phase 2.

Each test fixture creates a fresh project with one intersection, one
camera, and two legs so the (origin_leg_id, destination_leg_id) FK
references resolve.
"""
import os
import shutil
import tempfile

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app


client = TestClient(app)


def _make_video(dir_path: str, name: str, frames: int = 60) -> str:
    p = os.path.join(dir_path, name)
    w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (640, 480))
    for i in range(frames):
        w.write(np.full((480, 640, 3), 50 + i, dtype=np.uint8))
    w.release()
    return p


@pytest.fixture()
def project_with_camera_and_legs():
    """Create a project with one intersection, one camera, two legs.

    Returns (project_id, camera_id, leg1_id, leg2_id).
    """
    r = client.post("/api/projects", json={"name": "paths-api-test"})
    pid = r.json()["project_id"]
    tmpdir = tempfile.mkdtemp(prefix="paths_api_")
    try:
        # Add a video so the camera exists.
        path = _make_video(tmpdir, "Cam1_01_20260514_080000 Main St.mp4")
        client.post(f"/api/projects/{pid}/videos/bulk",
                    json={"paths": [path]})
        body = client.post(f"/api/projects/{pid}/videos/save-labels").json()
        iid = body["intersections"][0]["intersection_id"]
        cams = client.get(f"/api/projects/{pid}/intersections/{iid}/cameras").json()
        cid = cams[0]["camera_id"]

        # Calibrate two legs so the path FKs resolve.
        client.put(
            f"/api/projects/{pid}/cameras/{cid}/calibration/legs",
            json={"legs": [
                {"label": "L1", "cardinal_direction": "N", "sort_order": 0,
                 "origin_zone": [[100, 100]], "reference_heading": 0.0},
                {"label": "L2", "cardinal_direction": "S", "sort_order": 1,
                 "origin_zone": [[100, 400]], "reference_heading": 180.0},
            ]},
        )
        legs = client.get(f"/api/projects/{pid}/cameras/{cid}/calibration").json()["legs"]
        leg_ids = [l["leg_id"] for l in legs]
        yield (pid, cid, leg_ids[0], leg_ids[1])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        client.delete(f"/api/projects/{pid}")


def _path_body(origin_lid, dest_lid, poly=None, label="through",
               source="manual", supporting=10):
    return {
        "origin_leg_id": origin_lid,
        "destination_leg_id": dest_lid,
        "polyline": poly or [[100, 100], [100, 250], [100, 400]],
        "movement_label": label,
        "supporting_count": supporting,
        "source": source,
    }


class TestPathsCRUD:
    def test_list_starts_empty(self, project_with_camera_and_legs):
        pid, cid, *_ = project_with_camera_and_legs
        r = client.get(f"/api/projects/{pid}/cameras/{cid}/paths")
        assert r.status_code == 200
        assert r.json() == {"paths": []}

    def test_upsert_then_list_round_trip(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/paths",
                        json=_path_body(l1, l2))
        assert r.status_code == 200, r.text
        path_id = r.json()["path_id"]
        assert path_id > 0
        assert r.json()["polyline"] == [[100, 100], [100, 250], [100, 400]]
        # Listed back.
        listed = client.get(f"/api/projects/{pid}/cameras/{cid}/paths").json()
        assert len(listed["paths"]) == 1
        assert listed["paths"][0]["path_id"] == path_id

    def test_upsert_same_key_updates_in_place(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        r1 = client.post(f"/api/projects/{pid}/cameras/{cid}/paths",
                         json=_path_body(l1, l2, label="through")).json()
        r2 = client.post(f"/api/projects/{pid}/cameras/{cid}/paths",
                         json=_path_body(l1, l2, label="right",
                                         poly=[[100, 100], [200, 200], [300, 300]])).json()
        # Same path_id, updated fields.
        assert r1["path_id"] == r2["path_id"]
        listed = client.get(f"/api/projects/{pid}/cameras/{cid}/paths").json()
        assert len(listed["paths"]) == 1
        assert listed["paths"][0]["movement_label"] == "right"

    def test_bulk_replace(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        # Seed one path.
        client.post(f"/api/projects/{pid}/cameras/{cid}/paths",
                    json=_path_body(l1, l2))
        # Bulk replace with two new paths (opposite directions).
        r = client.put(f"/api/projects/{pid}/cameras/{cid}/paths", json={"paths": [
            _path_body(l1, l2, label="through"),
            _path_body(l2, l1, label="through",
                       poly=[[100, 400], [100, 250], [100, 100]]),
        ]})
        assert r.status_code == 200
        assert len(r.json()["paths"]) == 2

    def test_delete_one(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        path_id = client.post(
            f"/api/projects/{pid}/cameras/{cid}/paths",
            json=_path_body(l1, l2)).json()["path_id"]
        r = client.delete(f"/api/projects/{pid}/cameras/{cid}/paths/{path_id}")
        assert r.status_code == 200
        assert client.get(f"/api/projects/{pid}/cameras/{cid}/paths").json() == {"paths": []}

    def test_delete_404_for_missing(self, project_with_camera_and_legs):
        pid, cid, *_ = project_with_camera_and_legs
        r = client.delete(f"/api/projects/{pid}/cameras/{cid}/paths/99999")
        assert r.status_code == 404

    def test_clear_all(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        client.post(f"/api/projects/{pid}/cameras/{cid}/paths",
                    json=_path_body(l1, l2))
        client.post(f"/api/projects/{pid}/cameras/{cid}/paths",
                    json=_path_body(l2, l1,
                                    poly=[[100, 400], [100, 250], [100, 100]]))
        r = client.delete(f"/api/projects/{pid}/cameras/{cid}/paths")
        assert r.status_code == 200
        assert r.json()["count"] == 2
        assert client.get(f"/api/projects/{pid}/cameras/{cid}/paths").json() == {"paths": []}


class TestPathsValidation:
    def test_invalid_movement_label_rejected(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/paths",
                        json=_path_body(l1, l2, label="bear-right"))
        assert r.status_code == 422
        assert "movement_label" in r.text

    def test_polyline_too_short_rejected(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/paths",
                        json=_path_body(l1, l2, poly=[[100, 100]]))
        assert r.status_code == 422

    def test_point_out_of_frame_rejected(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/paths",
                        json=_path_body(l1, l2,
                                        poly=[[100, 100], [9999, 9999]]))
        assert r.status_code == 422

    def test_unknown_leg_rejected(self, project_with_camera_and_legs):
        pid, cid, l1, _ = project_with_camera_and_legs
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/paths",
                        json=_path_body(l1, 99999))
        assert r.status_code == 422
        assert "destination_leg_id" in r.text

    def test_camera_404(self):
        # Use a real project but a bogus camera id.
        r = client.post("/api/projects", json={"name": "tmp"}).json()
        pid = r["project_id"]
        try:
            resp = client.get(f"/api/projects/{pid}/cameras/9999/paths")
            assert resp.status_code == 404
        finally:
            client.delete(f"/api/projects/{pid}")
