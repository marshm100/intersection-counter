"""THE PREDICTED-CONTINUATION RULE (arm pc1, 2026-09-25): a fragment
lacking its exit whose counted continuation is born where the fragment
would be by then is one vehicle; a track born where the fragment DIED,
seconds later or behind the prediction, is the next vehicle.
docs/plan_basis_2026-09-11.md."""
import os
import sqlite3
import tempfile

import pytest

import backend.config as cfg
from backend.database import SCHEMA
from backend.services.entry_gates import build_gates
from backend.services.turn_merge import (continuation_dedup,
                                         fracture_track_dedup)

# the synthetic box from test_fracture_dedup: 4 legs, N-S + W-E channels
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


def _ev(db, tid, cam=2, origin=1):
    conn = sqlite3.connect(db)
    with conn:
        eid = conn.execute(
            "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
            "origin_leg_id, destination_leg_id, movement, trajectory_data, "
            "trajectory_confidence, vehicle_class, detection_confidence, "
            "timestamp_video, frame_number, classifier_num_points) "
            "VALUES (?, ?, ?, 3, 'through', '[[1,2]]', 0.9, 'car', 0.9, "
            "10.0, 100, 10)", (cam, tid, origin)).lastrowid
    conn.close()
    return eid


def _kept(db):
    conn = sqlite3.connect(db)
    rows = {r[0] for r in conn.execute(
        "SELECT event_id FROM vehicle_events WHERE COALESCE(rejected,0)=0")}
    conn.close()
    return rows


# A: enters gate 1 at 2 px/frame, dies mid-box at frame 29, y = 53
A = [(float(f), 50.0, -5.0 + 2.0 * f) for f in range(30)]
# B: born 1.5 s later ON A's predicted spot (53 + 2 x 15 = 83), exits gate 3.
# 30 px = 3 boxes from A's death and 1.5 s after it: the fracture rule's
# 1.0 s / 1.0 box window misses this pair.
B = [(44.0 + f, 50.0, 83.0 + 2.0 * f) for f in range(20)]


class TestContinuationRule:
    def test_predicted_continuation_counts_once(self, gates):
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = continuation_dedup(db, 2, _rows(1, A) + _rows(2, B), FPS, gates)
        assert st["continuation_pairs"] == 1 and _kept(db) == {eb}

    def test_fracture_rule_misses_the_same_pair(self, gates):
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = fracture_track_dedup(db, 2, _rows(1, A) + _rows(2, B), FPS, gates)
        assert st["fracture_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_follower_born_behind_the_prediction_untouched(self, gates):
        # born where A DIED, 1.5 s later: 3 boxes short of where A would be
        behind = [(44.0 + f, 50.0, 53.0 + 2.0 * f) for f in range(30)]
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = continuation_dedup(db, 2, _rows(1, A) + _rows(2, behind), FPS, gates)
        assert st["continuation_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_birth_past_the_moving_break_window_untouched(self, gates):
        # 3.5 s later, on the (extrapolated) spot: the next vehicle
        late = [(64.0 + f, 50.0, 53.0 + 2.0 * 35 + 2.0 * f) for f in range(10)]
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = continuation_dedup(db, 2, _rows(1, A) + _rows(2, late), FPS, gates)
        assert st["continuation_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_fragment_with_its_exit_never_yields(self, gates):
        full = [(float(f), 50.0, -5.0 + 6.0 * f) for f in range(20)]     # y to 109
        after = [(22.0 + f, 50.0, 121.0 + 6.0 * f) for f in range(6)]
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = continuation_dedup(db, 2, _rows(1, full) + _rows(2, after), FPS, gates)
        assert st["continuation_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_origin_mismatch_untouched(self, gates):
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2, origin=4)
        st = continuation_dedup(db, 2, _rows(1, A) + _rows(2, B), FPS, gates)
        assert st["continuation_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_opposite_heading_untouched(self, gates):
        back = [(44.0 + f, 50.0, 83.0 - 2.0 * f) for f in range(20)]
        db = _mk_db(); ea, eb = _ev(db, 1), _ev(db, 2)
        st = continuation_dedup(db, 2, _rows(1, A) + _rows(2, back), FPS, gates)
        assert st["continuation_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_partner_without_an_event_is_no_duplicate(self, gates):
        db = _mk_db(); ea = _ev(db, 1)
        st = continuation_dedup(db, 2, _rows(1, A) + _rows(2, B), FPS, gates)
        assert st["continuation_pairs"] == 0 and _kept(db) == {ea}

    def test_each_track_in_at_most_one_pair(self, gates):
        b2 = [(f + 1.0, x, y + 3.0) for f, x, y in B]
        db = _mk_db(); ea, eb, eb2 = _ev(db, 1), _ev(db, 2), _ev(db, 3)
        st = continuation_dedup(db, 2, _rows(1, A) + _rows(2, B) + _rows(3, b2),
                                FPS, gates)
        assert st["continuation_rejected"] == 1 and _kept(db) == {eb, eb2}

    def test_box_units_not_pixels(self, gates):
        # 20 px off the prediction: 2 boxes at 10 px (refused), 0.4 box at
        # 50 px (admitted) - the tracker's recovery-reach semantics
        off = [(f, x + 20.0, y) for f, x, y in B]
        db = _mk_db(); _ev(db, 1), _ev(db, 2)
        st = continuation_dedup(db, 2, _rows(1, A) + _rows(2, off), FPS, gates)
        assert st["continuation_pairs"] == 0
        db = _mk_db(); _ev(db, 1), _ev(db, 2)
        st = continuation_dedup(db, 2, _rows(1, A, 50.0) + _rows(2, off, 50.0),
                                FPS, gates)
        assert st["continuation_pairs"] == 1

    def test_other_camera_untouched(self, gates):
        db = _mk_db(); ea, eb = _ev(db, 1, cam=3), _ev(db, 2, cam=3)
        st = continuation_dedup(db, 2, _rows(1, A) + _rows(2, B), FPS, gates)
        assert st["continuation_pairs"] == 0 and _kept(db) == {ea, eb}

    def test_default_off_and_no_new_constants(self):
        assert cfg.CONTINUATION_DEDUP is False
        from backend.services.track_chains import STITCH_MOVE_GAP_S
        assert cfg.TRACKER_RECOVERY_REACH == 0.9
        assert STITCH_MOVE_GAP_S == (-0.48, 3.0)
