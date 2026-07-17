"""C-polish stage 1 (plan_C_polish_2026-07-14): two-pass cancel, the S5
multi-window union, and the processing-status merge."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection, get_v3_run_state

from backend.tests.test_two_pass_stage34 import _StubDetector, _mk_cam, _mk_video

client = TestClient(app)


@pytest.fixture()
def proj():
    pid = client.post("/api/projects", json={"name": "cpolish-test"}).json()["project_id"]
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


class TestCancelEndpoint:
    def test_404_when_disabled(self, proj, monkeypatch):
        import backend.routers.two_pass as tpr
        monkeypatch.setattr(tpr, "TWO_PASS_ENABLED", False)
        r = client.post(f"/api/projects/{proj}/intersections/1/two-pass/cancel")
        assert r.status_code == 404

    def test_409_when_idle(self, proj, monkeypatch):
        import backend.routers.two_pass as tpr
        monkeypatch.setattr(tpr, "TWO_PASS_ENABLED", True)
        r = client.post(f"/api/projects/{proj}/intersections/1/two-pass/cancel")
        assert r.status_code == 409
        assert "no running" in r.json()["detail"]

    def test_sets_flag_on_running_job(self, proj, monkeypatch):
        import backend.routers.two_pass as tpr
        monkeypatch.setattr(tpr, "TWO_PASS_ENABLED", True)
        key = (proj, "i1")
        tpr._jobs[key] = {"status": "running", "kind": "process"}
        try:
            r = client.post(f"/api/projects/{proj}/intersections/1/two-pass/cancel")
            assert r.status_code == 200
            assert tpr._jobs[key]["cancel_requested"] is True
        finally:
            tpr._jobs.pop(key, None)


class TestProcessCancel:
    def test_cancel_between_windows(self, proj, monkeypatch):
        """First window completes; the stub sets the cancel flag; the second
        window never runs; state lands 'cancelled' with one completed result."""
        import backend.routers.two_pass as tpr
        import backend.services.two_pass as tps
        iid, cid = _mk_cam(proj)
        key = (proj, f"i{iid}")
        calls = []

        def fake_pass2(pid, camera_id, *, variant, workdir, apply=False,
                       should_cancel=None):
            calls.append(variant)
            tpr._jobs[key]["cancel_requested"] = True
            return {"camera_id": camera_id, "intersection_id": iid,
                    "variant": variant, "borderline": [], "applied": apply}

        monkeypatch.setattr(tps, "run_pass2", fake_pass2)
        tpr._jobs[key] = {"status": "running", "kind": "process"}
        body = tpr.ProcessBody(windows={cid: "w1", cid + 1000: "w2"}, apply=False)
        # windows dict drives the loop directly; camera validity was the
        # endpoint's concern and is bypassed on purpose here.
        tpr._run_process_job(proj, iid, body)
        assert calls == ["w1"]
        assert tpr._jobs[key]["status"] == "cancelled"
        assert len(tpr._jobs[key]["completed"]) == 1
        # the chip's "M of N windows applied" line (stage-2 render)
        assert tpr._jobs[key]["completed_windows"] == 1
        assert tpr._jobs[key]["window_total"] == 2
        assert get_v3_run_state(proj, iid)["status"] == "cancelled"
        tpr._jobs.pop(key, None)

    def test_pass1_ingest_cancel_is_resumable(self, proj, tmp_path, monkeypatch):
        """Cancel mid-chunk == the crash-resume path: open part unreadable,
        resume re-enters at the chunk start and completes."""
        import backend.services.detector as det
        import backend.services.two_pass as tp
        from backend.services.pass2_replay import JobCancelled
        from backend.services.two_pass import run_pass1, _camera_parquet
        vid = tmp_path / "tiny.mp4"
        _mk_video(vid, n_frames=60)
        iid, cid = _mk_cam(proj, video={
            "path": str(vid), "fps": 10.0, "total_frames": 60,
            "file_size_bytes": vid.stat().st_size,
            "recording_start_datetime": "2026-05-12T07:00:00"})
        _StubDetector.calls = []
        _StubDetector.fail_at_frame = None
        monkeypatch.setattr(det, "VehicleDetector", _StubDetector)
        monkeypatch.setattr(tp, "PASS1_INGEST_CHUNK_SECONDS", 2.0)  # 20-frame chunks

        with pytest.raises(JobCancelled):
            run_pass1(proj, cid, variant="study_0700", start_frame=0,
                      end_frame=60,
                      should_cancel=lambda: len(_StubDetector.calls) >= 30)
        pq = _camera_parquet(proj, cid, "study_0700")
        assert not pq.exists()
        assert len(list(pq.parent.glob("*.part*.parquet"))) == 1  # chunk 0 only

        _StubDetector.calls = []
        res = run_pass1(proj, cid, variant="study_0700", start_frame=0,
                        end_frame=60, resume=True)
        assert len(_StubDetector.calls) == 40          # chunks 1-2 re-detected
        assert pq.exists()
        meta = json.loads((tp.tracks_dir(pq) / "meta.json").read_text())
        assert meta["complete"] is True

    def test_pass1_cache_cancel_flushes_highwater(self, proj, tmp_path, monkeypatch):
        """Cache-path cancel flushes count.txt so resume loses nothing."""
        import backend.services.detector as det
        import backend.services.two_pass as tp
        from backend.services.pass2_replay import JobCancelled
        from backend.services.two_pass import run_pass1, _camera_parquet
        vid = tmp_path / "tiny.mp4"
        _mk_video(vid, n_frames=60)
        iid, cid = _mk_cam(proj, video={
            "path": str(vid), "fps": 10.0, "total_frames": 60,
            "file_size_bytes": vid.stat().st_size,
            "recording_start_datetime": "2026-05-12T07:00:00"})
        _StubDetector.calls = []
        _StubDetector.fail_at_frame = None
        monkeypatch.setattr(det, "VehicleDetector", _StubDetector)
        monkeypatch.setattr(tp, "PASS1_INGEST_CHUNK_SECONDS", 2.0)
        run_pass1(proj, cid, variant="study_0700", start_frame=0, end_frame=60)
        pq = _camera_parquet(proj, cid, "study_0700")

        # now the cache exists: re-dump via the cache path, cancel partway
        n = {"seen": 0}

        def cancel_after_20():
            n["seen"] += 1
            return n["seen"] > 20

        with pytest.raises(JobCancelled):
            run_pass1(proj, cid, variant="study_0700", start_frame=0,
                      end_frame=60, resume=False, should_cancel=cancel_after_20)
        tdir = tp.tracks_dir(pq)
        assert not json.loads((tdir / "meta.json").read_text()).get("complete")
        assert (tdir / "count.txt").exists()           # flushed at the cancel
        res = run_pass1(proj, cid, variant="study_0700", start_frame=0,
                        end_frame=60, resume=True)
        assert json.loads((tdir / "meta.json").read_text())["complete"] is True


class TestS5Union:
    def test_union_across_windows_dedup_max_impact(self, proj):
        from backend.services.two_pass import rebuild_s5_union
        iid, cid = _mk_cam(proj)
        l1 = _add_leg(proj, cid, "N")
        l2 = _add_leg(proj, cid, "S")
        mk = lambda raw, exp: {"cell": [l1, l2], "raw": raw, "expected": exp,
                               "threshold": exp * 1.3, "merges": raw > exp * 1.3}
        results = [
            {"camera_id": cid, "borderline": [mk(10, 8.0)]},                  # impact 2
            {"camera_id": cid, "borderline": [mk(20, 8.0),                    # same cell, impact 12
                                              {"cell": [l2, l1], "raw": 5,
                                               "expected": 4.0, "threshold": 5.2,
                                               "merges": False}]},            # 2nd cell
        ]
        rebuild_s5_union(proj, iid, results)
        conn = get_connection(proj)
        rows = conn.execute(
            "SELECT impact FROM review_flags WHERE intersection_id = ? AND "
            "subtype = 'merge_borderline' ORDER BY impact DESC", (iid,)).fetchall()
        conn.close()
        assert len(rows) == 2                       # both cells, deduped
        assert rows[0][0] == pytest.approx(12.0)    # max-impact instance kept


class TestProcessingStatusMerge:
    def test_two_pass_block_merged(self, proj):
        import backend.routers.two_pass as tpr
        iid, cid = _mk_cam(proj)
        key = (proj, f"i{iid}")
        tpr._jobs[key] = {"status": "running", "kind": "process",
                          "stage": "pass2", "current_camera": cid,
                          "current_variant": "study_0700",
                          "window_index": 2, "window_total": 3,
                          "results": [{"huge": "payload"}]}
        try:
            r = client.get(
                f"/api/projects/{proj}/intersections/{iid}/processing/status")
            assert r.status_code == 200
            tp = r.json().get("two_pass")
            assert tp is not None
            assert tp["stage"] == "pass2"
            assert (tp["window_index"], tp["window_total"]) == (2, 3)
            assert "results" not in tp              # whitelist strips payloads
        finally:
            tpr._jobs.pop(key, None)

    def test_absent_when_no_job(self, proj):
        iid, cid = _mk_cam(proj)
        r = client.get(f"/api/projects/{proj}/intersections/{iid}/processing/status")
        assert r.status_code == 200
        assert "two_pass" not in r.json()
