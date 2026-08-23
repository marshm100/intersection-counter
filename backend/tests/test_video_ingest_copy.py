"""Copy-in-by-default video ingest (decision 2026-08-23).

The machine transition stranded every project's videos on an unreachable
OneDrive because ingest recorded absolute paths wherever files lived. Policy
now: adding a video copies it into data/projects/<pid>/videos/ so a project
folder is a self-contained study; copy_in=false opts out and the row carries
linked=true for the UI badge.
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.routers import videos as videos_router
from backend.routers.videos import _ingest_path

client = TestClient(app)


@pytest.fixture()
def proj():
    pid = client.post("/api/projects", json={"name": "ingest-copy-test"}).json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _mk_video(path, n_frames=30, fps=10):
    import cv2
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 64))
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    for i in range(n_frames):
        frame[:] = (i % 255, 100, 50)
        vw.write(frame)
    vw.release()


class TestCopyInDefault:
    def test_default_copies_into_project_folder(self, proj, tmp_path):
        src = tmp_path / "Cam1_01_20260514_080000 Main St.mp4"
        _mk_video(src)
        r = client.post(f"/api/projects/{proj}/videos", json={"path": str(src)})
        assert r.status_code == 200
        row = r.json()
        managed_dir = (videos_router.PROJECTS_DIR / proj / "videos").resolve()
        assert managed_dir in __import__("pathlib").Path(row["path"]).resolve().parents
        assert row["linked"] is False
        assert src.exists()  # source untouched — it's a copy, not a move

    def test_opt_out_links_in_place(self, proj, tmp_path):
        src = tmp_path / "Cam2_01_20260514_080000 Elm St.mp4"
        _mk_video(src)
        r = client.post(f"/api/projects/{proj}/videos",
                        json={"path": str(src), "copy_in": False})
        assert r.status_code == 200
        row = r.json()
        assert row["path"] == str(src)
        assert row["linked"] is True
        assert not (videos_router.PROJECTS_DIR / proj / "videos" / src.name).exists()

    def test_readd_same_source_is_idempotent(self, proj, tmp_path):
        src = tmp_path / "Cam3_01_20260514_080000 Oak St.mp4"
        _mk_video(src)
        a = client.post(f"/api/projects/{proj}/videos", json={"path": str(src)}).json()
        b = client.post(f"/api/projects/{proj}/videos", json={"path": str(src)}).json()
        assert a["video_id"] == b["video_id"]
        copies = list((videos_router.PROJECTS_DIR / proj / "videos").glob(src.stem + "*"))
        assert len(copies) == 1

    def test_bulk_honors_copy_in(self, proj, tmp_path):
        s1 = tmp_path / "Cam4_01_20260514_080000 A.mp4"
        s2 = tmp_path / "Cam5_01_20260514_080000 B.mp4"
        _mk_video(s1); _mk_video(s2)
        r = client.post(f"/api/projects/{proj}/videos/bulk",
                        json={"paths": [str(s1), str(s2)], "copy_in": False})
        assert r.status_code == 200
        rows = [x for x in r.json()["results"] if "error" not in x]
        assert len(rows) == 2
        assert all(x["linked"] for x in rows)

    def test_list_endpoint_carries_linked(self, proj, tmp_path):
        src = tmp_path / "Cam6_01_20260514_080000 C.mp4"
        _mk_video(src)
        client.post(f"/api/projects/{proj}/videos", json={"path": str(src)})
        rows = client.get(f"/api/projects/{proj}/videos").json()
        assert rows and rows[0]["linked"] is False


class TestIngestPathCollisions:
    def test_same_name_same_size_reused(self, proj, tmp_path):
        src = tmp_path / "clip.mp4"
        _mk_video(src)
        a = _ingest_path(proj, str(src), True)
        b = _ingest_path(proj, str(src), True)
        assert a == b

    def test_same_name_different_size_gets_suffix(self, proj, tmp_path):
        d1 = tmp_path / "a"; d2 = tmp_path / "b"
        d1.mkdir(); d2.mkdir()
        s1 = d1 / "clip.mp4"; s2 = d2 / "clip.mp4"
        _mk_video(s1, n_frames=30)
        _mk_video(s2, n_frames=90)   # different size, same basename
        a = _ingest_path(proj, str(s1), True)
        b = _ingest_path(proj, str(s2), True)
        assert a != b
        assert "(2)" in b

    def test_managed_path_passes_through(self, proj, tmp_path):
        src = tmp_path / "clip2.mp4"
        _mk_video(src)
        first = _ingest_path(proj, str(src), True)
        again = _ingest_path(proj, first, True)
        assert again == first
