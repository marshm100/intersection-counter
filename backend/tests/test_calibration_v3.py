"""v3 Phase 3 — Camera-scoped calibration tests."""

import json
import os
import shutil
import tempfile

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app


client = TestClient(app)


@pytest.fixture()
def project_with_one_camera():
    r = client.post("/api/projects", json={"name": "v3-cal-test"})
    pid = r.json()["project_id"]
    tmpdir = tempfile.mkdtemp(prefix="v3_cal_")
    try:
        p = os.path.join(tmpdir, "Cam1_01_20260514_080000 Main St.mp4")
        w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (320, 240))
        for _ in range(15):
            w.write(np.zeros((240, 320, 3), dtype=np.uint8))
        w.release()
        client.post(f"/api/projects/{pid}/videos/bulk", json={"paths": [p]})
        body = client.post(f"/api/projects/{pid}/videos/save-labels").json()
        iid = body["intersections"][0]["intersection_id"]
        cam_id = client.get(
            f"/api/projects/{pid}/intersections/{iid}/cameras"
        ).json()[0]["camera_id"]
        yield pid, cam_id
    finally:
        client.delete(f"/api/projects/{pid}")
        shutil.rmtree(tmpdir, ignore_errors=True)


def _sample_legs():
    return {
        "legs": [
            {
                "label": "North",
                "cardinal_direction": "N",
                "sort_order": 0,
                "origin_zone": [[100, 50]],
                "reference_heading": 0.0,
            },
            {
                "label": "East",
                "cardinal_direction": "E",
                "sort_order": 1,
                "origin_zone": [[250, 150]],
                "reference_heading": 90.0,
            },
        ]
    }


class TestGetEmpty:
    def test_get_camera_calibration_empty(self, project_with_one_camera):
        pid, cam_id = project_with_one_camera
        r = client.get(f"/api/projects/{pid}/cameras/{cam_id}/calibration")
        assert r.status_code == 200
        assert r.json()["legs"] == []

    def test_404_for_missing_camera(self):
        # Need a project, then ask for a nonexistent camera
        pid = client.post("/api/projects", json={"name": "x"}).json()["project_id"]
        try:
            r = client.get(f"/api/projects/{pid}/cameras/9999/calibration")
            assert r.status_code == 404
        finally:
            client.delete(f"/api/projects/{pid}")


class TestSaveLegs:
    def test_put_legs(self, project_with_one_camera):
        pid, cam_id = project_with_one_camera
        r = client.put(
            f"/api/projects/{pid}/cameras/{cam_id}/calibration/legs",
            json=_sample_legs(),
        )
        assert r.status_code == 200
        legs = r.json()["legs"]
        assert len(legs) == 2
        assert sorted(l["label"] for l in legs) == ["East", "North"]

    def test_round_trip(self, project_with_one_camera):
        pid, cam_id = project_with_one_camera
        client.put(
            f"/api/projects/{pid}/cameras/{cam_id}/calibration/legs",
            json=_sample_legs(),
        )
        r = client.get(f"/api/projects/{pid}/cameras/{cam_id}/calibration")
        assert len(r.json()["legs"]) == 2

    def test_replaces_existing(self, project_with_one_camera):
        pid, cam_id = project_with_one_camera
        client.put(
            f"/api/projects/{pid}/cameras/{cam_id}/calibration/legs",
            json=_sample_legs(),
        )
        # Now replace with just one leg
        client.put(
            f"/api/projects/{pid}/cameras/{cam_id}/calibration/legs",
            json={"legs": [_sample_legs()["legs"][0]]},
        )
        r = client.get(f"/api/projects/{pid}/cameras/{cam_id}/calibration")
        assert len(r.json()["legs"]) == 1

    def test_label_only_save_preserves_events_and_leg_ids(
            self, project_with_one_camera):
        """6.4 rehearsal finding #2: relabeling a PROCESSED camera (the
        FM51 mislabeled-cardinals fix, the compass wizard's Apply) must
        not wipe its counted events — same geometry -> in-place update."""
        from backend.database import get_connection

        pid, cam_id = project_with_one_camera
        client.put(f"/api/projects/{pid}/cameras/{cam_id}/calibration/legs",
                   json=_sample_legs())
        legs0 = client.get(
            f"/api/projects/{pid}/cameras/{cam_id}/calibration").json()["legs"]
        conn = get_connection(pid)
        with conn:
            conn.execute(
                "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                "origin_leg_id, destination_leg_id, movement, trajectory_data, "
                "trajectory_confidence, vehicle_class, detection_confidence, "
                "timestamp_video, frame_number) VALUES (?, 1, ?, ?, 'through', "
                "'[]', 0.9, 'car', 0.9, 10.0, 100)",
                (cam_id, legs0[0]["leg_id"], legs0[1]["leg_id"]))
        conn.close()
        relabeled = _sample_legs()
        relabeled["legs"][0]["cardinal_direction"] = "NE"   # the wizard's edit
        relabeled["legs"][0]["label"] = "Northeast"
        r = client.put(f"/api/projects/{pid}/cameras/{cam_id}/calibration/legs",
                       json=relabeled)
        assert r.status_code == 200
        legs1 = r.json()["legs"]
        assert [l["leg_id"] for l in legs1] == [l["leg_id"] for l in legs0]
        assert legs1[0]["cardinal_direction"] == "NE"
        conn = get_connection(pid)
        n = conn.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?",
                         (cam_id,)).fetchone()[0]
        conn.close()
        assert n == 1                                   # events SURVIVED

    def test_moved_node_still_wipes(self, project_with_one_camera):
        from backend.database import get_connection

        pid, cam_id = project_with_one_camera
        client.put(f"/api/projects/{pid}/cameras/{cam_id}/calibration/legs",
                   json=_sample_legs())
        legs0 = client.get(
            f"/api/projects/{pid}/cameras/{cam_id}/calibration").json()["legs"]
        conn = get_connection(pid)
        with conn:
            conn.execute(
                "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                "origin_leg_id, destination_leg_id, movement, trajectory_data, "
                "trajectory_confidence, vehicle_class, detection_confidence, "
                "timestamp_video, frame_number) VALUES (?, 1, ?, ?, 'through', "
                "'[]', 0.9, 'car', 0.9, 10.0, 100)",
                (cam_id, legs0[0]["leg_id"], legs0[1]["leg_id"]))
        conn.close()
        moved = _sample_legs()
        moved["legs"][0]["origin_zone"] = [[140, 80]]     # geometry changed
        client.put(f"/api/projects/{pid}/cameras/{cam_id}/calibration/legs",
                   json=moved)
        conn = get_connection(pid)
        n = conn.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?",
                         (cam_id,)).fetchone()[0]
        conn.close()
        assert n == 0                                   # recalibration wipes

    def test_empty_legs_rejected(self, project_with_one_camera):
        pid, cam_id = project_with_one_camera
        r = client.put(
            f"/api/projects/{pid}/cameras/{cam_id}/calibration/legs",
            json={"legs": []},
        )
        assert r.status_code == 422


class TestIsolation:
    def test_two_cameras_have_independent_legs(self):
        """Saving legs on Camera A should not touch Camera B's legs."""
        pid = client.post("/api/projects", json={"name": "v3-iso"}).json()["project_id"]
        tmpdir = tempfile.mkdtemp(prefix="v3_iso_")
        try:
            # Two cameras at the same intersection-day
            for name in ["Cam1_01_20260514_080000 Main St.mp4",
                         "Cam2_01_20260514_080000 Main St.mp4"]:
                p = os.path.join(tmpdir, name)
                w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (320, 240))
                for _ in range(15):
                    w.write(np.zeros((240, 320, 3), dtype=np.uint8))
                w.release()
                client.post(f"/api/projects/{pid}/videos/bulk", json={"paths": [p]})
            body = client.post(f"/api/projects/{pid}/videos/save-labels").json()
            iid = body["intersections"][0]["intersection_id"]
            cams = client.get(
                f"/api/projects/{pid}/intersections/{iid}/cameras"
            ).json()
            cam_a, cam_b = cams[0]["camera_id"], cams[1]["camera_id"]

            client.put(
                f"/api/projects/{pid}/cameras/{cam_a}/calibration/legs",
                json=_sample_legs(),
            )
            # Camera B should still have no legs
            r = client.get(f"/api/projects/{pid}/cameras/{cam_b}/calibration")
            assert r.json()["legs"] == []
            # Camera A has its legs
            r = client.get(f"/api/projects/{pid}/cameras/{cam_a}/calibration")
            assert len(r.json()["legs"]) == 2
        finally:
            client.delete(f"/api/projects/{pid}")
            shutil.rmtree(tmpdir, ignore_errors=True)
