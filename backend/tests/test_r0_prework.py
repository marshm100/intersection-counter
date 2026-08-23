"""R0 pre-work (plan 2026-08-23): the two fixes that make a measured review
pass possible.

1. add_event must write timestamp_real — without it an add-missed event is
   invisible to the dev scorer's production column (triangulate_manual.load_ours
   drops NULL-timestamp rows), so review's headline lever would not appear in a
   before/after measurement.
2. The flag queue must scope to one wallclock window (list_flags window=) so an
   operator can work ONE window until clean. Strict scope: flags with no window
   evidence (whole-day cell-level gaps, un-keyed event flags) are excluded.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import (
    _flag_in_window,
    _parse_window,
    get_connection,
    list_flags,
)
from backend.tests.test_two_pass_stage34 import _mk_cam

client = TestClient(app)


@pytest.fixture()
def proj():
    pid = client.post("/api/projects", json={"name": "r0-prework-test"}).json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _add_leg(pid, cid, cardinal="N"):
    conn = get_connection(pid)
    with conn:
        lid = conn.execute(
            "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
            "origin_zone, reference_heading) VALUES (?, ?, ?, 0, '[]', 90.0)",
            (cid, cardinal, cardinal)).lastrowid
    conn.close()
    return lid


def _video_id(pid, cid):
    conn = get_connection(pid)
    vid = conn.execute("SELECT video_id FROM videos WHERE camera_id=?", (cid,)).fetchone()[0]
    conn.close()
    return vid


class TestAddMissedTimestampReal:
    def test_timestamp_real_written_from_video_anchor(self, proj):
        iid, cid = _mk_cam(proj, video={
            "path": "X:/gone.mp4", "fps": 25.0, "total_frames": 100,
            "recording_start_datetime": "2026-05-12T00:00:02"})
        lid = _add_leg(proj, cid)
        r = client.post(f"/api/projects/{proj}/review", json={
            "origin_leg_id": lid, "movement": "through",
            "timestamp_video": 58818.56, "video_id": _video_id(proj, cid),
            "x": 10.0, "y": 20.0})
        assert r.status_code == 200
        conn = get_connection(proj)
        ts = conn.execute(
            "SELECT timestamp_real FROM vehicle_events WHERE event_id=?",
            (r.json()["event_id"],)).fetchone()[0]
        conn.close()
        # 2026-05-12T00:00:02 + 58818.56 s = 16:20:20.56 wallclock
        assert ts is not None
        assert datetime.fromisoformat(ts) == datetime.fromisoformat(
            "2026-05-12T16:20:20.560000")

    def test_no_video_id_leaves_timestamp_real_null(self, proj):
        iid, cid = _mk_cam(proj, video={
            "path": "X:/gone.mp4", "fps": 25.0, "total_frames": 100,
            "recording_start_datetime": "2026-05-12T00:00:02"})
        lid = _add_leg(proj, cid)
        r = client.post(f"/api/projects/{proj}/review", json={
            "origin_leg_id": lid, "movement": "through",
            "timestamp_video": 100.0})
        assert r.status_code == 200
        conn = get_connection(proj)
        ts = conn.execute(
            "SELECT timestamp_real FROM vehicle_events WHERE event_id=?",
            (r.json()["event_id"],)).fetchone()[0]
        conn.close()
        assert ts is None

    def test_malformed_anchor_does_not_break_add(self, proj):
        iid, cid = _mk_cam(proj, video={
            "path": "X:/gone.mp4", "fps": 25.0, "total_frames": 100,
            "recording_start_datetime": "not-a-datetime"})
        lid = _add_leg(proj, cid)
        r = client.post(f"/api/projects/{proj}/review", json={
            "origin_leg_id": lid, "movement": "left",
            "timestamp_video": 5.0, "video_id": _video_id(proj, cid)})
        assert r.status_code == 200  # event still lands, timestamp_real just NULL
        conn = get_connection(proj)
        ts = conn.execute(
            "SELECT timestamp_real FROM vehicle_events WHERE event_id=?",
            (r.json()["event_id"],)).fetchone()[0]
        conn.close()
        assert ts is None


class TestParseWindow:
    def test_valid(self):
        assert _parse_window("1600-1800") == (57600, 64800)
        assert _parse_window("0000-2400") == (0, 86400)

    @pytest.mark.parametrize("bad", ["16-18", "1600", "1800-1600", "16001800",
                                     "2500-2600", "abcd-efgh"])
    def test_invalid_raises(self, bad):
        with pytest.raises(ValueError):
            _parse_window(bad)


def _row(batch_key=None, interval=None):
    return {"batch_key": batch_key, "interval_start_seconds": interval}


class TestFlagInWindow:
    def test_event_flag_by_batch_key_bin(self):
        assert _flag_in_window(_row(batch_key="bin|2|NB-through|16:15"), 57600, 64800)
        assert _flag_in_window(_row(batch_key="bin|2|NB-through|17:45"), 57600, 64800)
        assert not _flag_in_window(_row(batch_key="bin|2|NB-through|15:45"), 57600, 64800)
        assert not _flag_in_window(_row(batch_key="bin|2|NB-through|18:00"), 57600, 64800)

    def test_gap_flag_by_interval_seconds(self):
        assert _flag_in_window(_row(interval=57600.0), 57600, 64800)
        assert _flag_in_window(_row(interval=63900.0), 57600, 64800)
        assert not _flag_in_window(_row(interval=56700.0), 57600, 64800)
        assert not _flag_in_window(_row(interval=64800.0), 57600, 64800)

    def test_no_window_evidence_is_excluded(self):
        # whole-day cell-level gap flags and un-keyed event flags: strict scope
        assert not _flag_in_window(_row(), 57600, 64800)
        assert not _flag_in_window(_row(batch_key="hole|26-29"), 57600, 64800)

    def test_malformed_bin_key_excluded(self):
        assert not _flag_in_window(_row(batch_key="bin|2|NB-through|junk"), 57600, 64800)


class TestListFlagsWindow:
    def _seed_flags(self, pid, iid, cid):
        conn = get_connection(pid)
        with conn:
            rows = [
                # (kind, subtype, batch_key, interval, impact)
                ("uncertain_event", "low_det_conf", "bin|2|NB-through|16:15", None, 1),
                ("uncertain_event", "low_det_conf", "bin|2|NB-through|11:00", None, 1),
                ("suspected_gap", "interval_corridor", None, 57600.0, 100),
                ("suspected_gap", "interval_corridor", None, 39600.0, 50),
                ("suspected_gap", "bank_coverage_hole", "hole|26-29", None, 400),
            ]
            for kind, sub, bk, iv, imp in rows:
                conn.execute(
                    "INSERT INTO review_flags (intersection_id, camera_id, kind, "
                    "subtype, batch_key, interval_start_seconds, impact, reason, "
                    "status, created_at) VALUES (?,?,?,?,?,?,?,?,'open','2026-08-23')",
                    (iid, cid, kind, sub, bk, iv, imp, "t"))
        conn.close()

    def test_window_scopes_and_orders(self, proj):
        iid, cid = _mk_cam(proj, video={
            "path": "X:/gone.mp4", "fps": 25.0, "total_frames": 100,
            "recording_start_datetime": "2026-05-12T00:00:02"})
        self._seed_flags(proj, iid, cid)
        flags = list_flags(proj, iid, window="1600-1800")
        keys = [(f["kind"], f["subtype"]) for f in flags]
        # only the 16:15 event flag and the 57600 gap flag survive;
        # impact-desc puts the gap flag first
        assert keys == [("suspected_gap", "interval_corridor"),
                        ("uncertain_event", "low_det_conf")]
        # no window: everything comes back
        assert len(list_flags(proj, iid)) == 5

    def test_limit_applies_after_window_filter(self, proj):
        iid, cid = _mk_cam(proj, video={
            "path": "X:/gone.mp4", "fps": 25.0, "total_frames": 100,
            "recording_start_datetime": "2026-05-12T00:00:02"})
        self._seed_flags(proj, iid, cid)
        flags = list_flags(proj, iid, window="1600-1800", limit=1)
        assert len(flags) == 1
        assert flags[0]["kind"] == "suspected_gap"  # highest impact in window

    def test_router_passes_window_and_rejects_junk(self, proj):
        iid, cid = _mk_cam(proj, video={
            "path": "X:/gone.mp4", "fps": 25.0, "total_frames": 100,
            "recording_start_datetime": "2026-05-12T00:00:02"})
        self._seed_flags(proj, iid, cid)
        r = client.get(f"/api/projects/{proj}/intersections/{iid}/flags"
                       f"?status=open&window=1600-1800")
        assert r.status_code == 200
        assert len(r.json()["flags"]) == 2
        r = client.get(f"/api/projects/{proj}/intersections/{iid}/flags"
                       f"?status=open&window=junk")
        assert r.status_code == 422
