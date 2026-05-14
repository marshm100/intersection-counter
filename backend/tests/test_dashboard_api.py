"""Tests for the dashboard router API (Step 6)."""

import sys
from unittest.mock import MagicMock

import pytest

for _mod in ("cv2", "numpy", "ultralytics", "supervision", "scipy", "sklearn"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.database import get_connection, set_project_info  # noqa: E402

client = TestClient(app)

PROJECT_ID = "test-dashboard-project"


def _setup(interval_minutes: int | None = None):
    conn = get_connection(PROJECT_ID)
    conn.execute("DELETE FROM vehicle_events")
    conn.execute("DELETE FROM legs")
    conn.execute("DELETE FROM project_info")
    conn.commit()
    conn.close()
    if interval_minutes is not None:
        set_project_info(PROJECT_ID, "interval_minutes", str(interval_minutes))


def _insert_leg(conn, label: str, sort_order: int) -> int:
    cur = conn.execute(
        "INSERT INTO legs (label, cardinal_direction, sort_order, origin_zone, reference_heading) VALUES (?, ?, ?, ?, ?)",
        (label, "N", sort_order, "[[0,0]]", 0.0),
    )
    conn.commit()
    return cur.lastrowid


def _insert_vehicle_event(conn, origin_leg_id: int, movement: str, timestamp_video: float):
    conn.execute(
        "INSERT INTO vehicle_events (vehicle_track_id, origin_leg_id, movement, trajectory_data, "
        "trajectory_confidence, vehicle_class, detection_confidence, timestamp_video, frame_number) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, origin_leg_id, movement, "[]", 0.9, "car", 0.8, timestamp_video, 1),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 1. Empty — no events
# ---------------------------------------------------------------------------

def test_dashboard_empty():
    _setup()
    r = client.get(f"/api/projects/{PROJECT_ID}/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["tmc_matrix"] == []
    assert body["time_series"] == []
    assert body["totals"] == {"vehicles": 0}


# ---------------------------------------------------------------------------
# 2. TMC matrix
# ---------------------------------------------------------------------------

def test_dashboard_tmc_matrix():
    _setup()
    conn = get_connection(PROJECT_ID)
    leg_id = _insert_leg(conn, "North", 1)
    _insert_vehicle_event(conn, leg_id, "through", 0.0)
    _insert_vehicle_event(conn, leg_id, "through", 1.0)
    _insert_vehicle_event(conn, leg_id, "left", 2.0)
    conn.close()

    r = client.get(f"/api/projects/{PROJECT_ID}/dashboard")
    assert r.status_code == 200
    matrix = r.json()["tmc_matrix"]
    assert len(matrix) == 1
    row = matrix[0]
    assert row["leg_label"] == "North"
    assert row["through"] == 2
    assert row["left"] == 1
    assert row["total"] == 3


# ---------------------------------------------------------------------------
# 3. Time series buckets
# ---------------------------------------------------------------------------

def test_dashboard_time_series():
    _setup(interval_minutes=15)
    conn = get_connection(PROJECT_ID)
    leg_id = _insert_leg(conn, "North", 1)
    _insert_vehicle_event(conn, leg_id, "through", 0.0)    # bucket 0
    _insert_vehicle_event(conn, leg_id, "through", 900.0)  # bucket 1 (15 min = 900s)
    conn.close()

    r = client.get(f"/api/projects/{PROJECT_ID}/dashboard")
    assert r.status_code == 200
    ts = r.json()["time_series"]
    assert len(ts) == 2
    assert ts[0]["vehicle_count"] == 1
    assert ts[1]["vehicle_count"] == 1


# ---------------------------------------------------------------------------
# 4. Totals
# ---------------------------------------------------------------------------

def test_dashboard_totals():
    _setup()
    conn = get_connection(PROJECT_ID)
    leg_id = _insert_leg(conn, "North", 1)
    for _ in range(5):
        _insert_vehicle_event(conn, leg_id, "through", 0.0)
    conn.close()

    r = client.get(f"/api/projects/{PROJECT_ID}/dashboard")
    assert r.status_code == 200
    totals = r.json()["totals"]
    assert totals["vehicles"] == 5


# ---------------------------------------------------------------------------
# 5. Interval from project_info
# ---------------------------------------------------------------------------

def test_dashboard_interval_from_project_info():
    _setup(interval_minutes=5)
    r = client.get(f"/api/projects/{PROJECT_ID}/dashboard")
    assert r.status_code == 200
    assert r.json()["interval_minutes"] == 5


# ---------------------------------------------------------------------------
# 6. Multiple legs
# ---------------------------------------------------------------------------

def test_dashboard_multiple_legs():
    _setup()
    conn = get_connection(PROJECT_ID)
    leg1 = _insert_leg(conn, "North", 1)
    leg2 = _insert_leg(conn, "South", 2)
    _insert_vehicle_event(conn, leg1, "through", 0.0)
    _insert_vehicle_event(conn, leg2, "left", 0.0)
    conn.close()

    r = client.get(f"/api/projects/{PROJECT_ID}/dashboard")
    assert r.status_code == 200
    matrix = r.json()["tmc_matrix"]
    assert len(matrix) == 2
    labels = {row["leg_label"] for row in matrix}
    assert labels == {"North", "South"}
