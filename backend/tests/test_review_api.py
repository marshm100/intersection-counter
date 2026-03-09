"""Tests for the review router API (Step 6)."""

import sys
from unittest.mock import MagicMock

import pytest

for _mod in ("cv2", "numpy", "ultralytics", "supervision", "scipy", "sklearn"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.database import get_connection  # noqa: E402

client = TestClient(app)

PROJECT_ID = "test-review-project"


def _setup():
    conn = get_connection(PROJECT_ID)
    conn.execute("DELETE FROM vehicle_events")
    conn.execute("DELETE FROM legs")
    conn.execute("DELETE FROM project_info")
    conn.commit()
    conn.close()


def _insert_leg(conn, label: str, sort_order: int = 1) -> int:
    cur = conn.execute(
        "INSERT INTO legs (label, cardinal_direction, sort_order, origin_zone, reference_heading) VALUES (?, ?, ?, ?, ?)",
        (label, "N", sort_order, "[[0,0]]", 0.0),
    )
    conn.commit()
    return cur.lastrowid


def _insert_vehicle_event(conn, origin_leg_id: int, movement: str = "through",
                           vehicle_class: str = "car", traj_conf: float = 0.9) -> int:
    cur = conn.execute(
        "INSERT INTO vehicle_events (vehicle_track_id, origin_leg_id, movement, trajectory_data, "
        "trajectory_confidence, vehicle_class, detection_confidence, timestamp_video, frame_number) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, origin_leg_id, movement, "[]", traj_conf, vehicle_class, 0.8, 0.0, 1),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# 1. Empty
# ---------------------------------------------------------------------------

def test_review_empty():
    _setup()
    conn = get_connection(PROJECT_ID)
    _insert_leg(conn, "North")
    conn.close()

    r = client.get(f"/api/projects/{PROJECT_ID}/review")
    assert r.status_code == 200
    body = r.json()
    assert body["events"] == []
    assert body["total"] == 0


# ---------------------------------------------------------------------------
# 2. Pagination
# ---------------------------------------------------------------------------

def test_review_pagination():
    _setup()
    conn = get_connection(PROJECT_ID)
    leg_id = _insert_leg(conn, "North")
    for _ in range(60):
        _insert_vehicle_event(conn, leg_id)
    conn.close()

    r1 = client.get(f"/api/projects/{PROJECT_ID}/review?page=1&page_size=50")
    assert r1.status_code == 200
    body1 = r1.json()
    assert len(body1["events"]) == 50
    assert body1["total"] == 60

    r2 = client.get(f"/api/projects/{PROJECT_ID}/review?page=2&page_size=50")
    assert r2.status_code == 200
    body2 = r2.json()
    assert len(body2["events"]) == 10


# ---------------------------------------------------------------------------
# 3. Filter by leg
# ---------------------------------------------------------------------------

def test_review_filter_by_leg():
    _setup()
    conn = get_connection(PROJECT_ID)
    leg1 = _insert_leg(conn, "North", 1)
    leg2 = _insert_leg(conn, "South", 2)
    _insert_vehicle_event(conn, leg1)
    _insert_vehicle_event(conn, leg2)
    conn.close()

    r = client.get(f"/api/projects/{PROJECT_ID}/review?leg_id={leg1}")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["events"][0]["origin_leg_id"] == leg1


# ---------------------------------------------------------------------------
# 4. Filter by movement
# ---------------------------------------------------------------------------

def test_review_filter_by_movement():
    _setup()
    conn = get_connection(PROJECT_ID)
    leg_id = _insert_leg(conn, "North")
    _insert_vehicle_event(conn, leg_id, movement="through")
    _insert_vehicle_event(conn, leg_id, movement="left")
    conn.close()

    r = client.get(f"/api/projects/{PROJECT_ID}/review?movement=through")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["events"][0]["movement"] == "through"


# ---------------------------------------------------------------------------
# 5. PATCH event ok
# ---------------------------------------------------------------------------

def test_patch_event_ok():
    _setup()
    conn = get_connection(PROJECT_ID)
    leg_id = _insert_leg(conn, "North")
    event_id = _insert_vehicle_event(conn, leg_id, movement="through", vehicle_class="car")
    conn.close()

    r = client.patch(
        f"/api/projects/{PROJECT_ID}/review/{event_id}",
        json={"movement": "left", "vehicle_class": "truck"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["movement"] == "left"
    assert body["vehicle_class"] == "truck"
    assert body["manually_edited"] == 1


# ---------------------------------------------------------------------------
# 6. PATCH invalid movement → 422
# ---------------------------------------------------------------------------

def test_patch_event_invalid_movement():
    _setup()
    conn = get_connection(PROJECT_ID)
    leg_id = _insert_leg(conn, "North")
    event_id = _insert_vehicle_event(conn, leg_id)
    conn.close()

    r = client.patch(
        f"/api/projects/{PROJECT_ID}/review/{event_id}",
        json={"movement": "invalid"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 7. PATCH invalid vehicle_class → 422
# ---------------------------------------------------------------------------

def test_patch_event_invalid_class():
    _setup()
    conn = get_connection(PROJECT_ID)
    leg_id = _insert_leg(conn, "North")
    event_id = _insert_vehicle_event(conn, leg_id)
    conn.close()

    r = client.patch(
        f"/api/projects/{PROJECT_ID}/review/{event_id}",
        json={"vehicle_class": "plane"},
    )
    assert r.status_code == 422
