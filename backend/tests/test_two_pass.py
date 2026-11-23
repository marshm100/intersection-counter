"""Stage-3 two-pass wiring: the flag gate and the missing-dump guard.
The counting-path fidelity itself is gated by scripts/pass2_parity.py (A2)
and the cam5 product-path run (7.1% MAE == the A4a benchmark, stage-3 doc)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection

client = TestClient(app)


def _mk_cam(pid):
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES ('T', '2026-07-10', 0, 4, '2026-07-10')").lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'c', 0, '2026-07-10')", (iid,)).lastrowid
    conn.close()
    return cid


@pytest.fixture()
def proj():
    pid = client.post("/api/projects", json={"name": "twopass-test"}).json()["project_id"]
    cid = _mk_cam(pid)
    yield pid, cid
    client.delete(f"/api/projects/{pid}")


class TestTwoPassGate:
    def test_disabled_404(self, proj, monkeypatch):
        # With the flag off (default flipped ON 2026-07-13 post-dry-run; the
        # off-mode remains the supported fallback) the legacy flow must be
        # untouched and the endpoints invisible.
        import backend.routers.two_pass as tp
        monkeypatch.setattr(tp, "TWO_PASS_ENABLED", False)
        pid, cid = proj
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/two-pass/run",
                        json={"variant": "study_0700"})
        assert r.status_code == 404
        assert "disabled" in r.json()["detail"]
        assert client.get(
            f"/api/projects/{pid}/cameras/{cid}/two-pass/status").status_code == 404

    def test_missing_dump_raises_actionable(self, proj):
        pid, cid = proj
        from backend.services.two_pass import run_pass2
        with pytest.raises(ValueError):
            # no video row on the synthetic camera -> actionable error, and a
            # camera WITH video but no dump raises FileNotFoundError ("run
            # pass 1 first") — both surface via /two-pass/status as error.
            run_pass2(pid, cid, variant="study_0700", workdir="unused")


class TestWindowScopedApply:
    def test_three_windows_apply_without_wiping_each_other(self, tmp_path):
        import sqlite3
        from backend.services.two_pass import _apply_window_events

        def _mk(path, events):
            c = sqlite3.connect(path)
            c.execute("CREATE TABLE vehicle_events (event_id INTEGER PRIMARY KEY, "
                      "camera_id INT, timestamp_video REAL, movement TEXT)")
            with c:
                c.executemany("INSERT INTO vehicle_events "
                              "(camera_id, timestamp_video, movement) VALUES (?,?,?)",
                              events)
            c.close()

        proj = tmp_path / "proj.db"
        # live: stale events in all three windows + another camera's event
        _mk(proj, [(2, 100.0, "old_a"), (2, 500.0, "old_b"), (2, 900.0, "old_c"),
                   (3, 100.0, "other_cam")])
        wA = tmp_path / "wA.db"; _mk(wA, [(2, 110.0, "new_a")])
        wB = tmp_path / "wB.db"; _mk(wB, [(2, 510.0, "new_b1"), (2, 511.0, "new_b2")])

        _apply_window_events(proj, wA, 2, 0.0, 400.0)
        _apply_window_events(proj, wB, 2, 400.0, 800.0)

        c = sqlite3.connect(proj)
        rows = sorted(r[0] for r in c.execute(
            "SELECT movement FROM vehicle_events WHERE camera_id = 2"))
        other = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id = 3").fetchone()[0]
        c.close()
        # window A replaced, window B replaced, window C (900s) UNTOUCHED
        assert rows == ["new_a", "new_b1", "new_b2", "old_c"]
        assert other == 1


class TestReviewSurvivesReapply:
    """Phase 0 (2026-10-15): a re-apply keeps the reviewer's adds, edits and
    rejects; a ruling on a track the new window lacks is reported."""

    @staticmethod
    def _mk(path, events):
        import sqlite3
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE vehicle_events (event_id INTEGER PRIMARY KEY, "
                  "camera_id INT, timestamp_video REAL, vehicle_track_id INT, "
                  "origin_leg_id INT, destination_leg_id INT, movement TEXT, "
                  "vehicle_class TEXT, rejected INT DEFAULT 0, manually_edited INT DEFAULT 0)")
        with c:
            c.executemany("INSERT INTO vehicle_events (camera_id, timestamp_video, "
                          "vehicle_track_id, origin_leg_id, destination_leg_id, movement, "
                          "vehicle_class, rejected, manually_edited) VALUES (?,?,?,?,?,?,?,?,?)",
                          events)
        c.close()

    def test_adds_edits_rejects_survive(self, tmp_path):
        import sqlite3
        from backend.services.two_pass import _apply_window_events
        proj = tmp_path / "proj.db"
        self._mk(proj, [
            (2, 10.0, 7, 1, 2, "left", "car", 0, 1),     # edited: movement changed
            (2, 20.0, 8, 1, 3, "through", "car", 1, 1),  # rejected by the reviewer
            (2, 30.0, 9, 1, 3, "through", "car", 0, 0),  # untouched
            (2, 40.0, -1, 2, 4, "right", "car", 0, 1),   # ADDED by the reviewer
            (2, 50.0, 99, 1, 3, "through", "car", 1, 1),  # ruling on a vanishing track
        ])
        w = tmp_path / "w.db"
        self._mk(w, [
            (2, 11.0, 7, 1, 3, "through", "car", 0, 0),
            (2, 21.0, 8, 1, 3, "through", "car", 0, 0),
            (2, 31.0, 9, 1, 2, "left", "car", 0, 0),
        ])
        stats = _apply_window_events(proj, w, 2, 0.0, 100.0)
        c = sqlite3.connect(proj)
        rows = {r[0]: r[1:] for r in c.execute(
            "SELECT vehicle_track_id, movement, destination_leg_id, rejected, manually_edited "
            "FROM vehicle_events WHERE camera_id = 2")}
        c.close()
        assert rows[7] == ("left", 2, 0, 1)        # the reviewer's movement wins
        assert rows[8][2] == 1                     # still rejected
        assert rows[9] == ("left", 2, 0, 0)        # machine row replaced as before
        assert rows[-1] == ("right", 4, 0, 1)      # the added car is kept
        assert 99 not in rows
        assert stats == {"added_kept": 1, "edits_replayed": 2, "vanished": [99]}

    def test_reapply_twice_does_not_duplicate_adds(self, tmp_path):
        import sqlite3
        from backend.services.two_pass import _apply_window_events
        proj = tmp_path / "proj.db"
        self._mk(proj, [(2, 40.0, -1, 2, 4, "right", "car", 0, 1)])
        w = tmp_path / "w.db"
        self._mk(w, [(2, 11.0, 7, 1, 3, "through", "car", 0, 0)])
        _apply_window_events(proj, w, 2, 0.0, 100.0)
        _apply_window_events(proj, w, 2, 0.0, 100.0)
        c = sqlite3.connect(proj)
        n_add = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE vehicle_track_id = -1").fetchone()[0]
        n = c.execute("SELECT COUNT(*) FROM vehicle_events").fetchone()[0]
        c.close()
        assert (n_add, n) == (1, 2)


class TestStage33Endpoints:
    def test_pass1_and_process_disabled_404(self, proj, monkeypatch):
        import backend.routers.two_pass as tp
        monkeypatch.setattr(tp, "TWO_PASS_ENABLED", False)
        pid, cid = proj
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/two-pass/pass1",
                        json={"variant": "v", "start_frame": 0, "end_frame": 10})
        assert r.status_code == 404
        r = client.post(f"/api/projects/{pid}/intersections/1/two-pass/process",
                        json={"windows": {str(cid): "v"}})
        assert r.status_code == 404

    def test_process_rejects_foreign_camera(self, proj, monkeypatch):
        import backend.routers.two_pass as tp
        monkeypatch.setattr(tp, "TWO_PASS_ENABLED", True)
        pid, cid = proj
        r = client.post(f"/api/projects/{pid}/intersections/999/two-pass/process",
                        json={"windows": {str(cid): "v"}})
        assert r.status_code == 409
        assert "not on intersection" in r.json()["detail"]

class TestApplyUnderWindowName:
    def test_linked_window_is_adjudicated_under_its_own_name(self, proj, tmp_path,
                                                             monkeypatch):
        """The linker renames the dump to lk_study_0700; the apply gate, its
        dispositions and trail must still see study_0700 (2026-09-30: a
        force_once on the window was never seen and the reprocess stood down)."""
        import json
        from pathlib import Path
        import numpy as np
        import backend.config as cfg
        import backend.services.tracklet_linker as tl
        import backend.services.two_pass as tp
        pid, cid = proj
        conn = get_connection(pid)
        with conn:
            conn.execute(
                "INSERT INTO videos (camera_id, sort_order, path, filename, fps, width, "
                "height, total_frames, duration_seconds, file_size_bytes, "
                "recording_start_datetime, added_at) VALUES "
                "(?, 0, 'v.mp4', 'v.mp4', 10, 640, 480, 100, 10, 1, "
                "'2026-07-10T07:00:00', '2026-07-10')", (cid,))
        conn.close()
        tdir = tmp_path / "study_0700.tracks"
        tdir.mkdir()
        (tdir / "count.txt").write_text("0")
        (tdir / "meta.json").write_text(json.dumps({"frames": [0, 100]}))
        monkeypatch.setattr(tp, "resolve_content_hash", lambda *a, **k: ("h", "m"))
        monkeypatch.setattr(tp, "tracks_dir", lambda p: tdir)
        monkeypatch.setattr(tp, "load_dump", lambda d: np.zeros((0, 8)))
        monkeypatch.setattr(cfg, "TRACKLET_LINKER", True)
        monkeypatch.setattr(
            tl, "ensure_linked_dump",
            lambda pid_, cid_, v, fps, td, rows, meta, frame_size=None:
                (f"lk_{v}", td, meta, rows))
        # reuse path: a prior compute of the (renamed) dump is valid
        wd = tmp_path / "wd"
        wd.mkdir()
        (wd / f"twopass_cam{cid}_lk_study_0700.db").write_bytes(b"")
        (wd / f"twopass_cam{cid}_lk_study_0700.stats.json").write_text(
            json.dumps({"result": {"events": 0}}))
        monkeypatch.setattr(tp, "sidecar_reusable", lambda *a, **k: True)
        seen = {}

        def fake_gate(project_id, camera_id, intersection_id, variant, out_db, *a):
            seen["variant"], seen["out_db"] = variant, Path(out_db).name
            return {"applied": True}
        monkeypatch.setattr(tp, "_gated_finish_apply", fake_gate)
        tp.run_pass2(pid, cid, variant="study_0700", workdir=wd, apply=True)
        assert seen["variant"] == "study_0700"
        assert seen["out_db"] == f"twopass_cam{cid}_lk_study_0700.db"


class TestLinkerFailureFlagsTheRun:
    """Operator ruling 2026-11-20: a linker error flags the run for re-run; it
    is never applied, never cached, and never falls back to deleted rules."""

    def test_flag_helper_marks_and_uncaches(self, tmp_path):
        import backend.services.two_pass as tp
        sp = tmp_path / "x.stats.json"
        sp.write_text("{}")
        res = tp.flag_linker_failed({"applied": True}, "ValueError: boom", sp)
        assert res["linker_failed"] == "ValueError: boom"
        assert res["applied"] is False and not sp.exists()

    def test_failure_blocks_reuse_and_apply(self, proj, tmp_path, monkeypatch):
        import json
        import numpy as np
        import pytest
        import backend.config as cfg
        import backend.services.tracklet_linker as tl
        import backend.services.two_pass as tp
        pid, cid = proj
        conn = get_connection(pid)
        with conn:
            conn.execute(
                "INSERT INTO videos (camera_id, sort_order, path, filename, fps, width, "
                "height, total_frames, duration_seconds, file_size_bytes, "
                "recording_start_datetime, added_at) VALUES "
                "(?, 0, 'v.mp4', 'v.mp4', 10, 640, 480, 100, 10, 1, "
                "'2026-07-10T07:00:00', '2026-07-10')", (cid,))
        conn.close()
        tdir = tmp_path / "study_0700.tracks"
        tdir.mkdir()
        (tdir / "count.txt").write_text("0")
        (tdir / "meta.json").write_text(json.dumps({"frames": [0, 100]}))
        monkeypatch.setattr(tp, "resolve_content_hash", lambda *a, **k: ("h", "m"))
        monkeypatch.setattr(tp, "tracks_dir", lambda p: tdir)
        monkeypatch.setattr(tp, "load_dump", lambda d: np.zeros((0, 8)))
        monkeypatch.setattr(cfg, "TRACKLET_LINKER", True)

        def boom(*a, **k):
            raise RuntimeError("linker exploded")
        monkeypatch.setattr(tl, "ensure_linked_dump", boom)
        # a prior, reusable result for the UNLINKED variant must not be used
        wd = tmp_path / "wd"
        wd.mkdir()
        (wd / f"twopass_cam{cid}_study_0700.db").write_bytes(b"")
        (wd / f"twopass_cam{cid}_study_0700.stats.json").write_text(
            json.dumps({"result": {"events": 0}}))
        monkeypatch.setattr(tp, "sidecar_reusable", lambda *a, **k: True)
        applied = []
        monkeypatch.setattr(tp, "_gated_finish_apply",
                            lambda *a, **k: applied.append(1) or {"applied": True})

        class Reached(Exception):
            pass

        def stop(*a, **k):
            raise Reached
        import sys
        import types
        fake = types.ModuleType("build_bank_gtfree")
        fake.build_gtfree_bank = stop
        monkeypatch.setitem(sys.modules, "build_bank_gtfree", fake)
        with pytest.raises(Reached):          # recomputed, not reused
            tp.run_pass2(pid, cid, variant="study_0700", workdir=wd, apply=True)
        assert not applied
