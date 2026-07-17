"""Conservation pass (mechanism ① iteration 3) — fragment chains + the
at-most-one-per-chain reject semantics. docs/plan_conservation_pass_2026-07-15.md."""
import os
import sqlite3
import tempfile

import pytest

from backend.database import SCHEMA
from backend.services.entry_gates import build_gates
from backend.services.track_chains import build_chain_map, chain_tracks
from backend.services.two_pass import conserve_replay_additions

# the synthetic box from test_entry_gates: 4 legs, N-S + W-E channels
LEGS = {1: (50.0, 0.0), 2: (100.0, 50.0), 3: (50.0, 100.0), 4: (0.0, 50.0)}
PATHS = [{"origin_leg_id": 1, "destination_leg_id": 3,
          "polyline": [[50, -20], [50, 120]]},
         {"origin_leg_id": 4, "destination_leg_id": 2,
          "polyline": [[-20, 50], [120, 50]]}]
HEAD = {1: 180.0, 2: 270.0, 3: 0.0, 4: 90.0}
FPS = 10.0


@pytest.fixture(scope="module")
def gates():
    return build_gates(LEGS, PATHS, HEAD)


# entry_only fragment: enters gate 1, dies mid-box moving
FRAG_A = [(float(f), 50.0, -5.0 + 6.0 * f) for f in range(10)]      # y -5..49
# its continuation: born near A's death 2 frames later, exits gate 3
FRAG_B = [(10.0 + f, 50.0, 52.0 + 6.0 * f) for f in range(10)]      # y 52..106
# a FULL-journey vehicle passing nearby (the follower class)
FULL = [(float(f), 56.0, -10.0 + 12.0 * f) for f in range(12)]


class TestChains:
    def test_fragments_chain(self, gates):
        cm = build_chain_map({1: FRAG_A, 2: FRAG_B}, gates, FPS)
        assert cm[1] == cm[2]

    def test_full_journey_never_chains(self, gates):
        # a box-full track may be neither A (needs missing exit) nor B
        # (needs missing entry) — the dedup-ceiling follower protection
        full_late = [(10.0 + f, 50.0, -10.0 + 12.0 * f) for f in range(12)]
        cm = build_chain_map({1: FRAG_A, 2: full_late}, gates, FPS)
        assert cm[1] != cm[2]

    def test_distant_birth_does_not_chain(self, gates):
        far = [(10.0 + f, 50.0 + 90.0, 52.0 + 6.0 * f) for f in range(10)]
        cm = build_chain_map({1: FRAG_A, 2: far}, gates, FPS)
        assert cm[1] != cm[2]

    def test_chain_extends_in_time_only(self, gates):
        # B entirely BEFORE A's death cannot continue A
        early = [(float(f), 50.0, 52.0 + 6.0 * f) for f in range(5)]
        chains = chain_tracks([
            {"tid": 1, "birth": FRAG_A[0], "death": FRAG_A[-1],
             "tag": "entry_only", "v_end": 6.0},
            {"tid": 2, "birth": early[0], "death": early[-1],
             "tag": "no_crossing", "v_end": 6.0}], FPS)
        assert all(len(c) == 1 for c in chains)


def _mk_db():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "p.db")
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.commit(); conn.close()
    return db


def _ev(db, tid, source=None, npts=10, cam=2):
    conn = sqlite3.connect(db)
    with conn:
        eid = conn.execute(
            "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
            "origin_leg_id, movement, trajectory_data, trajectory_confidence, "
            "vehicle_class, detection_confidence, timestamp_video, frame_number, "
            "classifier_num_points, posterior_source) "
            "VALUES (?, ?, 1, 'through', '[[1,2]]', 0.9, 'car', 0.9, 10.0, 100, ?, ?)",
            (cam, tid, npts, source)).lastrowid
    conn.close()
    return eid


def _kept(db):
    conn = sqlite3.connect(db)
    rows = {r[0] for r in conn.execute(
        "SELECT event_id FROM vehicle_events WHERE COALESCE(rejected,0)=0")}
    conn.close()
    return rows


class TestConserve:
    def test_additive_loses_to_legacy(self):
        db = _mk_db()
        e1 = _ev(db, 1, None)              # legacy fragment event
        e2 = _ev(db, 2, "branch1")         # additive fragment of same chain
        stats = conserve_replay_additions(db, 2, {1: 7, 2: 7})
        assert _kept(db) == {e1}
        assert stats["rejected_vs_legacy"] == 1

    def test_best_additive_survives_all_additive_chain(self):
        db = _mk_db()
        e1 = _ev(db, 1, "rescue_supports")
        e2 = _ev(db, 2, "rescue_full")
        e3 = _ev(db, 3, "branch1")
        conserve_replay_additions(db, 2, {1: 7, 2: 7, 3: 7})
        assert _kept(db) == {e2}           # rescue_full outranks

    def test_singletons_and_unmapped_untouched(self):
        db = _mk_db()
        e1 = _ev(db, 1, "branch1")         # singleton chain
        e2 = _ev(db, 2, "branch1")         # unmapped track
        conserve_replay_additions(db, 2, {1: 7})
        assert _kept(db) == {e1, e2}

    def test_legacy_multicounts_predate_us(self):
        db = _mk_db()
        e1 = _ev(db, 1, None)
        e2 = _ev(db, 2, None)              # two legacy events, one chain:
        conserve_replay_additions(db, 2, {1: 7, 2: 7})
        assert _kept(db) == {e1, e2}       # not ours to fix

    def test_dest_tie_counts_as_legacy(self):
        db = _mk_db()
        e1 = _ev(db, 1, "dest_tie")        # re-picked legacy event
        e2 = _ev(db, 2, "branch1")
        conserve_replay_additions(db, 2, {1: 7, 2: 7})
        assert _kept(db) == {e1}

    def test_other_camera_untouched(self):
        db = _mk_db()
        e1 = _ev(db, 1, None, cam=2)
        e2 = _ev(db, 2, "branch1", cam=3)  # same chain ids, other camera
        conserve_replay_additions(db, 2, {1: 7, 2: 7})
        assert _kept(db) == {e1, e2}
