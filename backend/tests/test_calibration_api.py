"""Tests for calibration endpoints: GET /calibration and PUT /calibration/legs."""
import json
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection

client = TestClient(app)


def _create_project() -> str:
    r = client.post("/api/projects", json={"name": "calib-test"})
    assert r.status_code == 200
    return r.json()["project_id"]


def _delete_project(pid: str) -> None:
    client.delete(f"/api/projects/{pid}")


# ---------------------------------------------------------------------------


def test_get_calibration_empty():
    pid = _create_project()
    try:
        r = client.get(f"/api/projects/{pid}/calibration")
        assert r.status_code == 200
        assert r.json() == {"legs": []}
    finally:
        _delete_project(pid)


def test_put_and_get_calibration():
    pid = _create_project()
    try:
        legs_payload = [
            {
                "label": "North Approach",
                "cardinal_direction": "N",
                "sort_order": 0,
                "origin_zone": [[100.0, 200.0], [300.0, 200.0]],
                "reference_heading": 0.0,
            },
            {
                "label": "South Approach",
                "cardinal_direction": "S",
                "sort_order": 1,
                "origin_zone": [[100.0, 400.0], [300.0, 400.0]],
                "reference_heading": 180.0,
            },
        ]

        r = client.put(f"/api/projects/{pid}/calibration/legs", json={"legs": legs_payload})
        assert r.status_code == 200
        saved = r.json()["legs"]
        assert len(saved) == 2
        assert saved[0]["label"] == "North Approach"
        assert saved[1]["cardinal_direction"] == "S"
        assert saved[0]["origin_zone"] == [[100.0, 200.0], [300.0, 200.0]]

        # Verify GET returns the same data
        r2 = client.get(f"/api/projects/{pid}/calibration")
        assert r2.status_code == 200
        fetched = r2.json()["legs"]
        assert len(fetched) == 2
        assert fetched[0]["label"] == "North Approach"
        assert fetched[1]["reference_heading"] == 180.0
    finally:
        _delete_project(pid)


def test_put_replaces_existing_legs():
    pid = _create_project()
    try:
        first = [
            {
                "label": "Old Leg",
                "cardinal_direction": "E",
                "sort_order": 0,
                "origin_zone": [[10.0, 10.0], [20.0, 20.0]],
                "reference_heading": 90.0,
            }
        ]
        client.put(f"/api/projects/{pid}/calibration/legs", json={"legs": first})

        second = [
            {
                "label": "New Leg A",
                "cardinal_direction": "N",
                "sort_order": 0,
                "origin_zone": [[0.0, 0.0], [100.0, 0.0]],
                "reference_heading": 0.0,
            },
            {
                "label": "New Leg B",
                "cardinal_direction": "S",
                "sort_order": 1,
                "origin_zone": [[0.0, 200.0], [100.0, 200.0]],
                "reference_heading": 180.0,
            },
        ]
        r = client.put(f"/api/projects/{pid}/calibration/legs", json={"legs": second})
        assert r.status_code == 200
        legs = r.json()["legs"]
        assert len(legs) == 2
        assert legs[0]["label"] == "New Leg A"

        # Verify DB directly
        conn = get_connection(pid)
        try:
            rows = conn.execute("SELECT COUNT(*) FROM legs").fetchone()
            assert rows[0] == 2
        finally:
            conn.close()
    finally:
        _delete_project(pid)


def test_put_empty_legs_returns_422():
    pid = _create_project()
    try:
        r = client.put(f"/api/projects/{pid}/calibration/legs", json={"legs": []})
        assert r.status_code == 422
    finally:
        _delete_project(pid)


def test_origin_zone_stored_as_json():
    pid = _create_project()
    try:
        zone = [[123.4, 567.8], [910.1, 234.5]]
        payload = [
            {
                "label": "Test",
                "cardinal_direction": "W",
                "sort_order": 0,
                "origin_zone": zone,
                "reference_heading": 270.0,
            }
        ]
        client.put(f"/api/projects/{pid}/calibration/legs", json={"legs": payload})

        conn = get_connection(pid)
        try:
            raw = conn.execute("SELECT origin_zone FROM legs").fetchone()[0]
            parsed = json.loads(raw)
            assert parsed == zone
        finally:
            conn.close()
    finally:
        _delete_project(pid)
