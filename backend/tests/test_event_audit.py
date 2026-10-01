"""The event audit (2026-10-01): sampled counted events, judged by the operator
on the video; the latest verdict per item stands."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services import event_audit as ea

client = TestClient(app)


def _item(**over):
    it = {"batch": "a1", "camera_id": 2, "video_id": 1, "window": "study_0700",
          "vehicle_track_id": 655, "stratum": "exit_only|branch1",
          "claimed_origin_leg_id": 28, "claimed_dest_leg_id": 29,
          "claimed_movement": "right", "claim_detail": "origin inferred, exit over S",
          "start_frame": 1000, "end_frame": 1300, "fps": 25.0,
          "track_json": [[1000, 425.0, 113.0, 28.0, 14.0], [1290, 44.0, 107.0, 20.0, 10.0]]}
    it.update(over)
    return it


@pytest.fixture()
def pid():
    p = client.post("/api/projects", json={"name": "audit"}).json()["project_id"]
    yield p
    client.delete(f"/api/projects/{p}")


def test_items_list_light_and_get_with_track(pid):
    i1 = ea.add_item(pid, _item())
    ea.add_item(pid, _item(batch="a2"))
    r = client.get(f"/api/projects/{pid}/audit-items", params={"batch": "a1"}).json()
    assert [x["item_id"] for x in r["items"]] == [i1]
    assert "track_json" not in r["items"][0] and r["items"][0]["answer"] is None
    it = client.get(f"/api/projects/{pid}/audit-items/{i1}").json()
    assert it["track"][0][1] == 425.0 and it["claimed_movement"] == "right"


def test_latest_answer_stands(pid):
    i1 = ea.add_item(pid, _item())
    client.post(f"/api/projects/{pid}/audit-items/{i1}/answer", json={"verdict": "correct"})
    r = client.post(f"/api/projects/{pid}/audit-items/{i1}/answer",
                    json={"verdict": "not_intersection", "note": "far road"})
    assert r.status_code == 200 and r.json()["verdict"] == "not_intersection"
    items = client.get(f"/api/projects/{pid}/audit-items").json()["items"]
    assert items[0]["answer"]["verdict"] == "not_intersection"


def test_wrong_movement_needs_the_true_legs(pid):
    i1 = ea.add_item(pid, _item())
    bad = client.post(f"/api/projects/{pid}/audit-items/{i1}/answer",
                      json={"verdict": "wrong_movement"})
    assert bad.status_code == 422
    ok = client.post(f"/api/projects/{pid}/audit-items/{i1}/answer",
                     json={"verdict": "wrong_movement", "true_origin_leg_id": 27,
                           "true_dest_leg_id": 29})
    assert ok.status_code == 200


def test_unknown_verdict_and_item(pid):
    i1 = ea.add_item(pid, _item())
    assert client.post(f"/api/projects/{pid}/audit-items/{i1}/answer",
                       json={"verdict": "maybe"}).status_code == 422
    assert client.post(f"/api/projects/{pid}/audit-items/9999/answer",
                       json={"verdict": "correct"}).status_code == 404
