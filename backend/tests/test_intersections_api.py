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


class TestCalibrationParams:
    """Per-intersection calibration tunables (set in the leg-calibration UI).

    These four columns are nullable overrides; NULL = use the config default.
    The PATCH endpoint round-trips floats and accepts null to clear.
    """

    def test_detail_includes_calibration_defaults(self, project_with_two_cameras):
        """The defaults must be exposed so the UI can render them as
        placeholder text next to the per-intersection override inputs."""
        pid, iid = project_with_two_cameras
        body = client.get(f"/api/projects/{pid}/intersections/{iid}").json()
        d = body.get("calibration_defaults")
        assert d is not None
        for k in ("tripwire_half_length_px", "trajectory_through_max_angle",
                  "trajectory_turn_min_angle", "trajectory_uturn_min_angle"):
            assert k in d
            assert isinstance(d[k], (int, float))
        # And fresh intersections have no overrides yet.
        isect = body["intersection"]
        assert isect["calib_tripwire_half_length_px"] is None
        assert isect["calib_trajectory_through_max_angle"] is None

    def test_set_and_clear_tripwire_override(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        # Set
        r = client.patch(f"/api/projects/{pid}/intersections/{iid}",
                         json={"calib_tripwire_half_length_px": 200.0})
        assert r.status_code == 200, r.text
        assert r.json()["calib_tripwire_half_length_px"] == 200.0
        # Clear (explicit null)
        r = client.patch(f"/api/projects/{pid}/intersections/{iid}",
                         json={"calib_tripwire_half_length_px": None})
        assert r.status_code == 200, r.text
        assert r.json()["calib_tripwire_half_length_px"] is None

    def test_tripwire_range_check(self, project_with_two_cameras):
        pid, iid = project_with_two_cameras
        r = client.patch(f"/api/projects/{pid}/intersections/{iid}",
                         json={"calib_tripwire_half_length_px": 5.0})
        assert r.status_code == 422
        r = client.patch(f"/api/projects/{pid}/intersections/{iid}",
                         json={"calib_tripwire_half_length_px": 600.0})
        assert r.status_code == 422

    def test_angle_ordering_invariant(self, project_with_two_cameras):
        """through_max < turn_min <= uturn_min must hold across the effective
        values after the PATCH, even when only one of the three is being set."""
        pid, iid = project_with_two_cameras
        # Setting through_max above default turn_min (35) violates ordering.
        r = client.patch(f"/api/projects/{pid}/intersections/{iid}",
                         json={"calib_trajectory_through_max_angle": 50.0})
        assert r.status_code == 422
        # Valid: all three set with proper ordering.
        r = client.patch(f"/api/projects/{pid}/intersections/{iid}", json={
            "calib_trajectory_through_max_angle": 20.0,
            "calib_trajectory_turn_min_angle": 40.0,
            "calib_trajectory_uturn_min_angle": 140.0,
        })
        assert r.status_code == 200, r.text
        # Invalid: turn_min > uturn_min.
        r = client.patch(f"/api/projects/{pid}/intersections/{iid}", json={
            "calib_trajectory_uturn_min_angle": 30.0,
        })
        assert r.status_code == 422

    def test_unrelated_patch_does_not_touch_overrides(self, project_with_two_cameras):
        """PATCHing just the name must leave calibration overrides intact."""
        pid, iid = project_with_two_cameras
        client.patch(f"/api/projects/{pid}/intersections/{iid}",
                     json={"calib_tripwire_half_length_px": 175.0})
        r = client.patch(f"/api/projects/{pid}/intersections/{iid}",
                         json={"name": "Renamed"})
        assert r.status_code == 200
        assert r.json()["calib_tripwire_half_length_px"] == 175.0

    def test_get_calibration_params_helper(self, project_with_two_cameras):
        """The backend helper returns the override when set, otherwise the
        default — so the pipeline always gets a complete dict."""
        from backend.database import get_calibration_params
        from backend.config import (
            TRIPWIRE_HALF_LENGTH_PX, TRAJECTORY_THROUGH_MAX_ANGLE,
        )
        pid, iid = project_with_two_cameras
        # Fresh: all defaults.
        eff = get_calibration_params(pid, iid)
        assert eff["tripwire_half_length_px"] == TRIPWIRE_HALF_LENGTH_PX
        assert eff["trajectory_through_max_angle"] == TRAJECTORY_THROUGH_MAX_ANGLE
        # After override: overridden value comes back, untouched stays at default.
        client.patch(f"/api/projects/{pid}/intersections/{iid}",
                     json={"calib_tripwire_half_length_px": 90.0})
        eff = get_calibration_params(pid, iid)
        assert eff["tripwire_half_length_px"] == 90.0
        assert eff["trajectory_through_max_angle"] == TRAJECTORY_THROUGH_MAX_ANGLE


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
