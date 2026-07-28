"""F3 stage A — range-capable video streaming (plan_f3_playback_studio_2026-07-28).

The endpoint serves bytes; it never parses the container — so the tests
use a small synthetic file with known content and exercise the Range
grammar + boundary math end-to-end through the API.
"""
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection

client = TestClient(app)

CONTENT = bytes(range(256)) * 4          # 1024 known bytes


@pytest.fixture()
def stream_project(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(CONTENT)
    r = client.post("/api/projects", json={"name": "f3-stream"})
    pid = r.json()["project_id"]
    conn = get_connection(pid)
    with conn:
        cur = conn.execute(
            "INSERT INTO videos (camera_id, sort_order, path, filename, fps, width, "
            "height, total_frames, duration_seconds, file_size_bytes, added_at) "
            "VALUES (NULL, 0, ?, 'clip.mp4', 10, 640, 480, 100, 10, ?, '2026-07-28')",
            (str(f), len(CONTENT)))
        vid = cur.lastrowid
    conn.close()
    yield pid, vid, f
    client.delete(f"/api/projects/{pid}")


class TestStream:
    def test_full_file_without_range(self, stream_project):
        pid, vid, _f = stream_project
        r = client.get(f"/api/projects/{pid}/videos/{vid}/stream")
        assert r.status_code == 200
        assert r.headers["accept-ranges"] == "bytes"
        assert r.headers["content-type"] == "video/mp4"
        assert r.content == CONTENT

    def test_partial_range(self, stream_project):
        pid, vid, _f = stream_project
        r = client.get(f"/api/projects/{pid}/videos/{vid}/stream",
                       headers={"Range": "bytes=10-19"})
        assert r.status_code == 206
        assert r.headers["content-range"] == f"bytes 10-19/{len(CONTENT)}"
        assert r.headers["content-length"] == "10"
        assert r.content == CONTENT[10:20]

    def test_open_ended_range(self, stream_project):
        pid, vid, _f = stream_project
        r = client.get(f"/api/projects/{pid}/videos/{vid}/stream",
                       headers={"Range": "bytes=1000-"})
        assert r.status_code == 206
        assert r.content == CONTENT[1000:]
        assert r.headers["content-range"] == f"bytes 1000-1023/{len(CONTENT)}"

    def test_suffix_range(self, stream_project):
        pid, vid, _f = stream_project
        r = client.get(f"/api/projects/{pid}/videos/{vid}/stream",
                       headers={"Range": "bytes=-16"})
        assert r.status_code == 206
        assert r.content == CONTENT[-16:]

    def test_end_clamped_to_size(self, stream_project):
        pid, vid, _f = stream_project
        r = client.get(f"/api/projects/{pid}/videos/{vid}/stream",
                       headers={"Range": "bytes=1020-9999"})
        assert r.status_code == 206
        assert r.content == CONTENT[1020:]

    def test_out_of_bounds_416(self, stream_project):
        pid, vid, _f = stream_project
        r = client.get(f"/api/projects/{pid}/videos/{vid}/stream",
                       headers={"Range": "bytes=5000-6000"})
        assert r.status_code == 416
        assert r.headers["content-range"] == f"bytes */{len(CONTENT)}"

    def test_malformed_range_416(self, stream_project):
        pid, vid, _f = stream_project
        r = client.get(f"/api/projects/{pid}/videos/{vid}/stream",
                       headers={"Range": "bytes=abc"})
        assert r.status_code == 416

    def test_missing_file_404(self, stream_project):
        pid, vid, f = stream_project
        f.unlink()
        r = client.get(f"/api/projects/{pid}/videos/{vid}/stream")
        assert r.status_code == 404
