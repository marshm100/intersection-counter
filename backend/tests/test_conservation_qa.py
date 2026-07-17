"""Tests for backend/services/conservation_qa.py (Phase 3).

Synthetic project: two intersections on a N-S corridor, one camera each,
4 cardinal legs, events inserted directly. Volumes are constructed so each
verdict tier (ok / warn / fail / info) is exercised.
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection
from backend.services.conservation_qa import (
    corridor_consistency, reverse_balance,
)

client = TestClient(app)


def _mk_intersection(pid, name, sort_order):
    conn = get_connection(pid)
    with conn:
        cur = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES (?, '2026-06-12', ?, 4, '2026-06-12')", (name, sort_order))
        iid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, ?, 0, '2026-06-12')", (iid, name))
        cid = cur.lastrowid
        # `legs` is keyed by each leg's travel-INTENT (N/S/E/W) so the event
        # cells and assertions below read naturally as NB/SB/EB/WB. Per the
        # project convention a leg's stored cardinal is its POSITION — the
        # OPPOSITE of the travel direction — so an NB approach (from the south
        # arm) stores cardinal 'S'. bound_approach() turns it back into "NB".
        _OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}
        legs = {}
        for card, (x, y) in {"N": (320, 460), "S": (320, 20),
                             "E": (20, 240), "W": (620, 240)}.items():
            cur = conn.execute(
                "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
                "origin_zone, reference_heading) VALUES (?, ?, ?, 0, ?, 0)",
                (cid, f"{card} leg", _OPP[card], json.dumps([[x, y]])))
            legs[card] = cur.lastrowid
    conn.close()
    return iid, cid, legs


def _add_events(pid, cid, legs, cells, t0=0.0, window=1800.0):
    """cells: {(origin_card, dest_card): count}. timestamps spread over window."""
    conn = get_connection(pid)
    total = sum(cells.values()) or 1
    i = 0
    with conn:
        for (a, b), n in cells.items():
            for _ in range(n):
                ts = t0 + window * i / total
                conn.execute(
                    "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                    "origin_leg_id, destination_leg_id, movement, trajectory_data, "
                    "trajectory_confidence, vehicle_class, detection_confidence, "
                    "timestamp_video, frame_number) "
                    "VALUES (?, ?, ?, ?, 'through', '[]', 1.0, 'car', 0.9, ?, ?)",
                    (cid, i, legs[a], legs[b], ts, int(ts * 10)))
                i += 1
    conn.close()


@pytest.fixture()
def corridor_project():
    r = client.post("/api/projects", json={"name": "qa-test"})
    pid = r.json()["project_id"]
    south = _mk_intersection(pid, "South Int", 0)
    north = _mk_intersection(pid, "North Int", 1)
    yield pid, south, north
    client.delete(f"/api/projects/{pid}")


class TestReverseBalance:
    def test_short_window_is_informational(self, corridor_project):
        pid, (iid, cid, legs), _ = corridor_project
        _add_events(pid, cid, legs, {("N", "S"): 100, ("S", "N"): 40}, window=1800)
        r = reverse_balance(pid, iid)
        assert r["applicable"] is False
        assert all(p["verdict"] == "info" for p in r["pairs"])

    def test_long_window_verdicts(self, corridor_project):
        pid, (iid, cid, legs), _ = corridor_project
        _add_events(pid, cid, legs, {
            ("N", "S"): 500, ("S", "N"): 480,   # imb 0.04 -> ok
            ("N", "E"): 100, ("E", "N"): 60,    # imb 0.40 -> warn (left vs right)
            ("E", "S"): 90,  ("S", "E"): 30,    # imb 0.67 -> fail
        }, window=12 * 3600)
        r = reverse_balance(pid, iid)
        assert r["applicable"] is True
        verdicts = {p["movement"]: p["verdict"] for p in r["pairs"]}
        assert verdicts["NB through"] == "ok"
        assert verdicts["NB left"] == "warn"
        assert verdicts["EB left"] == "fail"

    def test_tiny_cells_ignored(self, corridor_project):
        pid, (iid, cid, legs), _ = corridor_project
        _add_events(pid, cid, legs, {("N", "W"): 5, ("W", "N"): 1}, window=12 * 3600)
        r = reverse_balance(pid, iid)
        assert r["pairs"] == []   # below MIN_CELL_VOLUME


class TestCorridorConsistency:
    def test_conserving_link_ok(self, corridor_project):
        pid, (iid_s, cid_s, legs_s), (iid_n, cid_n, legs_n) = corridor_project
        # 200 vehicles northbound through both; 150 southbound through both.
        _add_events(pid, cid_s, legs_s, {("N", "S"): 200, ("S", "N"): 150})
        _add_events(pid, cid_n, legs_n, {("N", "S"): 205, ("S", "N"): 148})
        cc = corridor_consistency(pid, [iid_s, iid_n])
        assert all(l["verdict"] == "ok" for l in cc["links"])

    def test_leaky_link_flags(self, corridor_project):
        pid, (iid_s, cid_s, legs_s), (iid_n, cid_n, legs_n) = corridor_project
        _add_events(pid, cid_s, legs_s, {("N", "S"): 200})   # sends 200 north
        _add_events(pid, cid_n, legs_n, {("N", "S"): 120})   # receives only 120
        cc = corridor_consistency(pid, [iid_s, iid_n])
        nb = [l for l in cc["links"] if "Nbound" in l["link"]][0]
        assert nb["sent"] == 200 and nb["received"] == 120
        assert nb["verdict"] == "fail"

    def test_low_volume_link_is_info(self, corridor_project):
        pid, (iid_s, cid_s, legs_s), (iid_n, cid_n, legs_n) = corridor_project
        _add_events(pid, cid_s, legs_s, {("N", "S"): 10})
        _add_events(pid, cid_n, legs_n, {("N", "S"): 4})
        cc = corridor_consistency(pid, [iid_s, iid_n])
        nb = [l for l in cc["links"] if "Nbound" in l["link"]][0]
        assert nb["verdict"] == "info"

    def test_turns_feed_directional_io(self, corridor_project):
        pid, (iid_s, cid_s, legs_s), (iid_n, cid_n, legs_n) = corridor_project
        # 100 enter the corridor at South via an EB right turn (E->N exits
        # north? E->N is a right that exits via the N-approach road = SOUTH).
        # Use E->S (left, exits via S-approach road = NORTH side) instead:
        _add_events(pid, cid_s, legs_s, {("E", "S"): 100})    # turn onto corridor, heading north
        _add_events(pid, cid_n, legs_n, {("N", "S"): 95})     # arrives at North as NB through
        cc = corridor_consistency(pid, [iid_s, iid_n])
        nb = [l for l in cc["links"] if "Nbound" in l["link"]][0]
        assert nb["sent"] == 100 and nb["received"] == 95
        assert nb["verdict"] == "ok"
