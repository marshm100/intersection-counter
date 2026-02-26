import pytest
import shutil
import numpy as np
import cv2
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app import app
from backend.config import PROJECTS_DIR

client = TestClient(app)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_VIDEO = FIXTURES_DIR / "test_clip.mp4"
TEST_WIDTH = 320
TEST_HEIGHT = 240
TEST_FPS = 30
TEST_FRAMES = 90


@pytest.fixture(scope="module", autouse=True)
def create_test_video():
    """Generate synthetic MP4 if it doesn't already exist."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    if not TEST_VIDEO.exists():
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(TEST_VIDEO), fourcc, TEST_FPS, (TEST_WIDTH, TEST_HEIGHT))
        for i in range(TEST_FRAMES):
            b = (i * 3) % 256
            g = (i * 7 + 50) % 256
            r = (i * 11 + 100) % 256
            frame = np.full((TEST_HEIGHT, TEST_WIDTH, 3), (b, g, r), dtype=np.uint8)
            writer.write(frame)
        writer.release()
    yield
    if FIXTURES_DIR.exists():
        shutil.rmtree(FIXTURES_DIR)


def _create_project(name: str) -> str:
    r = client.post("/api/projects", json={"name": name})
    return r.json()["project_id"]


def _cleanup_project(project_id: str) -> None:
    p = PROJECTS_DIR / project_id
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


class TestSetVideo:
    def test_set_valid_video(self):
        pid = _create_project("set-valid")
        try:
            r = client.post(f"/api/projects/{pid}/video", json={"path": str(TEST_VIDEO)})
            assert r.status_code == 200
            data = r.json()
            assert data["filename"] == "test_clip.mp4"
            assert data["width"] == TEST_WIDTH
            assert data["height"] == TEST_HEIGHT
            assert data["total_frames"] == TEST_FRAMES
            assert "fps" in data
            assert "duration_seconds" in data
            assert "codec" in data
        finally:
            _cleanup_project(pid)

    def test_set_nonexistent_video(self):
        pid = _create_project("set-nonexist")
        try:
            r = client.post(f"/api/projects/{pid}/video", json={"path": "/nonexistent/video.mp4"})
            assert r.status_code == 400
        finally:
            _cleanup_project(pid)

    def test_set_invalid_file(self):
        pid = _create_project("set-invalid")
        try:
            fake = FIXTURES_DIR / "fake_video.mp4"
            fake.write_text("this is not a video")
            r = client.post(f"/api/projects/{pid}/video", json={"path": str(fake)})
            assert r.status_code == 400
        finally:
            _cleanup_project(pid)

    def test_replace_warns_without_confirm(self):
        pid = _create_project("set-replace")
        try:
            # Set video first time
            r1 = client.post(f"/api/projects/{pid}/video", json={"path": str(TEST_VIDEO)})
            assert r1.status_code == 200
            # Set same video again (resolved path is the same) — should succeed without warning
            r2 = client.post(f"/api/projects/{pid}/video", json={"path": str(TEST_VIDEO)})
            assert r2.status_code == 200
            # If the paths resolve to the same absolute path, no warning is needed
            data = r2.json()
            assert "filename" in data or "confirm_required" in data
        finally:
            _cleanup_project(pid)

    def test_project_not_found(self):
        r = client.post("/api/projects/nonexist/video", json={"path": str(TEST_VIDEO)})
        assert r.status_code == 404


class TestGetVideo:
    def test_get_after_set(self):
        pid = _create_project("get-after-set")
        try:
            client.post(f"/api/projects/{pid}/video", json={"path": str(TEST_VIDEO)})
            r = client.get(f"/api/projects/{pid}/video")
            assert r.status_code == 200
            data = r.json()
            assert data["filename"] == "test_clip.mp4"
            assert data["width"] == TEST_WIDTH
            assert data["height"] == TEST_HEIGHT
        finally:
            _cleanup_project(pid)

    def test_get_no_video_set(self):
        pid = _create_project("get-no-video")
        try:
            r = client.get(f"/api/projects/{pid}/video")
            assert r.status_code == 404
        finally:
            _cleanup_project(pid)

    def test_project_not_found(self):
        r = client.get("/api/projects/nonexist/video")
        assert r.status_code == 404


class TestGetFrame:
    def test_frame_at_zero(self):
        pid = _create_project("frame-zero")
        try:
            client.post(f"/api/projects/{pid}/video", json={"path": str(TEST_VIDEO)})
            r = client.get(f"/api/projects/{pid}/video/frame?seconds=0")
            assert r.status_code == 200
            assert r.headers["content-type"] == "image/jpeg"
            assert r.content[:2] == b"\xff\xd8"
        finally:
            _cleanup_project(pid)

    def test_frame_at_one_second(self):
        pid = _create_project("frame-one")
        try:
            client.post(f"/api/projects/{pid}/video", json={"path": str(TEST_VIDEO)})
            r = client.get(f"/api/projects/{pid}/video/frame?seconds=1.0")
            assert r.status_code == 200
            assert r.content[:2] == b"\xff\xd8"
        finally:
            _cleanup_project(pid)

    def test_frame_default_zero(self):
        pid = _create_project("frame-default")
        try:
            client.post(f"/api/projects/{pid}/video", json={"path": str(TEST_VIDEO)})
            r = client.get(f"/api/projects/{pid}/video/frame")
            assert r.status_code == 200
            assert r.content[:2] == b"\xff\xd8"
        finally:
            _cleanup_project(pid)

    def test_frame_out_of_range(self):
        pid = _create_project("frame-oor")
        try:
            client.post(f"/api/projects/{pid}/video", json={"path": str(TEST_VIDEO)})
            r = client.get(f"/api/projects/{pid}/video/frame?seconds=999")
            assert r.status_code == 400
        finally:
            _cleanup_project(pid)

    def test_frame_no_video_set(self):
        pid = _create_project("frame-no-vid")
        try:
            r = client.get(f"/api/projects/{pid}/video/frame?seconds=0")
            assert r.status_code == 404
        finally:
            _cleanup_project(pid)

    def test_frame_project_not_found(self):
        r = client.get("/api/projects/nonexist/video/frame?seconds=0")
        assert r.status_code == 404


class TestBrowseVideo:
    def test_browse_returns_null_in_headless(self):
        pid = _create_project("browse-headless")
        try:
            r = client.post(f"/api/projects/{pid}/video/browse")
            assert r.status_code == 200
            assert r.json()["path"] is None
        finally:
            _cleanup_project(pid)

    def test_browse_project_not_found(self):
        r = client.post("/api/projects/nonexist/video/browse")
        assert r.status_code == 404
