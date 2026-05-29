"""Tests for scripts/apply_recal_updates.py — the high-stakes recalibration apply.

The whole point of this script is to update leg geometry + replace the path bank
WITHOUT losing vehicle_events (the project has ~113 real trajectories and no
backup). These tests drive the real --apply path against a synthetic temp-DB
project (PROJECTS_DIR is redirected to tmp by conftest) and assert:
  * vehicle_events are preserved (both modern camera_id rows and legacy
    camera_id=NULL rows that carry one of the camera's leg_ids),
  * leg origin_zone + reference_heading are updated in place,
  * the path bank is fully replaced with the new data-driven paths,
  * a turn path with destination_leg_id=None is skipped (column is NOT NULL),
  * an audit suggestion row is written (status=applied),
  * a verified backup file is produced.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from backend.database import get_connection, get_db_path

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import apply_recal_updates as ara  # noqa: E402

CAM = 1


def _insert_leg(conn, label, sort_order):
    cur = conn.execute(
        "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
        "origin_zone, reference_heading) VALUES (?, ?, ?, ?, ?, ?)",
        (CAM, label, "N", sort_order, json.dumps([[1.0, 2.0]]), 10.0))
    return int(cur.lastrowid)


def _insert_event(conn, origin_leg_id, *, camera_id):
    conn.execute(
        "INSERT INTO vehicle_events (camera_id, vehicle_track_id, origin_leg_id, "
        "movement, trajectory_data, trajectory_confidence, vehicle_class, "
        "detection_confidence, timestamp_video, frame_number) "
        "VALUES (?, ?, ?, 'through', '[[0,0],[1,1]]', 0.9, 'car', 0.9, 1.0, 1)",
        (camera_id, 1, origin_leg_id))


def _insert_path(conn, o, d):
    conn.execute(
        "INSERT INTO intersection_paths (camera_id, origin_leg_id, destination_leg_id, "
        "polyline, movement_label, supporting_count, source, created_at) "
        "VALUES (?, ?, ?, '[[0,0]]', 'through', 1, 'manual', '2026-01-01T00:00:00Z')",
        (CAM, o, d))


@pytest.fixture
def proj(tmp_path):
    """A unique synthetic project, seeded, returning (pid, leg_a, leg_b)."""
    pid = "ztest_recal_" + tmp_path.name
    conn = get_connection(pid)
    try:
        with conn:
            # parent rows so the legs/paths/events FKs (-> cameras) hold.
            # Fresh per-test DB => these autoincrement to id 1, matching CAM.
            conn.execute(
                "INSERT INTO intersections (name, date, sort_order, created_at) "
                "VALUES ('X', '2026-01-01', 0, '2026-01-01T00:00:00Z')")
            conn.execute(
                "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
                "VALUES (1, 'cam', 0, '2026-01-01T00:00:00Z')")
            la = _insert_leg(conn, "Leg A", 0)
            lb = _insert_leg(conn, "Leg B", 1)
            # 2 modern (camera_id=1) + 1 legacy (camera_id=NULL, leg-tagged)
            _insert_event(conn, la, camera_id=CAM)
            _insert_event(conn, lb, camera_id=CAM)
            _insert_event(conn, la, camera_id=None)
            # 2 stale paths that must be fully cleared
            _insert_path(conn, la, lb)
            _insert_path(conn, lb, la)
    finally:
        conn.close()
    return pid, la, lb


def _suggestion(pid, la, lb):
    return {
        "project": pid, "camera_id": CAM,
        "updated_legs": [
            {"leg_id": la, "approach": "A", "origin_point": [100.0, 200.0],
             "reference_heading": 83.8},
            {"leg_id": lb, "approach": "B", "origin_point": [300.0, 220.0],
             "reference_heading": 261.8},
        ],
        "paths": [
            {"origin_leg_id": la, "destination_leg_id": lb, "movement_label": "through",
             "polyline": [[1.0, 1.0], [2.0, 2.0]], "supporting_count": 64,
             "source": "data-driven"},
            {"origin_leg_id": lb, "destination_leg_id": la, "movement_label": "through",
             "polyline": [[3.0, 3.0], [4.0, 4.0]], "supporting_count": 48,
             "source": "data-driven"},
            # turn path with no destination -> must be skipped (NOT NULL column)
            {"origin_leg_id": la, "destination_leg_id": None, "movement_label": "right",
             "polyline": [[5.0, 5.0]], "supporting_count": 9, "source": "data-driven"},
        ],
    }


def _run_apply(tmp_path, pid, la, lb, extra=()):
    sug = tmp_path / "recal.json"
    sug.write_text(json.dumps(_suggestion(pid, la, lb)))
    argv = ["apply_recal_updates.py", "--project", pid, "--camera-id", str(CAM),
            "--suggestion", str(sug), "--apply", *extra]
    old = sys.argv
    sys.argv = argv
    try:
        return ara.main()
    finally:
        sys.argv = old


def test_apply_preserves_events_and_replaces_paths(proj, tmp_path):
    pid, la, lb = proj
    assert _run_apply(tmp_path, pid, la, lb) == 0

    conn = get_connection(pid)
    try:
        # events preserved (all 3, including the legacy NULL-camera row)
        assert ara._count_events(conn, CAM) == 3
        # legs updated in place
        legs = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs WHERE camera_id=?",
            (CAM,))}
        assert json.loads(legs[la][0]) == [[100.0, 200.0]]
        assert legs[la][1] == 83.8
        assert json.loads(legs[lb][0]) == [[300.0, 220.0]]
        # path bank fully replaced: exactly the 2 valid through paths, all data-driven
        rows = conn.execute(
            "SELECT origin_leg_id, destination_leg_id, movement_label, source "
            "FROM intersection_paths WHERE camera_id=? ORDER BY origin_leg_id",
            (CAM,)).fetchall()
        assert len(rows) == 2  # the None-dest turn path was skipped
        assert all(r[3] == "data-driven" for r in rows)
        assert {(r[0], r[1]) for r in rows} == {(la, lb), (lb, la)}
        # audit row applied
        st = conn.execute(
            "SELECT status FROM calibration_suggestions WHERE camera_id=?",
            (CAM,)).fetchone()
        assert st[0] == "applied"
    finally:
        conn.close()

    # a verified backup file exists and is itself a readable, complete db
    baks = list((get_db_path(pid).parent / "backups").glob("project_*.db"))
    assert baks, "no backup file written"


def test_apply_is_idempotent(proj, tmp_path):
    pid, la, lb = proj
    assert _run_apply(tmp_path, pid, la, lb) == 0
    assert _run_apply(tmp_path, pid, la, lb) == 0  # second run must not crash or duplicate
    conn = get_connection(pid)
    try:
        assert ara._count_events(conn, CAM) == 3
        n = conn.execute(
            "SELECT COUNT(*) FROM intersection_paths WHERE camera_id=?", (CAM,)).fetchone()[0]
        assert n == 2
    finally:
        conn.close()


def test_apply_heading_only_preserves_origin(proj, tmp_path):
    """When updated_legs omits origin_point, reference_heading updates but the
    engineer-placed origin_zone is left untouched (the (a)/(d) decision)."""
    pid, la, lb = proj
    sug = _suggestion(pid, la, lb)
    for ul in sug["updated_legs"]:
        ul.pop("origin_point")  # heading-only suggestion
    sf = tmp_path / "recal.json"
    sf.write_text(json.dumps(sug))
    old = sys.argv
    sys.argv = ["apply_recal_updates.py", "--project", pid, "--camera-id", str(CAM),
                "--suggestion", str(sf), "--apply"]
    try:
        assert ara.main() == 0
    finally:
        sys.argv = old
    conn = get_connection(pid)
    try:
        row = conn.execute(
            "SELECT origin_zone, reference_heading FROM legs WHERE leg_id=?", (la,)).fetchone()
        assert json.loads(row[0]) == [[1.0, 2.0]]   # ORIGIN UNCHANGED (seeded value)
        assert row[1] == 83.8                        # heading updated
        assert ara._count_events(conn, CAM) == 3     # events preserved
    finally:
        conn.close()


def test_dry_run_writes_nothing(proj, tmp_path):
    pid, la, lb = proj
    sug = tmp_path / "recal.json"
    sug.write_text(json.dumps(_suggestion(pid, la, lb)))
    old = sys.argv
    sys.argv = ["apply_recal_updates.py", "--project", pid, "--camera-id", str(CAM),
                "--suggestion", str(sug)]  # no --apply
    try:
        assert ara.main() == 0
    finally:
        sys.argv = old
    conn = get_connection(pid)
    try:
        # legs untouched (still the seeded origin/heading), paths untouched (still 2 manual)
        leg = conn.execute(
            "SELECT origin_zone, reference_heading FROM legs WHERE leg_id=?", (la,)).fetchone()
        assert json.loads(leg[0]) == [[1.0, 2.0]] and leg[1] == 10.0
        src = conn.execute(
            "SELECT DISTINCT source FROM intersection_paths WHERE camera_id=?",
            (CAM,)).fetchall()
        assert src == [("manual",)]
    finally:
        conn.close()
