"""v3 Phase 4 — processing endpoints (preflight + status + cancel).

The /start endpoint kicks off real pipeline work in a thread, which is
slow and torch-dependent. We exercise it via preflight (pure planning,
no pipeline spawn) and verify the status/cancel surfaces respond correctly.
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


def _make_video(dir_path: str, name: str, frames: int = 90) -> str:
    p = os.path.join(dir_path, name)
    w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (320, 240))
    for i in range(frames):
        w.write(np.full((240, 320, 3), 50 + i, dtype=np.uint8))
    w.release()
    return p


@pytest.fixture()
def configured_intersection():
    """Project with 2 cameras at an intersection-day and one valid trim."""
    pid = client.post("/api/projects", json={"name": "v3-proc"}).json()["project_id"]
    tmpdir = tempfile.mkdtemp(prefix="v3_proc_")
    try:
        paths = [
            _make_video(tmpdir, "Cam1_01_20260514_080000 Main St.mp4"),
            _make_video(tmpdir, "Cam2_01_20260514_080000 Main St.mp4"),
        ]
        client.post(f"/api/projects/{pid}/videos/bulk", json={"paths": paths})
        body = client.post(f"/api/projects/{pid}/videos/save-labels").json()
        iid = body["intersections"][0]["intersection_id"]
        # Add a trim well within coverage (videos run 08:00:00-08:00:03)
        client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "08:00:00", "end_wallclock": "08:00:02"},
        )
        yield pid, iid
    finally:
        client.delete(f"/api/projects/{pid}")
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestPreflight:
    def test_preflight_ok_returns_segments(self, configured_intersection):
        pid, iid = configured_intersection
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/preflight")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["errors"] == []
        # 2 cameras × 1 trim × 1 video each = 2 segments
        assert body["segment_count"] == 2
        assert sorted(body["cameras_used"]) and sorted(body["trims_used"])

    def test_preflight_reports_uncovered_trim(self, configured_intersection):
        pid, iid = configured_intersection
        # Add an uncovered trim
        client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "20:00:00", "end_wallclock": "21:00:00"},
        )
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/preflight")
        body = r.json()
        assert body["ok"] is False
        assert len(body["errors"]) >= 1
        assert "no video coverage" in body["errors"][0].lower()


class TestStartGuard:
    def test_start_refuses_on_coverage_error(self, configured_intersection):
        pid, iid = configured_intersection
        # Wipe the good trim, leave only a bad one
        trims = client.get(f"/api/projects/{pid}/intersections/{iid}/trims").json()
        for t in trims:
            client.delete(f"/api/projects/{pid}/intersections/{iid}/trims/{t['trim_id']}")
        client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "20:00:00", "end_wallclock": "21:00:00"},
        )
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/start")
        assert r.status_code == 422
        assert "trim coverage errors" in str(r.json()["detail"])

    def test_start_refuses_with_no_trims(self, configured_intersection):
        pid, iid = configured_intersection
        # Wipe all trims so plan yields "no trims"
        trims = client.get(f"/api/projects/{pid}/intersections/{iid}/trims").json()
        for t in trims:
            client.delete(f"/api/projects/{pid}/intersections/{iid}/trims/{t['trim_id']}")
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/start")
        assert r.status_code == 422


class TestStatusBeforeStart:
    def test_idle_status(self, configured_intersection):
        pid, iid = configured_intersection
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/processing/status")
        assert r.status_code == 200
        assert r.json()["status"] == "idle"


class TestCancelNoOpOnIdle:
    def test_cancel_when_idle_is_safe(self, configured_intersection):
        pid, iid = configured_intersection
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/cancel")
        # Always returns 200; cancellation only takes effect on a running job
        assert r.status_code == 200
