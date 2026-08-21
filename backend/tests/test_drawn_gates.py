"""Operator-drawn gate lines (B1, 2026-08-21 one-system plan).

The G-PF2-1 negative isolated derived gates as the accuracy cap (a 94 px
stub zeroed a 379-vehicle movement). These tests pin the drawn-gate
contract: verbatim endpoints, draw-order-independent inward normal,
precedence over every derived source, byte-parity when absent
(OFF-parity lock), de-overlap safety, and the parser + persistence
semantics (a gate-only edit must never wipe counted events)."""
import os
import shutil
import tempfile

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services.entry_gates import (
    build_gates, classify, parse_gate_segment,
)

client = TestClient(app)

LEGS = {1: (50.0, 0.0), 2: (100.0, 50.0), 3: (50.0, 100.0), 4: (0.0, 50.0)}
PATHS = [{"origin_leg_id": 1, "destination_leg_id": 3,
          "polyline": [[50, -20], [50, 120]]},
         {"origin_leg_id": 4, "destination_leg_id": 2,
          "polyline": [[-20, 50], [120, 50]]}]
HEAD = {1: 180.0, 2: 270.0, 3: 0.0, 4: 90.0}


class TestParseGateSegment:
    def test_json_string_and_list_forms(self):
        want = ((10.0, 20.0), (110.0, 20.0))
        assert parse_gate_segment("[[10, 20], [110, 20]]") == want
        assert parse_gate_segment([[10, 20], [110, 20]]) == want

    def test_malformed_is_none_never_raises(self):
        assert parse_gate_segment(None) is None
        assert parse_gate_segment("not json") is None
        assert parse_gate_segment("[[1, 2]]") is None
        assert parse_gate_segment([[1, 2], [3, 4], [5, 6]]) is None
        assert parse_gate_segment([[1], [2, 3]]) is None


class TestDrawnGates:
    def test_verbatim_endpoints_and_inward_normal(self):
        drawn = {1: ((10.0, 5.0), (90.0, 5.0))}
        gates = build_gates(LEGS, PATHS, HEAD, leg_gates=drawn)
        p1, p2, inw = gates[1]
        assert p1 == (10.0, 5.0) and p2 == (90.0, 5.0)
        # centroid is below leg 1 -> inward normal points +y
        assert inw[1] > 0.9

    def test_inward_independent_of_draw_order(self):
        g_ab = build_gates(LEGS, PATHS, HEAD,
                           leg_gates={1: ((10.0, 5.0), (90.0, 5.0))})[1]
        g_ba = build_gates(LEGS, PATHS, HEAD,
                           leg_gates={1: ((90.0, 5.0), (10.0, 5.0))})[1]
        assert g_ab[2] == pytest.approx(g_ba[2])

    def test_precedence_over_leg_axes(self):
        # a wild axis would rotate the derived gate; the drawn segment
        # must ignore it entirely
        drawn = {1: ((10.0, 5.0), (90.0, 5.0))}
        axes = {1: (0.7071, 0.7071)}
        gates = build_gates(LEGS, PATHS, HEAD, leg_axes=axes,
                            leg_gates=drawn)
        assert gates[1][0] == (10.0, 5.0)
        assert gates[1][1] == (90.0, 5.0)

    def test_absent_legs_byte_identical(self):
        base = build_gates(LEGS, PATHS, HEAD)
        mixed = build_gates(LEGS, PATHS, HEAD,
                            leg_gates={1: ((10.0, 5.0), (90.0, 5.0))})
        for leg in (2, 3, 4):
            assert mixed[leg] == base[leg]
        empty = build_gates(LEGS, PATHS, HEAD, leg_gates={})
        assert empty == base

    def test_wide_drawn_gate_completes_journeys_the_stub_missed(self):
        # The G-PF2-1 mechanism in miniature: a narrow derived-style gate
        # at leg 2 misses a track exiting near the mouth's edge; the
        # operator's full-span drawn gate catches it.
        narrow = {2: ((100.0, 40.0), (100.0, 60.0))}
        wide = {2: ((100.0, 5.0), (100.0, 95.0))}
        # enters leg 1 heading S, curves E, exits at y=80 (outside the
        # narrow 40-60 span, inside the wide one)
        track = ([(f, 50.0, -10.0 + 10.0 * f) for f in range(5)]
                 + [(5 + f, 50.0 + 12.0 * f, 40.0 + 10.0 * f)
                    for f in range(6)])
        g_narrow = build_gates(LEGS, PATHS, HEAD, leg_gates=narrow)
        g_wide = build_gates(LEGS, PATHS, HEAD, leg_gates=wide)
        *_n, tag_narrow = classify(track, g_narrow, fps=10.0)
        o, d, *_w, tag_wide = classify(track, g_wide, fps=10.0)
        assert tag_narrow == "entry_only"
        assert (o, d, tag_wide) == (1, 2, "full")

    def test_crossing_drawn_gates_de_overlapped(self):
        # two drawn gates that cross get the 8 px pull-back
        drawn = {1: ((50.0, -40.0), (50.0, 40.0)),   # runs down into box
                 4: ((-40.0, 0.0), (40.0, 0.0))}     # runs right, crosses
        gates = build_gates(LEGS, PATHS, HEAD, leg_gates=drawn)
        (a1, a2, _), (b1, b2, _) = gates[1], gates[4]
        from backend.services.entry_gates import _seg_cross
        assert _seg_cross(a1, a2, b1, b2) is None


@pytest.fixture()
def project_with_one_camera():
    r = client.post("/api/projects", json={"name": "b1-gates-test"})
    pid = r.json()["project_id"]
    tmpdir = tempfile.mkdtemp(prefix="b1_gates_")
    try:
        p = os.path.join(tmpdir, "Cam1_01_20260514_080000 Main St.mp4")
        w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 30.0,
                            (320, 240))
        for _ in range(15):
            w.write(np.zeros((240, 320, 3), dtype=np.uint8))
        w.release()
        client.post(f"/api/projects/{pid}/videos/bulk", json={"paths": [p]})
        body = client.post(f"/api/projects/{pid}/videos/save-labels").json()
        iid = body["intersections"][0]["intersection_id"]
        cam_id = client.get(
            f"/api/projects/{pid}/intersections/{iid}/cameras"
        ).json()[0]["camera_id"]
        yield pid, cam_id
    finally:
        client.delete(f"/api/projects/{pid}")
        shutil.rmtree(tmpdir, ignore_errors=True)


def _legs_payload(gate=None):
    return {"legs": [
        {"label": "N", "cardinal_direction": "N", "sort_order": 0,
         "origin_zone": [[50, 10]], "reference_heading": 180.0,
         **({"gate_segment": gate} if gate else {})},
        {"label": "S", "cardinal_direction": "S", "sort_order": 1,
         "origin_zone": [[50, 200]], "reference_heading": 0.0},
    ]}


class TestGateSegmentPersistence:
    def test_gate_only_edit_rides_safe_branch(self, project_with_one_camera):
        pid, cid = project_with_one_camera
        base = f"/api/projects/{pid}/cameras/{cid}/calibration/legs"
        r = client.put(base, json=_legs_payload())
        assert r.status_code == 200
        lid = r.json()["legs"][0]["leg_id"]
        # counted event referencing the leg must survive a gate-only edit
        from backend.database import get_connection
        conn = get_connection(pid)
        with conn:
            conn.execute(
                "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                "origin_leg_id, movement, trajectory_data, "
                "trajectory_confidence, vehicle_class, "
                "detection_confidence, timestamp_video, frame_number) "
                "VALUES (?, 1, ?, 'through', '[]', 1.0, 'car', 0.9, "
                "1.0, 1)", (cid, lid))
        conn.close()
        r = client.put(base, json=_legs_payload(gate=[[10, 5], [90, 5]]))
        assert r.status_code == 200
        legs = r.json()["legs"]
        assert legs[0]["leg_id"] == lid            # same leg_id = safe branch
        assert legs[0]["gate_segment"] == [[10, 5], [90, 5]]
        assert legs[1]["gate_segment"] is None
        conn = get_connection(pid)
        n = conn.execute("SELECT COUNT(1) FROM vehicle_events "
                         "WHERE camera_id=?", (cid,)).fetchone()[0]
        conn.close()
        assert n == 1                              # events survived

    def test_get_echoes_gate_segment(self, project_with_one_camera):
        pid, cid = project_with_one_camera
        base = f"/api/projects/{pid}/cameras/{cid}/calibration/legs"
        client.put(base, json=_legs_payload(gate=[[10, 5], [90, 5]]))
        r = client.get(f"/api/projects/{pid}/cameras/{cid}/calibration")
        assert r.json()["legs"][0]["gate_segment"] == [[10, 5], [90, 5]]

    def test_moved_mouth_still_wipes(self, project_with_one_camera):
        pid, cid = project_with_one_camera
        base = f"/api/projects/{pid}/cameras/{cid}/calibration/legs"
        r = client.put(base, json=_legs_payload())
        lid = r.json()["legs"][0]["leg_id"]
        moved = _legs_payload()
        moved["legs"][0]["origin_zone"] = [[80, 10]]
        r = client.put(base, json=moved)
        assert r.status_code == 200
        assert r.json()["legs"][0]["leg_id"] != lid   # destructive branch

    def test_malformed_gate_422(self, project_with_one_camera):
        pid, cid = project_with_one_camera
        base = f"/api/projects/{pid}/cameras/{cid}/calibration/legs"
        r = client.put(base, json=_legs_payload(gate=[[10, 5]]))
        assert r.status_code == 422
        r = client.put(base, json=_legs_payload(gate=[[10, 5], [15, 5]]))
        assert r.status_code == 422                # under 20 px

    def test_fingerprint_changes_on_gate_edit(self, project_with_one_camera):
        pid, cid = project_with_one_camera
        base = f"/api/projects/{pid}/cameras/{cid}/calibration/legs"
        client.put(base, json=_legs_payload())
        from backend.services.two_pass import calib_fingerprint
        fp_before = calib_fingerprint(pid, cid)
        client.put(base, json=_legs_payload(gate=[[10, 5], [90, 5]]))
        assert calib_fingerprint(pid, cid) != fp_before
