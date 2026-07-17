"""Stage 3.4 — the operator surface (plan_stage34_operator_surface_2026-07-13).

Covers: the trim→window derivation contract (corridor dump numbers as
fixtures), dump completeness statuses, the pass-2 sidecar calibration
fingerprint, detect-at-ingest with chunked parts + resume, and the plan/
process endpoint gates. Heavier fidelity (replay parity, corridor MAE) is
gated elsewhere (pass2_parity, the §2d scoreboard) and NOT re-run here.
"""
import json
from datetime import datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection

client = TestClient(app)


def _mk_cam(pid, *, video: dict | None = None):
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES ('T', '2026-05-12', 0, 4, '2026-05-12')").lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'c', 0, '2026-05-12')", (iid,)).lastrowid
        if video is not None:
            conn.execute(
                "INSERT INTO videos (camera_id, sort_order, path, filename, fps, "
                "width, height, total_frames, duration_seconds, file_size_bytes, "
                "recording_start_datetime, added_at, content_hash, "
                "content_hash_method) VALUES (?,0,?,?,?,64,64,?,?,?,?,?,?,?)",
                (cid, video["path"], video.get("filename", "v.mp4"), video["fps"],
                 video["total_frames"], video["total_frames"] / video["fps"],
                 video.get("file_size_bytes", 1), video["recording_start_datetime"],
                 "2026-05-12", video.get("content_hash"),
                 "blake2b-128m-v1" if video.get("content_hash") else None))
    conn.close()
    return iid, cid


@pytest.fixture()
def proj():
    pid = client.post("/api/projects", json={"name": "stage34-test"}).json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


class TestTrimWindowDerivation:
    """The naming contract, verified against the CORRIDOR dump metas —
    these exact numbers are what the gated dumps on disk carry."""

    def _derive(self, pid, iid, trims):
        from backend.database import add_trim
        for s, e in trims:
            add_trim(pid, iid, s, e)
        from backend.services.two_pass import derive_windows
        return derive_windows(pid, iid)

    def test_cam1_shape_10fps(self, proj):
        # cam1/4/5: 10 fps, recording start 00:00:02, trim 07:00–09:00
        # -> study_0700 [251980, 323980] (the on-disk dump meta).
        iid, cid = _mk_cam(proj, video={
            "path": "x.mp4", "fps": 10.0, "total_frames": 864046,
            "recording_start_datetime": "2026-05-12T00:00:02"})
        w = self._derive(proj, iid, [("07:00:00", "09:00:00")])
        assert len(w) == 1
        assert w[0]["variant"] == "study_0700"
        assert (w[0]["start_frame"], w[0]["end_frame"]) == (251980, 323980)

    def test_cam2_shape_25fps(self, proj):
        iid, cid = _mk_cam(proj, video={
            "path": "x.mp4", "fps": 25.0, "total_frames": 2161088,
            "recording_start_datetime": "2026-05-12T00:00:02"})
        w = self._derive(proj, iid, [("07:00:00", "09:00:00"),
                                     ("16:00:00", "18:00:00")])
        assert [x["variant"] for x in w] == ["study_0700", "study_1600"]
        assert (w[0]["start_frame"], w[0]["end_frame"]) == (629950, 809950)
        assert (w[1]["start_frame"], w[1]["end_frame"]) == (1439950, 1619950)

    def test_cam3_full_day_unclamped_negative_start(self, proj):
        # 00:00:00 trim against a 00:00:02 recording start -> frame −20,
        # exactly the gated study_0000 dump. '24:00:00' must parse.
        iid, cid = _mk_cam(proj, video={
            "path": "x.mp4", "fps": 10.0, "total_frames": 864044,
            "recording_start_datetime": "2026-05-12T00:00:02"})
        w = self._derive(proj, iid, [("00:00:00", "24:00:00")])
        assert w[0]["variant"] == "study_0000"
        assert (w[0]["start_frame"], w[0]["end_frame"]) == (-20, 863980)

    def test_end_before_start_means_past_midnight(self, proj):
        iid, cid = _mk_cam(proj, video={
            "path": "x.mp4", "fps": 10.0, "total_frames": 864000,
            "recording_start_datetime": "2026-05-12T22:00:00"})
        w = self._derive(proj, iid, [("23:00:00", "01:00:00")])
        assert (w[0]["start_frame"], w[0]["end_frame"]) == (36000, 108000)


class TestDumpStatus:
    def _mk_dump(self, tmp_path, frames, rows_frames, complete):
        pq = tmp_path / "study_0700.parquet"
        tdir = tmp_path / "study_0700.tracks"
        tdir.mkdir()
        meta = {"format": 2, "frames": frames, "backend": "bytetrack"}
        if complete:
            meta["complete"] = True
        (tdir / "meta.json").write_text(json.dumps(meta))
        rows = np.zeros((max(len(rows_frames), 1), 8), dtype=np.float32)
        for i, f in enumerate(rows_frames):
            rows[i, 1] = f
        np.save(tdir / "rows.npy", rows)
        (tdir / "count.txt").write_text(str(len(rows_frames)))
        return pq

    def test_marker_wins(self, tmp_path):
        from backend.services.two_pass import dump_status
        pq = self._mk_dump(tmp_path, [0, 72000], [10], complete=True)
        assert dump_status(pq, 0, 72000, 10.0)["status"] == "ready"

    def test_legacy_tail_tolerance(self, tmp_path):
        # cam3's gated dump ends 118 s before the window edge (empty
        # midnight road) — the legacy heuristic must accept up to 300 s.
        from backend.services.two_pass import dump_status
        pq = self._mk_dump(tmp_path, [0, 72000], [100, 72000 - 1181],
                           complete=False)
        assert dump_status(pq, 0, 72000, 10.0)["status"] == "ready"

    def test_legacy_partial(self, tmp_path):
        from backend.services.two_pass import dump_status
        (tmp_path / "b").mkdir()
        pq = self._mk_dump(tmp_path / "b", [0, 72000], [100, 30000], complete=False)
        assert dump_status(pq, 0, 72000, 10.0)["status"] == "partial"

    def test_missing_and_mismatch(self, tmp_path):
        from backend.services.two_pass import dump_status
        assert dump_status(tmp_path / "none.parquet", 0, 10, 10.0)["status"] == "missing"
        (tmp_path / "b").mkdir()
        pq = self._mk_dump(tmp_path / "b", [0, 30000], [100], complete=True)
        # dump covers [0,30000) but the trim asks [0,72000) -> mismatch
        assert dump_status(pq, 0, 72000, 10.0)["status"] == "mismatch"

    def test_slack_absorbs_small_trim_edits(self, tmp_path):
        from backend.services.two_pass import dump_status
        (tmp_path / "b").mkdir()
        pq = self._mk_dump(tmp_path / "b", [-20, 863980], [100, 863970],
                           complete=True)
        # clamped-start (0) and a 2 s-short end still match the cam3 dump
        assert dump_status(pq, 0, 863990, 10.0)["status"] == "ready"


class TestCalibFingerprint:
    def test_stable_then_invalidated_by_operator_edits(self, proj):
        from backend.services.two_pass import calib_fingerprint
        iid, cid = _mk_cam(proj, video={
            "path": "x.mp4", "fps": 10.0, "total_frames": 100,
            "recording_start_datetime": "2026-05-12T00:00:00"})
        f0 = calib_fingerprint(proj, cid)
        assert f0 == calib_fingerprint(proj, cid)      # deterministic

        conn = get_connection(proj)                     # calibration knob edit
        with conn:
            conn.execute("UPDATE cameras SET calib_tracker_match_threshold = 0.9 "
                         "WHERE camera_id = ?", (cid,))
        conn.close()
        f1 = calib_fingerprint(proj, cid)
        assert f1 != f0

        conn = get_connection(proj)                     # leg geometry edit
        with conn:
            conn.execute(
                "INSERT INTO legs (camera_id, label, cardinal_direction, "
                "sort_order, origin_zone, reference_heading) "
                "VALUES (?, 'N', 'N', 0, '[]', 90.0)", (cid,))
        conn.close()
        f2 = calib_fingerprint(proj, cid)
        assert f2 != f1


class _StubDetector:
    """Deterministic detector: one moving box per frame, fails on demand."""
    calls: list = []
    fail_at_frame: int | None = None

    def __init__(self, **kwargs):
        pass

    def detect(self, frame):
        fidx = len(type(self).calls)
        type(self).calls.append(fidx)
        if (type(self).fail_at_frame is not None
                and len(type(self).calls) > type(self).fail_at_frame):
            raise RuntimeError("stub detector killed (test)")
        x = 5.0 + (fidx % 50)
        return [{"bbox": [x, 10.0, x + 12.0, 22.0], "center": [x + 6, 16.0],
                 "class_id": 2, "class_name": "car", "confidence": 0.9,
                 "bbox_width": 12.0, "bbox_height": 12.0, "bbox_area": 144.0,
                 "is_vehicle": True}]


def _mk_video(path, n_frames=60, fps=10):
    import cv2
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 64))
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    for i in range(n_frames):
        frame[:] = (i % 255, 100, 50)
        vw.write(frame)
    vw.release()


class TestDetectAtIngest:
    def test_first_run_detect_cache_dump_then_rerun_uses_cache(
            self, proj, tmp_path, monkeypatch):
        import backend.services.detector as det
        import backend.services.two_pass as tp
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

        res = run_pass1(proj, cid, variant="study_0700",
                        start_frame=0, end_frame=60)
        assert res["rows"] > 0
        pq = _camera_parquet(proj, cid, "study_0700")
        assert pq.exists() and pq.with_suffix(".meta.json").exists()
        meta = json.loads(pq.with_suffix(".meta.json").read_text())
        assert meta["windows"] == [[0, 60]]
        assert not list(pq.parent.glob("*.part*"))       # parts merged + gone
        dmeta = json.loads((tp.tracks_dir(pq) / "meta.json").read_text())
        assert dmeta["complete"] is True
        n_detect_calls = len(_StubDetector.calls)
        assert n_detect_calls == 60

        # Re-run (no resume): cache path now — the detector must NOT run.
        res2 = run_pass1(proj, cid, variant="study_0700",
                         start_frame=0, end_frame=60, resume=False)
        assert len(_StubDetector.calls) == n_detect_calls
        assert res2["rows"] == res["rows"]

    def test_chunk_resume_reenters_at_failed_chunk(self, proj, tmp_path, monkeypatch):
        import backend.services.detector as det
        import backend.services.two_pass as tp
        from backend.services.two_pass import run_pass1, _camera_parquet
        vid = tmp_path / "tiny2.mp4"
        _mk_video(vid, n_frames=60)
        iid, cid = _mk_cam(proj, video={
            "path": str(vid), "fps": 10.0, "total_frames": 60,
            "file_size_bytes": vid.stat().st_size,
            "recording_start_datetime": "2026-05-12T07:00:00"})
        _StubDetector.calls = []
        _StubDetector.fail_at_frame = 30      # dies mid-chunk 1 (frames 20–39)
        monkeypatch.setattr(det, "VehicleDetector", _StubDetector)
        monkeypatch.setattr(tp, "PASS1_INGEST_CHUNK_SECONDS", 2.0)

        with pytest.raises(RuntimeError):
            run_pass1(proj, cid, variant="study_0700", start_frame=0, end_frame=60)
        pq = _camera_parquet(proj, cid, "study_0700")
        assert not pq.exists()                          # no merge yet
        parts = sorted(pq.parent.glob("*.part*.parquet"))
        assert len(parts) == 1                           # only chunk 0 closed

        _StubDetector.calls = []
        _StubDetector.fail_at_frame = None
        res = run_pass1(proj, cid, variant="study_0700",
                        start_frame=0, end_frame=60, resume=True)
        # resumed at chunk 1: only frames 20..59 detected on the second run
        assert len(_StubDetector.calls) == 40
        assert pq.exists()
        meta = json.loads(pq.with_suffix(".meta.json").read_text())
        assert meta["windows"] == [[0, 60]]
        dmeta = json.loads((tp.tracks_dir(pq) / "meta.json").read_text())
        assert dmeta["complete"] is True
        # the merged cache covers all 60 frames' detections (20 from part 0
        # written pre-crash + 40 post-resume)
        from backend.services.detection_cache import DetectionCacheReader
        frames = [f for f, _ in DetectionCacheReader(pq).iter_frames()]
        assert frames == list(range(60))


class TestStage34Endpoints:
    def test_plan_404_when_disabled(self, proj, monkeypatch):
        import backend.routers.two_pass as tpr
        monkeypatch.setattr(tpr, "TWO_PASS_ENABLED", False)
        iid, cid = _mk_cam(proj)
        r = client.get(f"/api/projects/{proj}/intersections/{iid}/two-pass/plan")
        assert r.status_code == 404

    def test_plan_derives_from_trims(self, proj, monkeypatch):
        import backend.routers.two_pass as tpr
        monkeypatch.setattr(tpr, "TWO_PASS_ENABLED", True)
        from backend.database import add_trim
        iid, cid = _mk_cam(proj, video={
            "path": "x.mp4", "fps": 10.0, "total_frames": 864046,
            "recording_start_datetime": "2026-05-12T00:00:02",
            "content_hash": "deadbeef" * 8})
        add_trim(proj, iid, "07:00:00", "09:00:00")
        r = client.get(f"/api/projects/{proj}/intersections/{iid}/two-pass/plan")
        assert r.status_code == 200
        w = r.json()["windows"]
        assert len(w) == 1
        assert w[0]["variant"] == "study_0700"
        assert w[0]["dump"]["status"] == "missing"
        assert w[0]["cache"] == "missing"
        assert w[0]["pass2"] == "missing"

    def test_process_without_windows_requires_intersection(self, proj, monkeypatch):
        import backend.routers.two_pass as tpr
        monkeypatch.setattr(tpr, "TWO_PASS_ENABLED", True)
        r = client.post(f"/api/projects/{proj}/intersections/999/two-pass/process",
                        json={})
        assert r.status_code == 404
