"""Journey labels (2026-09-30, docs/research_tracking_2026-09-29.md phase 0):
the operator's per-vehicle ground truth — entry leg, exit leg, the frames and
the clicked positions, a class — stored per clip."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection
from backend.services import journey_labels as jl

client = TestClient(app)


@pytest.fixture()
def clip_project():
    r = client.post("/api/projects", json={"name": "journeys"})
    pid = r.json()["project_id"]
    conn = get_connection(pid)
    with conn:
        vid = conn.execute(
            "INSERT INTO videos (camera_id, sort_order, path, filename, fps, width, "
            "height, total_frames, duration_seconds, file_size_bytes, added_at) "
            "VALUES (NULL, 0, 'x.mp4', 'x.mp4', 10, 640, 480, 100000, 10000, 1, "
            "'2026-09-30')").lastrowid
    conn.close()
    jl.upsert_clip(pid, "cam4_1605", 4, vid, 1000, 2800, 10.0, "cam4 16:05")
    yield pid, vid
    client.delete(f"/api/projects/{pid}")


def _journey(**over):
    j = {"entry_leg_id": 1, "entry_leg_label": "N", "entry_frame": 1100,
         "entry_x": 300.0, "entry_y": 200.0, "exit_leg_id": 3,
         "exit_leg_label": "S", "exit_frame": 1180, "exit_x": 310.0,
         "exit_y": 420.0, "vehicle_class": "car"}
    j.update(over)
    return j


class TestJourneyLabels:
    def test_clips_are_listed_with_label_counts(self, clip_project):
        pid, _ = clip_project
        r = client.get(f"/api/projects/{pid}/journey-clips")
        assert r.status_code == 200
        clips = r.json()["clips"]
        assert clips[0]["clip_id"] == "cam4_1605" and clips[0]["n_labels"] == 0
        assert clips[0]["video_width"] == 640

    def test_a_full_journey_is_saved_and_listed(self, clip_project):
        pid, _ = clip_project
        r = client.post(f"/api/projects/{pid}/journey-clips/cam4_1605/labels",
                        json=_journey())
        assert r.status_code == 200
        labels = client.get(
            f"/api/projects/{pid}/journey-clips/cam4_1605/labels").json()["labels"]
        assert len(labels) == 1
        assert labels[0]["entry_leg_label"] == "N" and labels[0]["exit_frame"] == 1180

    def test_a_vehicle_already_inside_at_the_clip_start_has_no_entry(self, clip_project):
        pid, _ = clip_project
        r = client.post(f"/api/projects/{pid}/journey-clips/cam4_1605/labels",
                        json=_journey(entry_frame=None, entry_leg_id=None))
        assert r.status_code == 200
        assert r.json()["entry_leg_id"] is None and r.json()["entry_x"] is None

    def test_invalid_journeys_are_refused(self, clip_project):
        pid, _ = clip_project
        url = f"/api/projects/{pid}/journey-clips/cam4_1605/labels"
        assert client.post(url, json=_journey(exit_frame=1050)).status_code == 422
        assert client.post(url, json=_journey(entry_frame=900)).status_code == 422
        assert client.post(url, json=_journey(entry_frame=None, exit_frame=None)
                           ).status_code == 422
        assert client.post(url, json=_journey(vehicle_class="boat")).status_code == 422
        assert client.post(url, json=_journey(exit_x=None)).status_code == 422

    def test_delete_and_unknown_clip(self, clip_project):
        pid, _ = clip_project
        lid = client.post(f"/api/projects/{pid}/journey-clips/cam4_1605/labels",
                          json=_journey()).json()["label_id"]
        assert client.delete(
            f"/api/projects/{pid}/journey-clips/cam4_1605/labels/{lid}").status_code == 200
        assert client.get(
            f"/api/projects/{pid}/journey-clips/cam4_1605/labels").json()["labels"] == []
        assert client.get(f"/api/projects/{pid}/journey-clips/nope/labels").status_code == 404

    def test_upsert_clip_keeps_labels(self, clip_project):
        pid, vid = clip_project
        client.post(f"/api/projects/{pid}/journey-clips/cam4_1605/labels", json=_journey())
        jl.upsert_clip(pid, "cam4_1605", 4, vid, 1000, 2900, 10.0, "cam4 16:05")
        assert jl.list_clips(pid)[0]["n_labels"] == 1
        assert jl.list_clips(pid)[0]["end_frame"] == 2900
