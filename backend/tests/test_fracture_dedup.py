"""THE FRACTURE RULE (operator rulings 2026-09-11, cam5 fragment reel):
a detection drop and recapture of the same vehicle is one count; a
re-birth many seconds later at the same queue position is the next
vehicle. docs/plan_basis_2026-09-11.md."""
import os
import sqlite3
import tempfile

import numpy as np
import pytest

import backend.config as cfg
from backend.database import SCHEMA
from backend.services.entry_gates import build_gates
from backend.services.turn_merge import fracture_track_dedup

# the synthetic box from test_conservation: 4 legs, N-S + W-E channels
LEGS = {1: (50.0, 0.0), 2: (100.0, 50.0), 3: (50.0, 100.0), 4: (0.0, 50.0)}
PATHS = [{"origin_leg_id": 1, "destination_leg_id": 3,
          "polyline": [[50, -20], [50, 120]]},
         {"origin_leg_id": 4, "destination_leg_id": 2,
          "polyline": [[-20, 50], [120, 50]]}]
HEAD = {1: 180.0, 2: 270.0, 3: 0.0, 4: 90.0}
FPS = 10.0
BOX = 10.0


@pytest.fixture(scope="module")
def gates():
    return build_gates(LEGS, PATHS, HEAD)


def _rows(tid, pts, box=BOX):
    return [(float(tid), f, x, y, box, box) for f, x, y in pts]


def _mk_db():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "p.db")
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.commit(); conn.close()
    return db


def _ev(db, tid, cam=2):
    conn = sqlite3.connect(db)
    with conn:
        eid = conn.execute(
            "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
            "origin_leg_id, destination_leg_id, movement, trajectory_data, "
            "trajectory_confidence, vehicle_class, detection_confidence, "
            "timestamp_video, frame_number, classifier_num_points) "
            "VALUES (?, ?, 1, 3, 'through', '[[1,2]]', 0.9, 'car', 0.9, "
            "10.0, 100, 10)", (cam, tid)).lastrowid
    conn.close()
    return eid


def _kept(db):
    conn = sqlite3.connect(db)
    rows = {r[0] for r in conn.execute(
        "SELECT event_id FROM vehicle_events WHERE COALESCE(rejected,0)=0")}
    conn.close()
    return rows


# A: enters gate 1 (x=50, y -5..49 at 6 px/frame), dies mid-box moving
A = [(float(f), 50.0, -5.0 + 6.0 * f) for f in range(10)]
# B: the recapture, born 2 frames (0.2 s) after A dies, 3 px on, exits gate 3
B = [(12.0 + f, 50.0, 52.0 + 6.0 * f) for f in range(12)]


class TestFractureRule:
    def test_drop_and_recapture_counts_once(self, gates):
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = fracture_track_dedup(db, 2, _rows(1, A) + _rows(2, B), FPS, gates)
        assert st["fracture_pairs"] == 1 and _kept(db) == {eb}   # shorter A yields

    def test_rebirth_seconds_later_is_the_next_vehicle(self, gates):
        # same spot, 3 s later: clips 3-5, two vehicles
        late = [(f + 28.0, x, y) for f, x, y in B]
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = fracture_track_dedup(db, 2, _rows(1, A) + _rows(2, late), FPS, gates)
        assert st["fracture_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_rebirth_two_boxes_away_untouched(self, gates):
        far = [(f, x + 2.5 * BOX, y) for f, x, y in B]
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = fracture_track_dedup(db, 2, _rows(1, A) + _rows(2, far), FPS, gates)
        assert st["fracture_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_box_units_not_pixels(self, gates, monkeypatch):
        # the same 25 px offset is 2.5 boxes at 10 px (refused) and 0.5 box
        # at 50 px (admitted): the far field and the near field share a test
        far = [(f, x + 25.0, y) for f, x, y in B]
        db = _mk_db(); _ev(db, 1), _ev(db, 2)
        st = fracture_track_dedup(db, 2, _rows(1, A, 50.0) + _rows(2, far, 50.0), FPS, gates)
        assert st["fracture_pairs"] == 1

    def test_earlier_half_with_its_exit_never_pairs(self, gates):
        # A is a FULL journey (exits gate 3); a track born right behind it
        # is a follower, not a recapture
        full = [(float(f), 50.0, -5.0 + 6.0 * f) for f in range(20)]     # y to 109
        follower = [(22.0 + f, 50.0, 108.0 + 6.0 * f) for f in range(6)]
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = fracture_track_dedup(db, 2, _rows(1, full) + _rows(2, follower), FPS, gates)
        assert st["fracture_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_opposite_heading_untouched(self, gates):
        # born at A's death point but travelling back the way A came
        back = [(12.0 + f, 50.0, 52.0 - 6.0 * f) for f in range(8)]
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = fracture_track_dedup(db, 2, _rows(1, A) + _rows(2, back), FPS, gates)
        assert st["fracture_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_partner_without_an_event_is_no_duplicate(self, gates):
        db = _mk_db(); ea = _ev(db, 1)
        st = fracture_track_dedup(db, 2, _rows(1, A) + _rows(2, B), FPS, gates)
        assert st["fracture_pairs"] == 0 and _kept(db) == {ea}

    def test_each_track_in_at_most_one_pair(self, gates):
        # two recaptures born at A's death: only the nearer pairs, one reject
        b2 = [(f + 1.0, x, y + 4.0) for f, x, y in B]
        db = _mk_db(); ea, eb, eb2 = _ev(db, 1), _ev(db, 2), _ev(db, 3)
        st = fracture_track_dedup(db, 2, _rows(1, A) + _rows(2, B) + _rows(3, b2), FPS, gates)
        assert st["fracture_rejected"] == 1 and eb in _kept(db) and eb2 in _kept(db)

    def test_other_camera_untouched(self, gates):
        db = _mk_db(); ea, eb = _ev(db, 1, cam=3), _ev(db, 2, cam=3)
        st = fracture_track_dedup(db, 2, _rows(1, A) + _rows(2, B), FPS, gates)
        assert st["fracture_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_default_off(self):
        assert cfg.FRACTURE_DEDUP is False
        assert cfg.FRACTURE_GAP_S == 1.0 and cfg.FRACTURE_DIST_BOXES == 1.0
