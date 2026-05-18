import shutil
from fastapi.testclient import TestClient
from backend.app import app
from backend.config import PROJECTS_DIR

client = TestClient(app)

def test_list_empty():
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_create_project():
    response = client.post("/api/projects", json={"name": "Test Intersection"})
    assert response.status_code == 200
    data = response.json()
    assert "project_id" in data
    assert data["name"] == "Test Intersection"
    assert len(data["project_id"]) == 8
    # Clean up
    shutil.rmtree(PROJECTS_DIR / data["project_id"], ignore_errors=True)

def test_create_and_list():
    r1 = client.post("/api/projects", json={"name": "Project A"})
    r2 = client.post("/api/projects", json={"name": "Project B"})
    id1 = r1.json()["project_id"]
    id2 = r2.json()["project_id"]

    response = client.get("/api/projects")
    projects = response.json()
    ids = [p["project_id"] for p in projects]
    assert id1 in ids
    assert id2 in ids

    # Clean up
    shutil.rmtree(PROJECTS_DIR / id1, ignore_errors=True)
    shutil.rmtree(PROJECTS_DIR / id2, ignore_errors=True)

def test_get_project():
    r = client.post("/api/projects", json={"name": "Detail Test"})
    pid = r.json()["project_id"]

    response = client.get(f"/api/projects/{pid}")
    assert response.status_code == 200
    data = response.json()
    assert data["project_name"] == "Detail Test"
    assert data["status"] == "created"

    # Clean up
    shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)

def test_rename_project():
    r = client.post("/api/projects", json={"name": "Old Name"})
    pid = r.json()["project_id"]

    response = client.put(f"/api/projects/{pid}/name", json={"name": "New Name"})
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"

    detail = client.get(f"/api/projects/{pid}")
    assert detail.json()["project_name"] == "New Name"

    # Clean up
    shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)

def test_delete_project():
    r = client.post("/api/projects", json={"name": "To Delete"})
    pid = r.json()["project_id"]

    response = client.delete(f"/api/projects/{pid}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True

    # Verify gone
    response = client.get(f"/api/projects/{pid}")
    assert response.status_code == 404

def test_not_found():
    response = client.get("/api/projects/nonexist")
    assert response.status_code == 404

    response = client.delete("/api/projects/nonexist")
    assert response.status_code == 404


def test_has_video_true_when_video_in_videos_table():
    """v3 projects keep videos in the videos table, not project_info.
    The list endpoint must recognise either signal as 'has_video'."""
    from backend.database import get_connection
    from datetime import datetime, timezone

    r = client.post("/api/projects", json={"name": "v3 has-video"})
    pid = r.json()["project_id"]
    try:
        # Insert a video row directly to simulate the v3 upload path.
        conn = get_connection(pid)
        conn.execute(
            """INSERT INTO videos
               (sort_order, path, filename, fps, width, height, total_frames,
                duration_seconds, file_size_bytes, added_at)
               VALUES (0, '/tmp/x.mp4', 'x.mp4', 30.0, 1920, 1080, 900,
                       30.0, 1000, ?)""",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
        conn.close()

        listing = client.get("/api/projects").json()
        row = next(p for p in listing if p["project_id"] == pid)
        assert row["has_video"] is True, "v3 project with video should report has_video=true"
    finally:
        shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)


def test_has_video_false_when_no_video_anywhere():
    """Fresh project, no v2 video_path and no rows in videos — still 'needs video'."""
    r = client.post("/api/projects", json={"name": "empty"})
    pid = r.json()["project_id"]
    try:
        listing = client.get("/api/projects").json()
        row = next(p for p in listing if p["project_id"] == pid)
        assert row["has_video"] is False
    finally:
        shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)


def test_processing_modes_endpoint_returns_fast_and_accurate():
    """Frontend selector consumes this. Both modes must be present with
    labels and descriptions, plus a sensible default key."""
    r = client.get("/api/processing-modes")
    assert r.status_code == 200
    body = r.json()
    keys = {m["key"] for m in body["modes"]}
    assert "fast" in keys
    assert "accurate" in keys
    assert body["default"] in keys
    for m in body["modes"]:
        assert m["label"]
        assert m["description"]


def test_processing_mode_roundtrips_through_settings():
    """PUT /settings persists processing_mode; GET /projects/{id} returns it."""
    r = client.post("/api/projects", json={"name": "mode-test"})
    pid = r.json()["project_id"]
    try:
        # Default — not set yet, project_info won't have the key
        proj = client.get(f"/api/projects/{pid}").json()
        assert proj.get("processing_mode") in (None, "accurate")

        # Set to fast
        r2 = client.put(f"/api/projects/{pid}/settings",
                        json={"processing_mode": "fast"})
        assert r2.status_code == 200

        proj2 = client.get(f"/api/projects/{pid}").json()
        assert proj2["processing_mode"] == "fast"

        # Unknown mode → 422 with helpful detail
        r3 = client.put(f"/api/projects/{pid}/settings",
                        json={"processing_mode": "ludicrous"})
        assert r3.status_code == 422
        assert "ludicrous" in str(r3.json()["detail"])
    finally:
        shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)
