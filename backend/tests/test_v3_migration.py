"""v2 -> v3 migration auto-bootstrap (Phase 10).

A legacy v2 project has a flat video list with no camera_id and no
intersections/cameras/trims. The first time it's opened under v3,
ensure_default_intersection_for_legacy() must create a default intersection +
camera + trim and link existing videos/legs/events — idempotently, without
losing data. These tests verify that, AND that the GET intersections endpoint
actually triggers it (the bootstrap was previously never called).
"""

import sqlite3

from fastapi.testclient import TestClient

from backend.app import app
from backend.database import ensure_default_intersection_for_legacy, get_connection

client = TestClient(app)


def _seed_v2_project(name: str) -> tuple[str, int]:
    """Create a project, then seed legacy v2-shape data: a video, legs, and
    events all with camera_id IS NULL and no intersections/cameras/trims.
    Returns (project_id, leg_id)."""
    pid = client.post("/api/projects", json={"name": name}).json()["project_id"]
    conn = get_connection(pid)
    try:
        conn.execute(
            "INSERT INTO videos (sort_order, path, filename, fps, width, height, "
            "total_frames, duration_seconds, file_size_bytes, recording_start_datetime, added_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (0, "/x/v.mp4", "v.mp4", 30.0, 640, 480, 90, 3.0, 1000,
             "2026-05-14T08:00:00", "2026-05-14T08:00:00"),
        )
        leg_id = conn.execute(
            "INSERT INTO legs (label, cardinal_direction, sort_order, origin_zone, reference_heading) "
            "VALUES (?,?,?,?,?)",
            ("North", "NB", 0, "[[0,240],[640,240]]", 180.0),
        ).lastrowid
        for tk, mv in ((1, "through"), (2, "left")):
            conn.execute(
                "INSERT INTO vehicle_events (vehicle_track_id, origin_leg_id, movement, "
                "trajectory_data, trajectory_confidence, vehicle_class, detection_confidence, "
                "timestamp_video, frame_number) VALUES (?,?,?,?,?,?,?,?,?)",
                (tk, leg_id, mv, "[]", 0.9, "car", 0.8, 1.0, 30),
            )
        conn.commit()
    finally:
        conn.close()
    return pid, leg_id


def _counts(pid: str) -> dict:
    conn = get_connection(pid)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "intersections": conn.execute("SELECT COUNT(*) FROM intersections").fetchone()[0],
            "cameras": conn.execute("SELECT COUNT(*) FROM cameras").fetchone()[0],
            "trims": conn.execute("SELECT COUNT(*) FROM trims").fetchone()[0],
            "videos_unlinked": conn.execute("SELECT COUNT(*) FROM videos WHERE camera_id IS NULL").fetchone()[0],
            "legs_unlinked": conn.execute("SELECT COUNT(*) FROM legs WHERE camera_id IS NULL").fetchone()[0],
            "events_unlinked": conn.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id IS NULL").fetchone()[0],
            "events_total": conn.execute("SELECT COUNT(*) FROM vehicle_events").fetchone()[0],
        }
    finally:
        conn.close()


def test_legacy_project_bootstraps_and_links_everything():
    pid, _ = _seed_v2_project("v2mig")
    try:
        iid = ensure_default_intersection_for_legacy(pid)
        assert iid is not None
        c = _counts(pid)
        # default intersection + camera created
        assert c["intersections"] == 1 and c["cameras"] == 1
        # videos/legs/events all linked (no orphans)
        assert c["videos_unlinked"] == 0
        assert c["legs_unlinked"] == 0
        assert c["events_unlinked"] == 0
        # data preserved (both events still there, just linked)
        assert c["events_total"] == 2
        # a default trim spanning the clip was created (08:00:00 + 3s)
        conn = get_connection(pid)
        conn.row_factory = sqlite3.Row
        try:
            trims = conn.execute("SELECT * FROM trims WHERE intersection_id=?", (iid,)).fetchall()
            assert len(trims) == 1
            assert trims[0]["start_wallclock"] == "08:00:00"
            assert trims[0]["end_wallclock"] == "08:00:03"
            cid = conn.execute("SELECT camera_id FROM cameras").fetchone()[0]
            assert conn.execute(
                "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (cid,)
            ).fetchone()[0] == 2
        finally:
            conn.close()
    finally:
        client.delete(f"/api/projects/{pid}")


def test_migration_is_idempotent():
    pid, _ = _seed_v2_project("v2mig-idem")
    try:
        first = ensure_default_intersection_for_legacy(pid)
        assert first is not None
        # Second call: everything already linked -> no-op, returns None.
        assert ensure_default_intersection_for_legacy(pid) is None
        c = _counts(pid)
        assert c["intersections"] == 1
        assert c["cameras"] == 1
        assert c["trims"] == 1  # not duplicated
    finally:
        client.delete(f"/api/projects/{pid}")


def test_migration_noop_when_no_videos():
    pid = client.post("/api/projects", json={"name": "v2-empty"}).json()["project_id"]
    try:
        assert ensure_default_intersection_for_legacy(pid) is None
        assert _counts(pid)["intersections"] == 0
    finally:
        client.delete(f"/api/projects/{pid}")


def test_get_intersections_triggers_lazy_migration():
    """Opening the Intersections tab on a legacy project must auto-create its
    default card (regression guard: the bootstrap had no caller before)."""
    pid, _ = _seed_v2_project("v2-wire")
    try:
        assert _counts(pid)["intersections"] == 0  # not migrated yet
        cards = client.get(f"/api/projects/{pid}/intersections").json()
        assert len(cards) == 1  # the GET triggered the bootstrap
        c = _counts(pid)
        assert c["videos_unlinked"] == 0 and c["events_unlinked"] == 0
    finally:
        client.delete(f"/api/projects/{pid}")
