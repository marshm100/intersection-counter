"""CRUD tests for /api/projects/{p}/cameras/{c}/channels — Phase 2.1.

Operator-drawn channel persistence: GET (list), PUT (full replace with
validation), DELETE (clear). Mirrors the paths-API fixture: one project,
one camera, two legs so the leg FKs resolve.
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
    """(project_id, camera_id, leg1_id, leg2_id) with calibrated legs."""
    r = client.post("/api/projects", json={"name": "channels-api-test"})
    pid = r.json()["project_id"]
    tmpdir = tempfile.mkdtemp(prefix="channels_api_")
    try:
        path = _make_video(tmpdir, "Cam1_01_20260514_080000 Main St.mp4")
        client.post(f"/api/projects/{pid}/videos/bulk", json={"paths": [path]})
        body = client.post(f"/api/projects/{pid}/videos/save-labels").json()
        iid = body["intersections"][0]["intersection_id"]
        cams = client.get(f"/api/projects/{pid}/intersections/{iid}/cameras").json()
        cid = cams[0]["camera_id"]
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
        yield pid, cid, legs[0]["leg_id"], legs[1]["leg_id"]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        client.delete(f"/api/projects/{pid}")


def _channel(l1, l2, **over):
    ch = {"origin_leg_id": l1, "destination_leg_id": l2, "movement": "through",
          "entry": [100, 110], "apex": [100, 250], "exit": [100, 390],
          "width_in": 50, "width_out": 30}
    ch.update(over)
    return ch


class TestChannelsCrud:
    def test_empty_list_initially(self, project_with_camera_and_legs):
        pid, cid, _, _ = project_with_camera_and_legs
        r = client.get(f"/api/projects/{pid}/cameras/{cid}/channels")
        assert r.status_code == 200
        assert r.json() == {"channels": []}

    def test_put_then_get_roundtrip(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        r = client.put(f"/api/projects/{pid}/cameras/{cid}/channels",
                       json={"channels": [_channel(l1, l2),
                                          _channel(l2, l1, movement="left")]})
        assert r.status_code == 200
        saved = r.json()["channels"]
        assert len(saved) == 2
        got = client.get(f"/api/projects/{pid}/cameras/{cid}/channels").json()["channels"]
        assert len(got) == 2
        ch = [c for c in got if c["origin_leg_id"] == l1][0]
        assert ch["movement"] == "through"
        assert ch["entry"] == [100, 110]
        assert ch["apex"] == [100, 250]
        assert ch["exit"] == [100, 390]
        assert ch["width_in"] == 50

    def test_put_is_full_replace(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        client.put(f"/api/projects/{pid}/cameras/{cid}/channels",
                   json={"channels": [_channel(l1, l2), _channel(l2, l1)]})
        client.put(f"/api/projects/{pid}/cameras/{cid}/channels",
                   json={"channels": [_channel(l1, l2, movement="right")]})
        got = client.get(f"/api/projects/{pid}/cameras/{cid}/channels").json()["channels"]
        assert len(got) == 1
        assert got[0]["movement"] == "right"

    def test_delete_clears_all(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        client.put(f"/api/projects/{pid}/cameras/{cid}/channels",
                   json={"channels": [_channel(l1, l2)]})
        r = client.delete(f"/api/projects/{pid}/cameras/{cid}/channels")
        assert r.status_code == 200
        got = client.get(f"/api/projects/{pid}/cameras/{cid}/channels").json()["channels"]
        assert got == []


class TestChannelsValidation:
    def test_bad_movement_rejected(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        r = client.put(f"/api/projects/{pid}/cameras/{cid}/channels",
                       json={"channels": [_channel(l1, l2, movement="sideways")]})
        assert r.status_code == 422

    def test_foreign_leg_rejected(self, project_with_camera_and_legs):
        pid, cid, l1, _ = project_with_camera_and_legs
        r = client.put(f"/api/projects/{pid}/cameras/{cid}/channels",
                       json={"channels": [_channel(l1, 999999)]})
        assert r.status_code == 422

    def test_out_of_frame_point_rejected(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        r = client.put(f"/api/projects/{pid}/cameras/{cid}/channels",
                       json={"channels": [_channel(l1, l2, entry=[5000, 5000])]})
        assert r.status_code == 422

    def test_bad_width_rejected(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        r = client.put(f"/api/projects/{pid}/cameras/{cid}/channels",
                       json={"channels": [_channel(l1, l2, width_in=1000)]})
        assert r.status_code == 422

    def test_invalid_put_leaves_table_untouched(self, project_with_camera_and_legs):
        pid, cid, l1, l2 = project_with_camera_and_legs
        client.put(f"/api/projects/{pid}/cameras/{cid}/channels",
                   json={"channels": [_channel(l1, l2)]})
        r = client.put(f"/api/projects/{pid}/cameras/{cid}/channels",
                       json={"channels": [_channel(l1, l2, movement="bogus")]})
        assert r.status_code == 422
        got = client.get(f"/api/projects/{pid}/cameras/{cid}/channels").json()["channels"]
        assert len(got) == 1
        assert got[0]["movement"] == "through"
