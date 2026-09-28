"""THE BOUND-CHAIN CONSERVATION GUARD (config.BOUND_CHAIN_CONSERVE,
2026-09-20, iteration 2 of the G-EX cycle).

G-EX-2 counts a track whose EXIT was observed. On a fragmenting camera that
track is often the TAIL HALF of a vehicle whose head half — witnessed
entering, never exiting — was already counted, so the vehicle lands twice.
Arm gx1 failed the G-DEF-1 letter on cam1 (-5.20) and cam3 (-1.20) for
exactly that reason while gaining +15.20 on cam4, which does not fragment.

Scaffolding reused verbatim from test_fracture_dedup.py — the same synthetic
box, gates fixture, row builder and DB helpers.
"""
import os
import sqlite3
import tempfile

import pytest

import backend.config as cfg
from backend.database import SCHEMA
from backend.services import track_chains
from backend.services.entry_gates import build_gates
from backend.services.turn_merge import bound_chain_dedup

# the synthetic box from test_fracture_dedup / test_conservation
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


def _ev(db, tid, cam=2, source=None):
    conn = sqlite3.connect(db)
    with conn:
        eid = conn.execute(
            "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
            "origin_leg_id, destination_leg_id, movement, trajectory_data, "
            "trajectory_confidence, vehicle_class, detection_confidence, "
            "timestamp_video, frame_number, classifier_num_points, "
            "posterior_source) "
            "VALUES (?, ?, 1, 3, 'through', '[[1,2]]', 0.9, 'car', 0.9, "
            "10.0, 100, 10, ?)", (cam, tid, source)).lastrowid
    conn.close()
    return eid


def _kept(db):
    conn = sqlite3.connect(db)
    rows = {r[0] for r in conn.execute(
        "SELECT event_id FROM vehicle_events WHERE COALESCE(rejected,0)=0")}
    conn.close()
    return rows


# HEAD: enters over gate 1 (x=50, y -5..49 at 6 px/frame) and dies mid-box
# still moving — witnessed entry, no exit.
HEAD_PTS = [(float(f), 50.0, -5.0 + 6.0 * f) for f in range(10)]
# TAIL: born 2 frames (0.2 s) after the head dies, 3 px on, carries out over
# gate 3 — witnessed exit, no entry. One vehicle, two halves.
TAIL_PTS = [(12.0 + f, 50.0, 52.0 + 6.0 * f) for f in range(12)]
# A LONE tail far away in time: nothing for it to continue.
LONE_PTS = [(400.0 + f, 50.0, 52.0 + 6.0 * f) for f in range(12)]


class TestBoundChainGuard:
    def test_rejects_the_tail_when_the_head_is_already_counted(self, gates):
        """The defect in one test: the head was counted from its witnessed
        entry, G-EX-2 bound the tail from its witnessed exit, and the vehicle
        landed twice. The tail yields."""
        db = _mk_db()
        head = _ev(db, 1)
        tail = _ev(db, 2, source="rescue_exit")
        st = bound_chain_dedup(db, 2, _rows(1, HEAD_PTS) + _rows(2, TAIL_PTS),
                               FPS, gates)
        assert st["bound_events"] == 1
        assert st["bound_rejected"] == 1
        assert _kept(db) == {head}          # the head survives, not the tail
        assert tail not in _kept(db)

    def test_a_bound_event_with_no_partner_survives(self, gates):
        """Nothing to continue — this is a vehicle we genuinely never counted,
        which is the whole point of G-EX-2."""
        db = _mk_db()
        lone = _ev(db, 2, source="rescue_exit")
        st = bound_chain_dedup(db, 2, _rows(2, LONE_PTS), FPS, gates)
        assert st["bound_rejected"] == 0
        assert _kept(db) == {lone}

    def test_a_partner_that_carries_no_event_does_not_reject(self, gates):
        """The head half exists in the dump but was itself dropped. Nothing
        was double counted, so the tail must still count."""
        db = _mk_db()
        tail = _ev(db, 2, source="rescue_exit")     # head track 1 has no event
        st = bound_chain_dedup(db, 2, _rows(1, HEAD_PTS) + _rows(2, TAIL_PTS),
                               FPS, gates)
        assert st["bound_rejected"] == 0
        assert _kept(db) == {tail}

    def test_never_rejects_a_legacy_event(self, gates):
        """THE SCOPE RESTRICTION, asserted directly. Flip the sources: the
        LATER half is the ordinary event and the earlier one is bound. Only a
        rescue_exit row may ever be rejected, so the legacy row is untouchable
        no matter where it sits in the chain."""
        db = _mk_db()
        head = _ev(db, 1, source="rescue_exit")
        tail = _ev(db, 2)                            # legacy, later in the chain
        st = bound_chain_dedup(db, 2, _rows(1, HEAD_PTS) + _rows(2, TAIL_PTS),
                               FPS, gates)
        assert tail in _kept(db)
        assert st["bound_rejected"] <= 1
        # and whatever it dropped, it was not the legacy event
        conn = sqlite3.connect(db)
        dropped = {r[0] for r in conn.execute(
            "SELECT event_id FROM vehicle_events WHERE rejected = 1")}
        srcs = {r[0] for r in conn.execute(
            "SELECT COALESCE(posterior_source,'') FROM vehicle_events "
            "WHERE rejected = 1")}
        conn.close()
        assert head not in _kept(db) or not dropped
        assert srcs <= {"rescue_exit"}

    def test_other_cameras_are_untouched(self, gates):
        db = _mk_db()
        head = _ev(db, 1, cam=7)
        tail = _ev(db, 2, cam=7, source="rescue_exit")
        st = bound_chain_dedup(db, 2, _rows(1, HEAD_PTS) + _rows(2, TAIL_PTS),
                               FPS, gates)
        assert st["bound_events"] == 0 and st["bound_rejected"] == 0
        assert _kept(db) == {head, tail}

    def test_no_bound_events_is_a_no_op(self, gates):
        """Inert unless GATE_EXIT_ONLY_BINDING produced something to guard."""
        db = _mk_db()
        head, tail = _ev(db, 1), _ev(db, 2)
        st = bound_chain_dedup(db, 2, _rows(1, HEAD_PTS) + _rows(2, TAIL_PTS),
                               FPS, gates)
        assert st["bound_events"] == 0 and st["bound_rejected"] == 0
        assert _kept(db) == {head, tail}


class TestNoNewConstants:
    def test_the_chain_constants_are_untouched(self):
        """The guard's strongest property: it reuses the July-frozen chaining
        window rather than inventing one. The September measurement of the
        real pairs (gap p10 -0.20 / p50 0.85 s) agreed with these
        independently, which is why no constant was added."""
        assert track_chains.STITCH_MOVE_GAP_S == (-0.48, 3.0)
        assert track_chains.STITCH_MOVE_DIST == 70.0
        assert track_chains.CHAIN_DIR_TOL_DEG == 55.0

    def test_default_on(self):
        """SHIPPED 2026-09-24 with GATE_EXIT_ONLY_BINDING (arm gx2)."""
        assert cfg.BOUND_CHAIN_CONSERVE is True


# a head born INSIDE the box (never crosses gate 1) that dies mid-box: no_crossing
NOCROSS_HEAD_PTS = [(float(f), 50.0, 6.0 + 4.3 * f) for f in range(10)]
# a FULL journey: in over gate 1, out over gate 3
FULL_PTS = [(float(f), 50.0, -5.0 + 6.0 * f) for f in range(20)]
# born right behind the full journey's exit, carrying on south: exit_only
AFTER_FULL_PTS = [(21.0 + f, 50.0, 105.0 + 6.0 * f) for f in range(8)]


class TestChainGuardAllPartials:
    """arm cg1 (config.CHAIN_GUARD_ALL_PARTIALS): every partial counted event
    in scope, exactly one count kept per chain."""

    @pytest.fixture(autouse=True)
    def _on(self, monkeypatch):
        monkeypatch.setattr(cfg, "CHAIN_GUARD_ALL_PARTIALS", True)

    def test_a_counted_tail_behind_a_counted_head_yields(self, gates):
        # no posterior_source on either: out of scope for today's guard
        db = _mk_db()
        head, tail = _ev(db, 1), _ev(db, 2)
        st = bound_chain_dedup(db, 2, _rows(1, HEAD_PTS) + _rows(2, TAIL_PTS),
                               FPS, gates)
        assert _kept(db) == {head}
        assert st["partial_rejected"] == 1

    def test_two_partials_in_one_chain_keep_exactly_one(self, gates):
        db = _mk_db()
        head, tail = _ev(db, 1), _ev(db, 2)
        bound_chain_dedup(db, 2, _rows(1, NOCROSS_HEAD_PTS) + _rows(2, TAIL_PTS),
                          FPS, gates)
        assert len(_kept(db)) == 1          # the vehicle is never lost

    def test_a_lone_exit_only_track_is_never_touched(self, gates):
        # operator ruling 2026-09-27: a real car counted once
        db = _mk_db()
        lone = _ev(db, 2)
        st = bound_chain_dedup(db, 2, _rows(2, LONE_PTS), FPS, gates)
        assert _kept(db) == {lone} and st["partial_rejected"] == 0

    def test_a_full_journey_is_never_rejected(self, gates):
        db = _mk_db()
        full, after = _ev(db, 1), _ev(db, 2)
        bound_chain_dedup(db, 2, _rows(1, FULL_PTS) + _rows(2, AFTER_FULL_PTS),
                          FPS, gates)
        assert full in _kept(db)


def test_chain_guard_all_partials_default_off():
    assert cfg.CHAIN_GUARD_ALL_PARTIALS is False
