"""Tests for the processing router API (Step 5.5)."""

import os
import sys
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# Stub heavy native modules before any project imports so tests work without
# the full ML stack installed.
for _mod in ("cv2", "numpy", "ultralytics", "supervision", "scipy", "sklearn"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Provide a realistic cv2.VideoCapture stub used by _load_prerequisites.
_cv2_stub = sys.modules["cv2"]
_cap_stub = MagicMock()
_cap_stub.get.return_value = 30.0  # fps
_cap_stub.isOpened.return_value = True
_cv2_stub.VideoCapture.return_value = _cap_stub
_cv2_stub.CAP_PROP_FPS = 5
_cv2_stub.CAP_PROP_FRAME_COUNT = 7

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.database import get_connection, set_project_info, get_db_path  # noqa: E402

client = TestClient(app)

PROJECT_ID = "test-proc-project"


def _create_project_db(video_path: str | None = None, with_legs: bool = True):
    """Set up a test project with optional video_path and legs."""
    conn = get_connection(PROJECT_ID)
    conn.execute("DELETE FROM vehicle_events")
    conn.execute("DELETE FROM legs")
    conn.execute("DELETE FROM checkpoint")
    conn.execute("DELETE FROM project_info")
    conn.commit()
    conn.close()

    set_project_info(PROJECT_ID, "status", "idle")
    if video_path:
        set_project_info(PROJECT_ID, "video_path", video_path)
    if with_legs:
        conn = get_connection(PROJECT_ID)
        conn.execute(
            "INSERT INTO legs (label, cardinal_direction, sort_order, origin_zone, reference_heading) "
            "VALUES (?, ?, ?, ?, ?)",
            ("North", "N", 1, "[[0,0],[100,0]]", 0.0),
        )
        conn.commit()
        conn.close()


def _fake_video():
    """Return a path to a temporary file that acts as a video placeholder."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    return tmp.name


def _cleanup_state():
    """Clear module-level state between tests."""
    import backend.routers.processing as proc
    with proc._state_lock:
        proc._pipelines.clear()
        proc._progress.clear()
        proc._threads.clear()


@pytest.fixture(autouse=True)
def reset_state():
    _cleanup_state()
    yield
    _cleanup_state()


# ---------------------------------------------------------------------------
# 1. start ok
# ---------------------------------------------------------------------------

def test_start_ok():
    video = _fake_video()
    try:
        _create_project_db(video_path=video, with_legs=True)

        with patch("backend.routers.processing.ProcessingPipeline") as MockPipeline:
            instance = MagicMock()
            instance.pause_requested = threading.Event()
            MockPipeline.return_value = instance

            r = client.post(f"/api/projects/{PROJECT_ID}/processing/start")
            assert r.status_code == 200
            assert r.json()["status"] == "ok"
    finally:
        os.unlink(video)


# ---------------------------------------------------------------------------
# 2. start already running → 409
# ---------------------------------------------------------------------------

def test_start_already_running_409():
    video = _fake_video()
    try:
        _create_project_db(video_path=video, with_legs=True)

        with patch("backend.routers.processing.ProcessingPipeline") as MockPipeline:
            instance = MagicMock()
            instance.pause_requested = threading.Event()

            def slow_process(*a, **kw):
                time.sleep(5)

            instance.process_video.side_effect = slow_process
            MockPipeline.return_value = instance

            client.post(f"/api/projects/{PROJECT_ID}/processing/start")

            r = client.post(f"/api/projects/{PROJECT_ID}/processing/start")
            assert r.status_code == 409
    finally:
        os.unlink(video)


# ---------------------------------------------------------------------------
# 3. start with no video → 400
# ---------------------------------------------------------------------------

def test_start_no_video_400():
    _create_project_db(video_path=None, with_legs=True)
    r = client.post(f"/api/projects/{PROJECT_ID}/processing/start")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 4. start with no legs → 400
# ---------------------------------------------------------------------------

def test_start_no_legs_400():
    video = _fake_video()
    try:
        _create_project_db(video_path=video, with_legs=False)
        r = client.post(f"/api/projects/{PROJECT_ID}/processing/start")
        assert r.status_code == 400
    finally:
        os.unlink(video)


# ---------------------------------------------------------------------------
# 5. pause when running → ok
# ---------------------------------------------------------------------------

def test_pause_when_running_ok():
    import backend.routers.processing as proc

    mock_pipeline = MagicMock()
    mock_pipeline.pause_requested = threading.Event()

    with proc._state_lock:
        proc._pipelines[PROJECT_ID] = mock_pipeline

    _create_project_db(video_path=None, with_legs=False)
    r = client.post(f"/api/projects/{PROJECT_ID}/processing/pause")
    assert r.status_code == 200
    mock_pipeline.pause.assert_called_once()


# ---------------------------------------------------------------------------
# 6. pause when idle → 400
# ---------------------------------------------------------------------------

def test_pause_when_idle_400():
    _create_project_db(video_path=None, with_legs=False)
    r = client.post(f"/api/projects/{PROJECT_ID}/processing/pause")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 7. resume with no checkpoint → 400
# ---------------------------------------------------------------------------

def test_resume_no_checkpoint_400():
    _create_project_db(video_path=None, with_legs=False)
    r = client.post(f"/api/projects/{PROJECT_ID}/processing/resume")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 8. resume ok
# ---------------------------------------------------------------------------

def test_resume_ok():
    video = _fake_video()
    try:
        _create_project_db(video_path=video, with_legs=True)

        # Insert a fake checkpoint row
        conn = get_connection(PROJECT_ID)
        conn.execute(
            "INSERT OR REPLACE INTO checkpoint "
            "(id, frame_number, timestamp_video, tracker_state, active_trajectories, "
            "vehicle_count, error_count, updated_at) "
            "VALUES (1, 1000, 33.3, NULL, NULL, 5, 0, '2024-01-01T00:00:00')"
        )
        conn.commit()
        conn.close()

        with patch("backend.routers.processing.ProcessingPipeline") as MockPipeline:
            instance = MagicMock()
            instance.pause_requested = threading.Event()
            instance.resume_from_checkpoint.return_value = 940
            MockPipeline.return_value = instance

            r = client.post(f"/api/projects/{PROJECT_ID}/processing/resume")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok"
            # start_frame is now an internal detail of the orchestrator thread
            # (it calls resume_from_checkpoint per-video). The endpoint instead
            # reports resume_video_id when applicable.
            assert "resume_video_id" in body
    finally:
        os.unlink(video)


# ---------------------------------------------------------------------------
# 9. cancel clears state
# ---------------------------------------------------------------------------

def test_cancel_clears_state():
    import backend.routers.processing as proc

    _create_project_db(video_path=None, with_legs=False)

    mock_pipeline = MagicMock()
    mock_pipeline.pause_requested = threading.Event()

    with proc._state_lock:
        proc._pipelines[PROJECT_ID] = mock_pipeline
        proc._progress[PROJECT_ID] = {"frame_number": 100}

    r = client.post(f"/api/projects/{PROJECT_ID}/processing/cancel")
    assert r.status_code == 200

    with proc._state_lock:
        assert PROJECT_ID not in proc._pipelines
        assert PROJECT_ID not in proc._progress


# ---------------------------------------------------------------------------
# 10. status progress populated
# ---------------------------------------------------------------------------

def test_status_progress_populated():
    import backend.routers.processing as proc

    _create_project_db(video_path=None, with_legs=False)
    set_project_info(PROJECT_ID, "status", "processing")

    progress_data = {
        "frame_number": 4500,
        "total_frames": 54000,
        "progress_pct": 8.33,
        "vehicle_count": 47,
        "fps_processing": 12.5,
        "error_count": 0,
        "eta_seconds": 3480.0,
    }
    mock_pipeline = MagicMock()

    with proc._state_lock:
        proc._pipelines[PROJECT_ID] = mock_pipeline
        proc._progress[PROJECT_ID] = progress_data

    r = client.get(f"/api/projects/{PROJECT_ID}/processing/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "processing"
    assert body["is_running"] is True
    assert body["progress"]["vehicle_count"] == 47
    assert body["progress"]["fps_processing"] == 12.5


# ---------------------------------------------------------------------------
# 11. status complete after thread exits
# ---------------------------------------------------------------------------

def test_status_complete_after_thread_exits():
    video = _fake_video()
    try:
        _create_project_db(video_path=video, with_legs=True)

        with patch("backend.routers.processing.ProcessingPipeline") as MockPipeline:
            instance = MagicMock()
            instance.pause_requested = threading.Event()
            instance.process_video.return_value = None  # returns immediately
            MockPipeline.return_value = instance

            client.post(f"/api/projects/{PROJECT_ID}/processing/start")

            # Wait for thread to finish
            deadline = time.time() + 5
            while time.time() < deadline:
                r = client.get(f"/api/projects/{PROJECT_ID}/processing/status")
                if not r.json()["is_running"]:
                    break
                time.sleep(0.1)

        r = client.get(f"/api/projects/{PROJECT_ID}/processing/status")
        body = r.json()
        assert body["is_running"] is False
        assert body["status"] == "complete"
    finally:
        os.unlink(video)
