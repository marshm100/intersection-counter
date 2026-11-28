"""The hand count (2026-11-28): presses saved as one JSON file per session; DEV-validation only."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


@pytest.fixture()
def pid():
    p = client.post("/api/projects", json={"name": "handcount"}).json()["project_id"]
    yield p
    client.delete(f"/api/projects/{p}")


def test_missing_session_is_empty(pid):
    r = client.get(f"/api/projects/{pid}/hand-counts/s1").json()
    assert r["taps"] == [] and r["exists"] is False


def test_save_then_load_round_trip(pid):
    body = {"video_id": 2, "from_wall": "08:31:00", "to_wall": "08:34:00",
            "taps": [{"t": 30662.4, "kind": "red", "x": 120, "y": 110}, {"t": 30670.0, "kind": "green"}]}
    assert client.put(f"/api/projects/{pid}/hand-counts/s1", json=body).json()["saved"] == 2
    body["taps"] = body["taps"][:1]
    client.put(f"/api/projects/{pid}/hand-counts/s1", json=body)
    r = client.get(f"/api/projects/{pid}/hand-counts/s1").json()
    assert r["exists"] and [t["kind"] for t in r["taps"]] == ["red"] and r["taps"][0]["x"] == 120


def test_bad_session_name_and_project(pid):
    assert client.get(f"/api/projects/{pid}/hand-counts/a.b").status_code == 400
    assert client.get("/api/projects/nope/hand-counts/s1").status_code == 404


def test_video_without_start_time_is_409(pid):
    assert client.get(f"/api/projects/{pid}/hand-counts/video/99").status_code == 404
