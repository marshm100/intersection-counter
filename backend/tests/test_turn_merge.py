"""A4a — production turn merge + S5 signal (backend/services/turn_merge.py).

The mechanism itself (merge_turn_fragments) is the validated hybrid_ocbot port;
these tests pin the PORT's behavior + the new DB post-pass semantics: volume
gate scaling via sample_window_seconds, rejected=1 (not deleted), throughs
untouched by construction, borderline S5 output, s5_flags dict contract.
"""
import json
import sqlite3

import pytest

from backend.services.cardinals import bound_approach
from backend.services.turn_merge import (
    bank_expecteds, borderline_merge_cells, merge_replay_turns,
    merge_turn_fragments, s5_flags,
)


def _ev(i, ol=1, dl=2, mv="left", s=0, e=10, start=(100.0, 100.0)):
    return {"id": i, "ol": ol, "dl": dl, "mv": mv, "s": s, "e": e, "start": start}


class TestMergeTurnFragments:
    def test_fragments_merge_when_over_expected(self):
        # 3 same-cell "vehicles" chained head-to-tail within px+gap = fragments
        turns = [_ev(1, s=0, e=10), _ev(2, s=20, e=30), _ev(3, s=45, e=55)]
        keep = merge_turn_fragments(turns, 30.0, 40.0,
                                    expected_by_cell={(1, 2): 1}, vol_factor=1.3)
        assert keep == {1}

    def test_volume_gate_blocks_merge_at_expected_volume(self):
        # Same geometry, but the cell EXPECTS ~3 -> no clear overcount -> no merge
        turns = [_ev(1, s=0, e=10), _ev(2, s=20, e=30), _ev(3, s=45, e=55)]
        keep = merge_turn_fragments(turns, 30.0, 40.0,
                                    expected_by_cell={(1, 2): 3}, vol_factor=1.3)
        assert keep == {1, 2, 3}

    def test_distant_starts_do_not_merge(self):
        turns = [_ev(1, s=0, e=10, start=(100.0, 100.0)),
                 _ev(2, s=20, e=30, start=(400.0, 100.0))]
        keep = merge_turn_fragments(turns, 30.0, 40.0,
                                    expected_by_cell={(1, 2): 1}, vol_factor=1.3)
        assert keep == {1, 2}


class TestBorderline:
    def test_borderline_cell_reported(self):
        turns = [_ev(i, s=i * 100, e=i * 100 + 10) for i in range(134)]
        out = borderline_merge_cells(turns, {(1, 2): 110})
        assert len(out) == 1 and out[0]["raw"] == 134 and not out[0]["merges"]

    def test_far_from_threshold_quiet(self):
        turns = [_ev(i) for i in range(10)]
        assert borderline_merge_cells(turns, {(1, 2): 100}) == []


def _mk_db(tmp_path):
    db = tmp_path / "replay.db"
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE vehicle_events (event_id INTEGER PRIMARY KEY, camera_id INT,
            origin_leg_id INT, destination_leg_id INT, movement TEXT,
            start_frame INT, frame_number INT, trajectory_data TEXT,
            rejected INT DEFAULT 0);
        CREATE TABLE intersection_paths (camera_id INT, origin_leg_id INT,
            destination_leg_id INT, supporting_count INT,
            sample_window_seconds REAL);
    """)
    return db, c


class TestMergeReplayTurns:
    def test_merge_rejects_fragments_and_spares_throughs(self, tmp_path):
        db, c = _mk_db(tmp_path)
        with c:
            # bank: expect 1 left per 1800s -> window 1800 -> threshold 1.3
            c.execute("INSERT INTO intersection_paths VALUES (7, 1, 2, 1, 1800)")
            traj = json.dumps([[100, 100], [110, 110]])
            for i, (s, e) in enumerate(((0, 10), (20, 30), (45, 55))):
                c.execute("INSERT INTO vehicle_events VALUES (?,7,1,2,'left',?,?,?,0)",
                          (i + 1, s, e, traj))
            # a THROUGH pile in the same cell geometry — must never be touched
            for i in range(3):
                c.execute("INSERT INTO vehicle_events VALUES (?,7,1,2,'through',?,?,?,0)",
                          (10 + i, i * 20, i * 20 + 10, traj))
        c.close()
        stats = merge_replay_turns(db, 7, window_seconds=1800)
        assert stats["turns"] == 3 and stats["merged_away"] == 2
        c = sqlite3.connect(db)
        rej = {r[0]: r[1] for r in c.execute(
            "SELECT event_id, rejected FROM vehicle_events")}
        c.close()
        assert rej[1] == 0 and rej[2] == 1 and rej[3] == 1     # rejected, not deleted
        assert rej[10] == rej[11] == rej[12] == 0              # throughs untouched

    def test_window_scaling_disarms_gate(self, tmp_path):
        # Same 3 fragments, but the counting window is 3x the sample window ->
        # expected scales 1 -> 3 -> threshold 3.9 >= 3 raw -> NO merge.
        db, c = _mk_db(tmp_path)
        with c:
            c.execute("INSERT INTO intersection_paths VALUES (7, 1, 2, 1, 1800)")
            traj = json.dumps([[100, 100], [110, 110]])
            for i, (s, e) in enumerate(((0, 10), (20, 30), (45, 55))):
                c.execute("INSERT INTO vehicle_events VALUES (?,7,1,2,'left',?,?,?,0)",
                          (i + 1, s, e, traj))
        c.close()
        stats = merge_replay_turns(db, 7, window_seconds=5400)
        assert stats["merged_away"] == 0

    def test_null_sample_window_falls_back(self, tmp_path):
        db, c = _mk_db(tmp_path)
        with c:
            c.execute("INSERT INTO intersection_paths VALUES (7, 1, 2, 1, NULL)")
        expected = bank_expecteds(c, 7, window_seconds=1800)
        c.close()
        assert expected[(1, 2)] == pytest.approx(1.0)   # 1800/1800 via fallback


class TestS5Flags:
    def test_flag_dict_contract(self):
        borderline = [{"cell": (22, 24), "raw": 134, "expected": 110.0,
                       "threshold": 143.0, "merges": False}]
        flags = s5_flags(1, borderline, {22: "S"}, bound_approach)
        assert len(flags) == 1
        f = flags[0]
        assert f["kind"] == "suspected_gap" and f["subtype"] == "merge_borderline"
        assert f["approach"] == "N" and f["impact"] == pytest.approx(24.0)
        assert f["evidence"]["raw"] == 134 and f["batch_key"] is None
