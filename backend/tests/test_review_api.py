"""Tests for the review router API (Step 6)."""

import sqlite3
import sys
import time
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
    # Resilient to the known transient OneDrive file lock (reference_onedrive_locks):
    # retry briefly and ALWAYS close so a locked attempt can't leak a connection
    # and cascade the lock into the next test.
    last = None
    for _ in range(15):
        conn = None
        try:
            conn = get_connection(PROJECT_ID)
            conn.execute("DELETE FROM vehicle_events")
            conn.execute("DELETE FROM legs")
            conn.execute("DELETE FROM project_info")
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            last = e
            time.sleep(0.2)
        finally:
            if conn is not None:
                conn.close()
    raise last


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


# ---------------------------------------------------------------------------
# trajectory_data exposure + add-missed-vehicle (Phase 9)
# ---------------------------------------------------------------------------

def test_review_returns_trajectory_data():
    """The overlay needs trajectory_data; GET /review must expose it."""
    _setup()
    conn = get_connection(PROJECT_ID)
    leg = _insert_leg(conn, "North")
    conn.execute(
        "INSERT INTO vehicle_events (vehicle_track_id, origin_leg_id, movement, trajectory_data, "
        "trajectory_confidence, vehicle_class, detection_confidence, timestamp_video, frame_number) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (5, leg, "through", "[[1,2],[3,4]]", 0.9, "car", 0.8, 1.0, 10),
    )
    conn.commit(); conn.close()
    r = client.get(f"/api/projects/{PROJECT_ID}/review")
    assert r.status_code == 200
    ev = r.json()["events"][0]
    assert ev["trajectory_data"] == "[[1,2],[3,4]]"


def test_add_missed_vehicle_creates_counted_event():
    import json
    _setup()
    conn = get_connection(PROJECT_ID)
    leg = _insert_leg(conn, "North")
    conn.close()
    r = client.post(f"/api/projects/{PROJECT_ID}/review", json={
        "origin_leg_id": leg, "movement": "left", "timestamp_video": 12.5,
        "x": 100, "y": 200})
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["movement"] == "left"
    assert ev["manually_edited"] == 1
    assert ev["rejected"] == 0
    assert ev["leg_label"] == "North"
    assert json.loads(ev["trajectory_data"]) == [[100.0, 200.0]]
    # It is persisted and counted in the list.
    g = client.get(f"/api/projects/{PROJECT_ID}/review")
    assert g.json()["total"] == 1


def test_add_missed_vehicle_derives_camera_from_leg():
    """camera_id is taken from the origin leg so the event scopes to v3.
    Uses a REAL camera so the vehicle_events.camera_id FK is satisfied."""
    from backend.database import upsert_camera, upsert_intersection
    _setup()
    iid = upsert_intersection(PROJECT_ID, name="ReviewT", date="2026-06-08", leg_count=4)
    cid = upsert_camera(PROJECT_ID, iid, "cam1")
    conn = get_connection(PROJECT_ID)
    cur = conn.execute(
        "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, origin_zone, reference_heading) "
        "VALUES (?,?,?,?,?,?)",
        (cid, "EastLeg", "E", 1, "[[0,0]]", 90.0),
    )
    conn.commit(); leg = cur.lastrowid; conn.close()
    r = client.post(f"/api/projects/{PROJECT_ID}/review", json={
        "origin_leg_id": leg, "movement": "through", "timestamp_video": 1.0})
    assert r.status_code == 200, r.text
    eid = r.json()["event_id"]
    conn = get_connection(PROJECT_ID)
    cam = conn.execute("SELECT camera_id FROM vehicle_events WHERE event_id=?", (eid,)).fetchone()[0]
    conn.close()
    assert cam == cid


def test_add_missed_vehicle_invalid_movement_rejected():
    _setup()
    conn = get_connection(PROJECT_ID)
    leg = _insert_leg(conn, "North")
    conn.close()
    r = client.post(f"/api/projects/{PROJECT_ID}/review", json={
        "origin_leg_id": leg, "movement": "diagonal", "timestamp_video": 1.0})
    assert r.status_code == 422


def test_add_missed_vehicle_unknown_leg_404():
    _setup()
    r = client.post(f"/api/projects/{PROJECT_ID}/review", json={
        "origin_leg_id": 99999, "movement": "through", "timestamp_video": 1.0})
    assert r.status_code == 404
