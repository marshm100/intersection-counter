"""THE MOUTH FROM MOTION + COUNT ONCE (arm mm, 2026-10-13). The cam2 cases on
the synthetic box (x 0..100, y 0..100; leg 1 top, 2 right, 3 bottom, 4 left):
a car that WAITED in leg 4's queue, a car first seen mid-box moving ALONG the
1->3 lane, a car revealed from behind another, a tie, and one car carrying two
tracks versus a real follower."""
import os
import sqlite3
import tempfile

import pytest

from backend.database import SCHEMA
from backend.services.entry_gates import build_gates
from backend.services.mouth_from_motion import count_once_pass, mouth_from_motion_pass

LEGS = {1: (50.0, 0.0), 2: (100.0, 50.0), 3: (50.0, 100.0), 4: (0.0, 50.0)}
PATHS = [{"origin_leg_id": 1, "destination_leg_id": 3, "polyline": [[50, -20], [50, 120]]},
         {"origin_leg_id": 4, "destination_leg_id": 2, "polyline": [[-20, 50], [120, 50]]}]
HEAD = {1: 180.0, 2: 270.0, 3: 0.0, 4: 90.0}
FPS = 10.0
BOX = 10.0


@pytest.fixture(scope="module")
def gates():
    return build_gates(LEGS, PATHS, HEAD)


def _rows(tid, pts, box=BOX):
    # (tid, frame, cx, cy, w, h): pts give the box centre; the anchor is cy + h/2
    return [(float(tid), float(f), float(x), float(y), box, box) for f, x, y in pts]


def _through(f0, x=30.0):
    """1 -> 3 straight down at 6 px/frame."""
    return [(f0 + i, x, -25.0 + 6.0 * i) for i in range(25)]


def _right_turn(f0, wait_frames=20):
    """4 -> 3: waits at the left mouth, drives right, then turns down."""
    pts = [(f0 + i, -6.0, 65.0) for i in range(wait_frames)]
    f = f0 + wait_frames
    for i in range(12):
        pts.append((f + i, -6.0 + 6.0 * i, 65.0))
    f += 12
    for i in range(10):
        pts.append((f + i, 66.0, 65.0 + 6.0 * i))
    return pts


def _db():
    db = os.path.join(tempfile.mkdtemp(), "p.db")
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    return db


def _ev(db, tid, o, d, mv, tag, cam=2):
    conn = sqlite3.connect(db)
    with conn:
        eid = conn.execute(
            "INSERT INTO vehicle_events (camera_id, vehicle_track_id, origin_leg_id, "
            "destination_leg_id, movement, trajectory_data, trajectory_confidence, "
            "vehicle_class, detection_confidence, timestamp_video, frame_number, "
            "classifier_num_points) VALUES (?, ?, ?, ?, ?, '[[1,2]]', 0.9, 'car', 0.9, "
            "10.0, 100, 10)", (cam, tid, o, d, mv)).lastrowid
        conn.execute("INSERT INTO track_fates (camera_id, vehicle_track_id, disposition, reason, created_at, "
                     "gate_tag, origin_leg_id, destination_leg_id, movement) "
                     "VALUES (?, ?, 'counted', 'counted', '2026-10-13', ?, ?, ?, ?)", (cam, tid, tag, o, d, mv))
    conn.close()
    return eid


def _event(db, eid):
    conn = sqlite3.connect(db)
    r = conn.execute("SELECT origin_leg_id, destination_leg_id, movement, posterior_source, "
                     "COALESCE(rejected,0) FROM vehicle_events WHERE event_id=?", (eid,)).fetchone()
    conn.close()
    return r


def _site(db):
    """Clean (full) journeys that make the two lanes ending at leg 3."""
    rows = []
    for k in range(6):
        tid = 100 + k
        rows += _rows(tid, _through(k * 40))
        _ev(db, tid, 1, 3, "through", "full")
    for k in range(6):
        tid = 200 + k
        rows += _rows(tid, _right_turn(k * 60))
        _ev(db, tid, 4, 3, "right", "full")
    return rows


class TestMouthFromMotion:
    def test_waited_in_the_queue_came_in_by_that_leg(self, gates):
        db = _db(); rows = _site(db)
        # born ON the leg-4 line in its queue, never seen crossing; today guessed leg 1
        pts = [p for p in _right_turn(1000) if p[1] >= -6.0]
        rows += _rows(9, pts)
        eid = _ev(db, 9, 1, 3, "through", "exit_only")
        st = mouth_from_motion_pass(db, 2, rows, FPS, gates)
        assert _event(db, eid)[:4] == (4, 3, "right", "motion_wait")
        assert st["exit_only:changed"] == 1

    def test_moving_along_a_lane_mid_box_takes_that_lane(self, gates):
        db = _db(); rows = _site(db)
        # first seen mid-box (hidden before), moving down the 1->3 lane; today guessed leg 4
        pts = [(2000 + i, 30.0, 35.0 + 6.0 * i) for i in range(12)]
        rows += _rows(9, pts)
        eid = _ev(db, 9, 4, 3, "right", "exit_only")
        mouth_from_motion_pass(db, 2, rows, FPS, gates)
        assert _event(db, eid)[:4] == (1, 3, "through", "motion_lane")

    def test_revealed_from_behind_a_vehicle_takes_its_leg(self, gates):
        db = _db(); rows = _site(db)
        # a counted leg-1 car passes (50, 50); a car appears under it and stands still
        rows += _rows(8, [(3000 + i, 50.0, -25.0 + 6.0 * i) for i in range(25)])
        _ev(db, 8, 1, 3, "through", "full")
        hidden = [(3013 + i, 50.0, 52.0) for i in range(8)]
        rows += _rows(9, hidden)
        eid = _ev(db, 9, 4, 3, "right", "exit_only")
        mouth_from_motion_pass(db, 2, rows, FPS, gates)
        assert _event(db, eid)[:4] == (1, 3, "through", "motion_occluder")

    def test_no_evidence_is_a_tie_left_as_today(self, gates):
        db = _db(); rows = _site(db)
        # stands still on the exit line the whole time: no wait zone, no motion, no occluder
        rows += _rows(9, [(4000 + i, 80.0, 92.0) for i in range(8)])
        eid = _ev(db, 9, 4, 3, "right", "exit_only")
        st = mouth_from_motion_pass(db, 2, rows, FPS, gates)
        assert _event(db, eid) == (4, 3, "right", None, 0)
        assert st["exit_only:tie"] == 1

    def test_apply_false_writes_nothing(self, gates):
        db = _db(); rows = _site(db)
        rows += _rows(9, [(2000 + i, 30.0, 35.0 + 6.0 * i) for i in range(12)])
        eid = _ev(db, 9, 4, 3, "right", "exit_only")
        st = mouth_from_motion_pass(db, 2, rows, FPS, gates, apply=False)
        assert _event(db, eid) == (4, 3, "right", None, 0)
        assert [d["new_o"] for d in st["decisions"] if d["tid"] == 9] == [1]


class TestCountOnce:
    def _lane(self, db):
        """Clean 1->3 cars at varied headways (1.0 .. 3.4 s) give the lane its minimum."""
        rows, f = [], 0
        for k, gap in enumerate([10, 12, 15, 18, 20, 22, 25, 28, 30, 34, 26, 16]):
            rows += _rows(100 + k, _through(f))
            _ev(db, 100 + k, 1, 3, "through", "full")
            f += gap
        return rows

    def test_two_tracks_on_one_car_count_once(self):
        db = _db(); rows = self._lane(db)
        rows += _rows(1, _through(5000)) + _rows(2, _through(5000, x=34.0))
        e1 = _ev(db, 1, 1, 3, "through", "entry_only")
        e2 = _ev(db, 2, 1, 3, "through", "exit_only")
        st = count_once_pass(db, 2, rows, FPS)
        assert st["count_once_rejected"] == 1
        assert sorted([_event(db, e1)[4], _event(db, e2)[4]]) == [0, 1]

    def test_a_follower_is_the_next_car(self):
        db = _db(); rows = self._lane(db)
        rows += _rows(1, _through(5000)) + _rows(2, _through(5015))   # 1.5 s behind
        e1 = _ev(db, 1, 1, 3, "through", "entry_only")
        e2 = _ev(db, 2, 1, 3, "through", "exit_only")
        count_once_pass(db, 2, rows, FPS)
        assert _event(db, e1)[4] == 0 and _event(db, e2)[4] == 0
