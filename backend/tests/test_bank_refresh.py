"""Bank refresh — the narrow-update contract (G-BR-1 unit layer)."""
import json
import sqlite3

import pytest

from backend.services.bank_refresh import (refresh_bank, rollback_bank,
                                           shipped_cell_counts,
                                           study_window_seconds)

SCHEMA = """
CREATE TABLE cameras (camera_id INTEGER PRIMARY KEY, intersection_id INTEGER);
CREATE TABLE trims (trim_id INTEGER PRIMARY KEY, intersection_id INTEGER,
    start_wallclock TEXT, end_wallclock TEXT, sort_order INTEGER);
CREATE TABLE vehicle_events (event_id INTEGER PRIMARY KEY,
    camera_id INTEGER, origin_leg_id INTEGER, destination_leg_id INTEGER,
    rejected INTEGER DEFAULT 0);
CREATE TABLE intersection_paths (path_id INTEGER PRIMARY KEY,
    camera_id INTEGER, origin_leg_id INTEGER, destination_leg_id INTEGER,
    polyline TEXT, movement_label TEXT, supporting_count INTEGER,
    sample_window_seconds REAL, source TEXT DEFAULT 'manual');
"""


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.executescript(SCHEMA)
    c.execute("INSERT INTO cameras VALUES (1, 10)")
    c.execute("INSERT INTO trims VALUES (1, 10, '07:00:00', '09:00:00', 0)")
    c.execute("INSERT INTO trims VALUES (2, 10, '16:00:00', '18:00:00', 1)")
    # 3 shipped events 5->6, 1 rejected 5->6, 2 shipped 6->5, 1 legless
    c.executemany("INSERT INTO vehicle_events "
                  "(camera_id, origin_leg_id, destination_leg_id, rejected) "
                  "VALUES (?,?,?,?)",
                  [(1, 5, 6, 0), (1, 5, 6, 0), (1, 5, 6, 0), (1, 5, 6, 1),
                   (1, 6, 5, 0), (1, 6, 5, 0), (1, None, 5, 0)])
    c.execute("INSERT INTO intersection_paths VALUES "
              "(100, 1, 5, 6, '[[0,0],[1,1]]', 'through', 13, 1800.0, 'x')")
    c.execute("INSERT INTO intersection_paths VALUES "
              "(101, 1, 7, 5, '[[2,2],[3,3]]', 'left', 8, 1800.0, 'x')")
    c.commit()
    c.close()
    return p


def test_shipped_basis_is_rejected_zero_with_both_legs(db):
    c = sqlite3.connect(db)
    assert shipped_cell_counts(c, 1) == {(5, 6): 3, (6, 5): 2}
    c.close()


def test_window_from_trims(db):
    c = sqlite3.connect(db)
    assert study_window_seconds(c, 1) == 4 * 3600
    c.close()


def test_narrow_update_and_untouched_columns(db):
    res = refresh_bank("t", 1, db_path=db, write=True)
    assert res["written"]
    c = sqlite3.connect(db)
    rows = {r[0]: r for r in c.execute(
        "SELECT path_id, polyline, movement_label, source, "
        "supporting_count, sample_window_seconds FROM intersection_paths")}
    c.close()
    # priors refreshed: 5->6 has 3 shipped; 7->5 has zero shipped
    assert rows[100][4] == 3 and rows[100][5] == 14400.0
    assert rows[101][4] == 0 and rows[101][5] == 14400.0
    # geometry/labels byte-identical
    assert rows[100][1] == "[[0,0],[1,1]]" and rows[100][2] == "through"
    assert rows[101][1] == "[[2,2],[3,3]]" and rows[101][3] == "x"
    # 6->5 has shipped traffic but no bank row: reported, not created
    assert res["no_row_cells"] == [
        {"origin_leg_id": 6, "destination_leg_id": 5, "counted": 2}]


def test_rollback_restores_exact_values(db, tmp_path):
    refresh_bank("t", 1, db_path=db, write=True)
    sidecar = json.loads(
        (tmp_path / "bank_refresh_rollback_cam1.json").read_text())
    assert {r["path_id"]: r["supporting_count"]
            for r in sidecar["rows"]} == {100: 13, 101: 8}
    n = rollback_bank("t", 1, db_path=db)
    assert n == 2
    c = sqlite3.connect(db)
    vals = list(c.execute("SELECT path_id, supporting_count, "
                          "sample_window_seconds FROM intersection_paths "
                          "ORDER BY path_id"))
    c.close()
    assert vals == [(100, 13, 1800.0), (101, 8, 1800.0)]


def test_dry_run_writes_nothing(db):
    res = refresh_bank("t", 1, db_path=db, write=False)
    assert not res["written"]
    c = sqlite3.connect(db)
    assert list(c.execute("SELECT supporting_count FROM intersection_paths "
                          "ORDER BY path_id")) == [(13,), (8,)]
    c.close()
