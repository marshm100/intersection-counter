"""v3 Phase 3 — Intersection card API tests."""

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
def project_id():
    r = client.post("/api/projects", json={"name": "v3-intersections-test"})
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _make_video(dir_path: str, name: str, frames: int = 90) -> str:
    """Make a fake video so duration_seconds > 0. 90 frames @ 30fps = 3s."""
    p = os.path.join(dir_path, name)
    w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (320, 240))
    for i in range(frames):
        w.write(np.full((240, 320, 3), 50 + i, dtype=np.uint8))
    w.release()
    return p


@pytest.fixture()
def project_with_two_cameras(project_id):
    """Create a project with 2 cameras at one intersection-day."""
    tmpdir = tempfile.mkdtemp(prefix="v3_isect_")
    try:
        paths = [
            _make_video(tmpdir, "Cam1_01_20260514_080000 Main St.mp4"),
            _make_video(tmpdir, "Cam2_01_20260514_080000 Main St.mp4"),
        ]
        client.post(f"/api/projects/{project_id}/videos/bulk", json={"paths": paths})
        body = client.post(f"/api/projects/{project_id}/videos/save-labels").json()
        intersections = body["intersections"]
        assert len(intersections) == 1
        yield project_id, intersections[0]["intersection_id"]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestIntersectionCRUD:
    def test_list(self, project_with_two_cameras):
        pid, _ = project_with_two_cameras
        r = client.get(f"/api/projects/{pid}/intersections")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_detail_includes_cameras_and_trims(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        r = client.get(f"/api/projects/{pid}/intersections/{iid}")
        body = r.json()
        assert "intersection" in body
        assert len(body["cameras"]) == 2
        assert isinstance(body["trims"], list)

    def test_rename_and_leg_count(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        r = client.patch(
            f"/api/projects/{pid}/intersections/{iid}",
            json={"name": "Main St & Lamar", "leg_count": 5},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Main St & Lamar"
        assert body["leg_count"] == 5

    def test_invalid_leg_count_rejected(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        r = client.patch(
            f"/api/projects/{pid}/intersections/{iid}",
            json={"leg_count": 1},
        )
        assert r.status_code == 422

    def test_delete_cascades(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        r = client.delete(f"/api/projects/{pid}/intersections/{iid}")
        assert r.status_code == 200
        # Intersection gone, cameras gone, videos still on disk but unlinked
        r = client.get(f"/api/projects/{pid}/intersections")
        assert r.json() == []


class TestCameraCRUD:
    def test_list_cameras(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/cameras")
        assert r.status_code == 200
        cams = r.json()
        assert sorted(c["label"] for c in cams) == ["Cam1", "Cam2"]

    def test_rename_camera(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        cams = client.get(f"/api/projects/{pid}/intersections/{iid}/cameras").json()
        cam_id = cams[0]["camera_id"]
        r = client.patch(
            f"/api/projects/{pid}/intersections/{iid}/cameras/{cam_id}",
            json={"label": "NW pole"},
        )
        assert r.status_code == 200
        assert r.json()["label"] == "NW pole"

    def test_delete_camera(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        cams = client.get(f"/api/projects/{pid}/intersections/{iid}/cameras").json()
        cam_id = cams[0]["camera_id"]
        r = client.delete(f"/api/projects/{pid}/intersections/{iid}/cameras/{cam_id}")
        assert r.status_code == 200
        cams = client.get(f"/api/projects/{pid}/intersections/{iid}/cameras").json()
        assert len(cams) == 1


class TestTrimsCRUD:
    def test_add_valid_trim(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        r = client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "08:00:00", "end_wallclock": "08:00:03"},
        )
        assert r.status_code == 200
        assert "trim_id" in r.json()

    def test_trim_end_before_start_rejected(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        r = client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "09:00:00", "end_wallclock": "08:00:00"},
        )
        assert r.status_code == 422

    def test_malformed_trim_time_rejected(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        r = client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "8am", "end_wallclock": "9am"},
        )
        assert r.status_code == 422

    def test_list_trims(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "08:00:00", "end_wallclock": "08:00:02"},
        )
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/trims")
        assert len(r.json()) >= 1

    def test_delete_trim(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        tid = client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "08:00:00", "end_wallclock": "08:00:02"},
        ).json()["trim_id"]
        r = client.delete(f"/api/projects/{pid}/intersections/{iid}/trims/{tid}")
        assert r.status_code == 200


class TestCoverageReport:
    def test_trim_fully_covered_reports_no_gaps(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        # Fake videos run for 3 seconds starting at 08:00:00. Trim within that.
        client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "08:00:00", "end_wallclock": "08:00:02"},
        )
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/coverage-report")
        assert r.status_code == 200
        body = r.json()
        assert len(body["per_trim"]) >= 1
        trim_report = body["per_trim"][-1]
        assert trim_report["is_fully_covered"] is True
        assert trim_report["gaps"] == []

    def test_trim_outside_coverage_reports_gap(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        # Trim well after the video ends (videos run 08:00-08:03)
        client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "10:00:00", "end_wallclock": "10:30:00"},
        )
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/coverage-report")
        body = r.json()
        trim_report = body["per_trim"][-1]
        assert trim_report["is_fully_covered"] is False
        assert len(trim_report["gaps"]) > 0

    def test_parallel_coverage_shows_both_cameras(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        # Both Cam1 and Cam2 cover 08:00-08:03 in parallel; trim within.
        client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "08:00:00", "end_wallclock": "08:00:02"},
        )
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/coverage-report")
        body = r.json()
        trim_report = body["per_trim"][-1]
        # All sub-intervals should have 2 camera_ids in parallel
        for sub in trim_report["sub_intervals"]:
            assert len(sub["camera_ids"]) == 2
