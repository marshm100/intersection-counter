"""R0 instrument v2 (operator spec 2026-08-24): gap-card line items +
the review_log audit trail.

- gap_items.items_for_flag: machine-proposed candidates — counted and
  rejected tracks excluded, parked/jitter excluded (speed floor), wrong
  approach excluded, times cued to the entry crossing. Proposals only.
- review_log: append-only findings-as-data; REBUILD-IMMUNE (flag
  rebuilds delete open flags; the log must survive).
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import (
    append_review_log, clear_open_flags, get_connection, insert_flag,
    list_review_log,
)

client = TestClient(app)


@pytest.fixture()
def site():
    pid = client.post("/api/projects",
                      json={"name": "instr-test"}).json()["project_id"]
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count,"
            " created_at) VALUES ('T', '2026-08-24', 0, 4, '2026-08-24')"
        ).lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order,"
            " created_at) VALUES (?, 'c', 0, '2026-08-24')", (iid,)
        ).lastrowid
        # north leg (bound approach 'S') and south leg (bound 'N'),
        # drawn gates spanning the roadway
        ln = conn.execute(
            "INSERT INTO legs (camera_id, label, cardinal_direction,"
            " sort_order, origin_zone, reference_heading, gate_segment)"
            " VALUES (?, 'N leg', 'N', 0, '[[100,20]]', 180.0,"
            " '[[0,50],[200,50]]')", (cid,)).lastrowid
        ls = conn.execute(
            "INSERT INTO legs (camera_id, label, cardinal_direction,"
            " sort_order, origin_zone, reference_heading, gate_segment)"
            " VALUES (?, 'S leg', 'S', 1, '[[100,380]]', 0.0,"
            " '[[0,350],[200,350]]')", (cid,)).lastrowid
        conn.execute(
            "INSERT INTO videos (camera_id, sort_order, path, filename,"
            " fps, total_frames, duration_seconds, file_size_bytes,"
            " width, height, recording_start_datetime, added_at) VALUES"
            " (?, 0, 'x.mp4', 'x.mp4', 25.0, 100000, 4000.0, 1,"
            " 640, 480, '2026-05-12T00:00:00', '2026-08-24')", (cid,))
        # tid 7 is already counted
        conn.execute(
            "INSERT INTO vehicle_events (camera_id, vehicle_track_id,"
            " origin_leg_id, destination_leg_id, movement,"
            " trajectory_data, trajectory_confidence, vehicle_class,"
            " detection_confidence, timestamp_video, frame_number)"
            " VALUES (?, 7, ?, ?, 'through', '[]', 0.9, 'car', 0.9,"
            " 10.0, 250)", (cid, ln, ls))
    conn.close()
    yield pid, iid, cid, ln, ls
    client.delete(f"/api/projects/{pid}")


def _rows(tracks):
    out = []
    for tid, pts in tracks.items():
        for f, x, y in pts:
            out.append([tid, f, x, y, 30.0, 20.0, 0.9, 2.0])
    out.sort(key=lambda r: r[1])
    return np.array(out, dtype=np.float32)


def _sb(tid, f0=0, n=100):
    """Southbound through: crosses both gates (y 10 -> 406)."""
    return [(float(f0 + i), 100.0, 10.0 + 4.0 * i) for i in range(n)]


class TestGapItems:
    def _run(self, monkeypatch, pid, cid, tracks, flag):
        from backend.services import gap_items
        rows = _rows(tracks)
        entry = {"rows": rows, "frames": rows[:, 1], "fps": 25.0,
                 "variant": "study_test"}
        monkeypatch.setattr(gap_items, "_resolve_variant",
                            lambda *a, **k: "study_test")
        monkeypatch.setattr(gap_items, "_load", lambda *a, **k: entry)
        return gap_items.items_for_flag(pid, flag)

    def test_candidate_proposed_counted_and_offapproach_excluded(
            self, monkeypatch, site):
        pid, iid, cid, ln, ls = site
        tracks = {
            5: _sb(5),                       # eventless SB full -> ITEM
            7: _sb(7),                       # counted -> excluded
            9: [(float(f), 100.0, 200.0) for f in range(100)],  # parked
            11: [(float(f), 120.0, 396.0 - 4.0 * f)             # NB: wrong
                 for f in range(100)],                          # approach
        }
        flag = {"camera_id": cid, "interval_start_seconds": 0.0,
                "interval_end_seconds": 40.0, "approach": "S"}
        out = self._run(monkeypatch, pid, cid, tracks, flag)
        tids = [it["tid"] for it in out["items"]]
        assert tids == [5]
        it = out["items"][0]
        assert it["origin_leg_id"] == ln
        assert it["destination_leg_id"] == ls
        # movement comes from derive_movement (its correctness is
        # trajectory_classifier's tested domain; the 2-leg fixture is
        # geometrically degenerate) — the contract here is that full
        # tracks arrive WITH a movement proposal
        assert it["movement"] in ("through", "left", "right", "u_turn")
        assert it["tag"] == "full"
        # cued to the entry-gate crossing (~y=50 at frame 10 -> 0.4 s)
        assert 0.0 < it["t_cross"] < 2.0

    def test_rejected_pool_not_reproposed(self, monkeypatch, site):
        pid, iid, cid, ln, ls = site
        conn = get_connection(pid)
        with conn:
            conn.execute(
                "INSERT INTO vehicle_events (camera_id, vehicle_track_id,"
                " origin_leg_id, movement, trajectory_data,"
                " trajectory_confidence, vehicle_class,"
                " detection_confidence, timestamp_video, frame_number,"
                " rejected) VALUES (?, 5, ?, 'through', '[]', 0.9, 'car',"
                " 0.9, 1.0, 25, 1)", (cid, ln))
        conn.close()
        flag = {"camera_id": cid, "interval_start_seconds": 0.0,
                "interval_end_seconds": 40.0, "approach": "S"}
        out = self._run(monkeypatch, pid, cid, {5: _sb(5)}, flag)
        assert out["items"] == []            # a human already rejected it

    def test_endpoint_marks_done_items(self, monkeypatch, site):
        pid, iid, cid, ln, ls = site
        from backend.services import gap_items
        rows = _rows({5: _sb(5)})
        entry = {"rows": rows, "frames": rows[:, 1], "fps": 25.0,
                 "variant": "study_test"}
        monkeypatch.setattr(gap_items, "_resolve_variant",
                            lambda *a, **k: "study_test")
        monkeypatch.setattr(gap_items, "_load", lambda *a, **k: entry)
        fid = insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                          subtype="interval_corridor", camera_id=cid,
                          interval_start_seconds=0.0,
                          interval_end_seconds=40.0, approach="S",
                          impact=10)
        append_review_log(pid, cid, f"f{fid}", item_key="tid:5",
                          action="added", source_tid=5)
        r = client.get(f"/api/projects/{pid}/flags/{fid}/items").json()
        assert r["card_key"] == f"f{fid}"
        assert r["items"][0]["tid"] == 5
        assert r["items"][0]["done"] == "added"


class TestReviewLog:
    def test_append_list_and_card_filter(self, site):
        pid, iid, cid, ln, ls = site
        append_review_log(pid, cid, "cardA", item_key="tid:5",
                          action="added", event_id=1, source_tid=5)
        append_review_log(pid, cid, "cardA", item_key="card",
                          action="verdict", verdict="fixed_as_asked",
                          note="two missed SB")
        append_review_log(pid, cid, "cardB", action="verdict",
                          verdict="nothing_wrong")
        a = list_review_log(pid, card_key="cardA")
        assert [r["action"] for r in a] == ["added", "verdict"]
        assert a[1]["verdict"] == "fixed_as_asked"
        assert a[1]["note"] == "two missed SB"
        assert len(list_review_log(pid)) == 3

    def test_rebuild_immune(self, site):
        pid, iid, cid, ln, ls = site
        insert_flag(pid, intersection_id=iid, kind="suspected_gap",
                    subtype="interval_corridor", impact=5)
        append_review_log(pid, cid, "cardA", action="added", source_tid=9)
        clear_open_flags(pid, iid)           # the rebuild's delete
        assert len(list_review_log(pid)) == 1

    def test_endpoints(self, site):
        pid, iid, cid, ln, ls = site
        r = client.post(f"/api/projects/{pid}/review-log", json={
            "camera_id": cid, "card_key": "cardX", "item_key": "tid:3",
            "action": "not_a_vehicle", "source_tid": 3})
        assert r.status_code == 200
        rows = client.get(f"/api/projects/{pid}/review-log",
                          params={"card_key": "cardX"}).json()["rows"]
        assert len(rows) == 1 and rows[0]["action"] == "not_a_vehicle"
