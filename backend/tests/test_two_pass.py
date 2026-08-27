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

class TestStopFractureCollapse:
    """Counted-path C: the red-light stop-fracture twin collapse."""

    def _arr(self, tracks):
        import numpy as np
        rows = []
        for tid, pts in tracks.items():
            for f, x, y in pts:
                rows.append([tid, f, x, y, 30.0, 20.0, 0.9, 2.0])
        rows.sort(key=lambda r: r[1])
        return np.array(rows, dtype=np.float32)

    def _fracture(self, twin_shift=(0.0, 0.0), twin_span=(120, 350)):
        # A: approaches, stops at (300,200), gap [100..400], resumes
        a = ([(f, 300.0 - 4 * (50 - f), 200.0) for f in range(0, 50)]
             + [(f, 300.0, 200.0) for f in range(50, 101)]
             + [(f, 300.0 + 3 * (f - 400), 200.0) for f in range(400, 460)])
        dx, dy = twin_shift
        b0, b1 = twin_span
        b = [(f, 300.0 + dx, 200.0 + dy) for f in range(b0, b1)]
        return {1.0: a, 2.0: b}

    def test_twin_collapses(self):
        from backend.services.two_pass import _collapse_stop_fractures
        arr = self._arr(self._fracture())
        n, pairs = _collapse_stop_fractures(arr, [], 25.0)
        assert n == 1 and pairs[0][:2] == [1, 2]
        assert not (arr[:, 0] == 2.0).any()      # B re-stamped into A

    def test_queue_neighbor_one_end_refused(self):
        # neighbor sits 34px away at birth (within STITCH_STAT_DIST) but
        # DRIVES OFF (death far from A's resume point) -> one-end pin only
        from backend.services.two_pass import _collapse_stop_fractures
        tracks = self._fracture()
        tracks[2.0] = [(f, 300.0 + 20.0, 200.0 + (f - 120) * 2.0)
                       for f in range(120, 350)]
        arr = self._arr(tracks)
        n, _ = _collapse_stop_fractures(arr, [], 25.0)
        assert n == 0

    def test_moving_loss_refused(self):
        # A was MOVING at the loss (no dwell) -> not the fracture class
        from backend.services.two_pass import _collapse_stop_fractures
        a = [(f, 4.0 * f, 200.0) for f in range(0, 101)]
        a += [(f, 4.0 * f, 200.0) for f in range(400, 460)]
        b = [(f, 400.0, 200.0) for f in range(120, 350)]
        arr = self._arr({1.0: a, 2.0: b})
        n, _ = _collapse_stop_fractures(arr, [], 25.0)
        assert n == 0

    def test_gate_chord_refused(self):
        # a drawn gate between A's rest point and the twin -> refuse
        from backend.services.two_pass import _collapse_stop_fractures
        arr = self._arr(self._fracture(twin_shift=(30.0, 0.0)))
        gate = [((315.0, 100.0), (315.0, 300.0))]
        n, _ = _collapse_stop_fractures(arr, gate, 25.0)
        assert n == 0

    def test_determinism(self):
        import numpy as np
        from backend.services.two_pass import _collapse_stop_fractures
        a1 = self._arr(self._fracture())
        a2 = self._arr(self._fracture())
        _collapse_stop_fractures(a1, [], 25.0)
        _collapse_stop_fractures(a2, [], 25.0)
        assert np.array_equal(a1, a2)

