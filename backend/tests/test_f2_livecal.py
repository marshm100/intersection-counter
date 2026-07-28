"""F2 live auto-cal perception view (plan_f2_livecal_2026-07-28).

Covers the service layer + endpoint semantics. The YOLO-heavy collector
path is exercised by live verification (repo convention: deferred-import
modules stay import-light for tests); the collector's hook CONTRACT is
pinned by a signature test so accidental breaks fail fast.
"""
import inspect
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection
from backend.services import auto_calibrator_v2 as AC

client = TestClient(app)


@pytest.fixture()
def cal_project():
    r = client.post("/api/projects", json={"name": "f2-livecal"})
    pid = r.json()["project_id"]
    conn = get_connection(pid)
    with conn:
        cur = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES ('F2', '2026-07-28', 0, 4, '2026-07-28')")
        iid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'cam', 0, '2026-07-28')", (iid,))
        cid = cur.lastrowid
    conn.close()
    yield pid, cid
    AC._JOBS.pop(cid, None)
    client.delete(f"/api/projects/{pid}")


def _seed_job(cid):
    AC._JOBS[cid] = {"job_id": "t", "camera_id": cid, "status": "running",
                     "progress_pct": 5.0, "phase": "collect_trajectories",
                     "cancel_requested": False, "updated_at": 0}


def _info(progress=0.5, with_frame=True):
    return {
        "frame_no": 150, "start_frame": 0, "end_frame": 300,
        "progress": progress, "active": 4, "finished": 11,
        "frame": (np.zeros((100, 160, 3), dtype=np.uint8) if with_frame else None),
        "tracked": [{"track_id": 1, "bbox": [10, 10, 40, 30],
                     "center": [25, 20]}],
        "trails": {1: [(20.0, 15.0), (25.0, 20.0)]},
    }


class TestRenderPreview:
    def test_populates_job_and_encodes_jpeg(self, cal_project):
        _pid, cid = cal_project
        _seed_job(cid)
        AC._render_preview(cid, _info(progress=0.5))
        job = AC._JOBS[cid]
        assert job["progress_pct"] == 47.5          # 5 + 85*0.5 — honest
        assert job["active_tracks"] == 4 and job["finished_tracks"] == 11
        assert job["preview_seq"] == 1
        assert job["preview_jpeg"][:2] == b"\xff\xd8"   # JPEG magic

    def test_seq_increments_and_status_excludes_bytes(self, cal_project):
        _pid, cid = cal_project
        _seed_job(cid)
        AC._render_preview(cid, _info(progress=0.1))
        AC._render_preview(cid, _info(progress=0.2))
        assert AC._JOBS[cid]["preview_seq"] == 2
        status = AC.get_status(cid)
        assert "preview_jpeg" not in status
        assert status["preview_seq"] == 2
        json.dumps(status)                          # JSON-safe payload
        assert AC.get_preview_jpeg(cid)[:2] == b"\xff\xd8"

    def test_no_frame_is_a_noop(self, cal_project):
        _pid, cid = cal_project
        _seed_job(cid)
        AC._render_preview(cid, _info(with_frame=False))
        assert "preview_jpeg" not in AC._JOBS[cid]
        assert "preview_seq" not in AC._JOBS[cid]


class TestPreviewEndpoint:
    def test_404_before_first_frame(self, cal_project):
        pid, cid = cal_project
        _seed_job(cid)
        r = client.get(f"/api/projects/{pid}/cameras/{cid}"
                       f"/calibration/suggestion/preview.jpg")
        assert r.status_code == 404

    def test_200_jpeg_after_render(self, cal_project):
        pid, cid = cal_project
        _seed_job(cid)
        AC._render_preview(cid, _info())
        r = client.get(f"/api/projects/{pid}/cameras/{cid}"
                       f"/calibration/suggestion/preview.jpg")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert r.headers["cache-control"] == "no-store"
        assert r.content[:2] == b"\xff\xd8"


class TestCollectorContract:
    def test_hook_signature_pinned(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        import auto_calibrate as A
        params = inspect.signature(A.collect_trajectories).parameters
        assert "on_progress" in params
        assert params["on_progress"].default is None    # legacy path intact
        assert "on_progress" in inspect.signature(A.run).parameters


class TestShapeSampleTracks:
    def test_downsample_and_min_points(self):
        acc = {1: {f: (float(f), 0.0) for f in range(100, 190)},   # 90 frames
               2: {f: (0.0, 0.0) for f in range(100, 110)}}        # 10 frames
        out = AC._shape_sample_tracks(acc, every=3, min_points=8)
        by_tid = {t["tid"]: t for t in out}
        assert 1 in by_tid
        assert 2 not in by_tid                       # 10/3 = 4 pts < 8
        pts = by_tid[1]["points"]
        assert len(pts) == 30                        # 90 frames / every-3rd
        assert pts[0] == [100, 100.0, 0.0]
        assert pts[1][0] == 103                      # stride respected

    def test_global_cap_keeps_longest(self):
        acc = {i: {f: (0.0, 0.0) for f in range(0, 30 * (i + 1), 1)}
               for i in range(5)}                    # lengths 30..150
        out = AC._shape_sample_tracks(acc, every=1, min_points=8, max_points=200)
        lens = [len(t["points"]) for t in out]
        assert lens == sorted(lens, reverse=True)    # longest first
        assert sum(lens) <= 200
        assert lens[0] == 150                        # the longest survived
