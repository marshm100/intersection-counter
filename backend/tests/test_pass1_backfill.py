"""Pass-1 back-fill for weak-box births (2026-09-12): back-fill rows collect
in a sidecar saved before every count.txt write, join the dump at the end of
the run (before the stop-fracture collapse), and the finished dump is
rewritten in frame order. Resume clamps to the main rows, keeps only
back-fill promoted before the resume frame, floors the id counter, and a
complete dump is not re-stepped."""
import json

import numpy as np
import pytest
from supervision.tracker.byte_tracker.basetrack import BaseTrack

import backend.services.two_pass as tp
from backend import config as cfg
from backend.tests.test_two_pass_stage34 import _mk_cam, _mk_video, client


@pytest.fixture()
def proj():
    pid = client.post("/api/projects", json={"name": "backfill-test"}).json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


@pytest.fixture(autouse=True)
def stage_on(monkeypatch):
    monkeypatch.setattr(BaseTrack, "_count", 0)
    monkeypatch.setattr(cfg, "TRACKER_POSITION_RECOVERY", True)
    monkeypatch.setattr(cfg, "TRACKER_WEAK_BIRTH", True)


# ---- helpers ------------------------------------------------------------------

def test_sidecar_save_load_filters_on_promotion(tmp_path):
    rows = [(1, 5, 10, 10, 4, 4, 0.2, 2, 8), (2, 6, 10, 10, 4, 4, 0.2, 2, 20)]
    tp._save_backfill(tmp_path, rows)
    assert [r[0] for r in tp._load_backfill(tmp_path, 10)] == [1]
    assert len(tp._load_backfill(tmp_path, 100)) == 2
    tp._reset_backfill(tmp_path)
    assert tp._load_backfill(tmp_path, 100) == []


def test_resume_count_clamps_to_main_rows_and_persists(tmp_path):
    (tmp_path / "count.txt").write_text("120")
    assert tp._resume_count(tmp_path, {"backfill_merge": {"main_rows": 100, "rows": 20}}) == 100
    assert (tmp_path / "count.txt").read_text() == "100"
    (tmp_path / "count.txt").write_text("90")
    assert tp._resume_count(tmp_path, {"backfill_merge": {"main_rows": 100}}) == 90
    assert tp._resume_count(tmp_path, {}) == 90


def test_keep_mask_drops_id_frame_collisions_and_duplicates():
    main = np.array([[1, 10, 0, 0, 1, 1, 1, 2], [2, 10, 0, 0, 1, 1, 1, 2]], dtype=np.float32)
    bf = np.array([[1, 10, 0, 0, 1, 1, .2, 2, 12],      # collides with main
                   [1, 9, 0, 0, 1, 1, .2, 2, 12],
                   [1, 9, 0, 0, 1, 1, .2, 2, 12],       # duplicate within back-fill
                   [3, 10, 0, 0, 1, 1, .2, 2, 12]], dtype=np.float64)
    assert tp._backfill_keep_mask(main, bf).tolist() == [False, True, False, True]


def test_frame_order_rewrite_is_stable(tmp_path):
    from numpy.lib.format import open_memmap
    mm = open_memmap(tmp_path / "rows.npy", mode="w+", dtype=np.float32, shape=(10, 8))
    mm[:5] = [[1, 3, 0, 0, 1, 1, 1, 2], [2, 3, 0, 0, 1, 1, 1, 2], [1, 4, 0, 0, 1, 1, 1, 2],
              [5, 1, 0, 0, 1, 1, 1, 2], [5, 2, 0, 0, 1, 1, 1, 2]]
    mm.flush(); del mm
    assert tp._frame_order_rewrite(tmp_path, 5)
    rows = np.load(tmp_path / "rows.npy")
    assert rows[:, 1].tolist() == [1, 2, 3, 3, 4]
    assert rows[:, 0].tolist() == [5, 5, 1, 2, 1]


def test_cfg_weak_birth_and_resume_key(monkeypatch):
    assert "weak_birth" in tp.PASS1_RESUME_KEYS
    assert tp._cfg_weak_birth()["persist_s"] == cfg.TRACKER_WEAK_BIRTH_PERSIST_S
    monkeypatch.setattr(cfg, "TRACKER_WEAK_BIRTH", False)
    assert tp._cfg_weak_birth() is None


# ---- end to end ---------------------------------------------------------------

class _WeakStartDetector:
    """One car moving 1 px/frame: weak (0.18) for the first WEAK frames, then 0.9."""
    calls: list = []
    WEAK = 12

    def __init__(self, **kwargs):
        pass

    def detect(self, frame):
        fidx = len(type(self).calls)
        type(self).calls.append(fidx)
        x = 5.0 + fidx
        conf = 0.18 if fidx < type(self).WEAK else 0.9
        return [{"bbox": [x, 10.0, x + 12.0, 22.0], "center": [x + 6, 16.0],
                 "class_id": 2, "class_name": "car", "confidence": conf,
                 "bbox_width": 12.0, "bbox_height": 12.0, "bbox_area": 144.0,
                 "is_vehicle": True}]


def _setup(proj, tmp_path, monkeypatch, name):
    import backend.services.detector as det
    vid = tmp_path / f"{name}.mp4"
    _mk_video(vid, n_frames=40)
    _iid, cid = _mk_cam(proj, video={
        "path": str(vid), "fps": 10.0, "total_frames": 40,
        "file_size_bytes": vid.stat().st_size,
        "recording_start_datetime": "2026-05-12T07:00:00"})
    _WeakStartDetector.calls = []
    monkeypatch.setattr(det, "VehicleDetector", _WeakStartDetector)
    monkeypatch.setattr(tp, "PASS1_INGEST_CHUNK_SECONDS", 2.0)
    return cid


def _rows(proj, cid, variant="study_0700"):
    from backend.services.pass2_replay import load_dump, tracks_dir
    d = tracks_dir(tp._camera_parquet(proj, cid, variant))
    rows = np.array(load_dump(d), copy=True)          # a copy: a live memmap blocks rewriting rows.npy on Windows
    return rows, json.loads((d / "meta.json").read_text()), d


def test_ingest_backfills_the_weak_start(proj, tmp_path, monkeypatch):
    cid = _setup(proj, tmp_path, monkeypatch, "wb1")
    tp.run_pass1(proj, cid, variant="study_0700", start_frame=0, end_frame=40)
    rows, meta, _d = _rows(proj, cid)
    assert meta["complete"] and meta["backfill_rows"] > 0 and meta.get("frame_ordered") is True
    assert (np.diff(rows[:, 1]) >= 0).all()
    keys = set(zip(rows[:, 0].astype(int).tolist(), rows[:, 1].astype(int).tolist()))
    assert len(keys) == len(rows)                                   # unique (id, frame)
    tid = int(rows[rows[:, 1] == 20][0, 0])
    fr = rows[rows[:, 0] == tid][:, 1].astype(int)
    assert fr.min() <= 1                                            # the path starts at the car's first frames


def test_cache_cancel_then_resume_keeps_backfill_once(proj, tmp_path, monkeypatch):
    cid = _setup(proj, tmp_path, monkeypatch, "wb2")
    tp.run_pass1(proj, cid, variant="study_0700", start_frame=0, end_frame=40)   # builds the cache
    ref_rows, _m, _d = _rows(proj, cid)
    BaseTrack._count = 0
    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        return calls["n"] > 25
    with pytest.raises(tp.JobCancelled):
        tp.run_pass1(proj, cid, variant="study_0700", start_frame=0, end_frame=40,
                     resume=False, should_cancel=cancel)
    BaseTrack._count = 0                                            # a new process
    tp.run_pass1(proj, cid, variant="study_0700", start_frame=0, end_frame=40, resume=True)
    rows, meta, _d = _rows(proj, cid)
    assert meta["complete"]
    keys = list(zip(rows[:, 0].astype(int).tolist(), rows[:, 1].astype(int).tolist()))
    assert len(set(keys)) == len(keys)                              # no duplicate (id, frame)
    early = rows[rows[:, 1] < _WeakStartDetector.WEAK]
    assert len(early) == len(ref_rows[ref_rows[:, 1] < _WeakStartDetector.WEAK])   # prefix once


def test_resume_of_a_complete_dump_returns_early(proj, tmp_path, monkeypatch):
    cid = _setup(proj, tmp_path, monkeypatch, "wb3")
    tp.run_pass1(proj, cid, variant="study_0700", start_frame=0, end_frame=40)
    _rows0, _m, d = _rows(proj, cid)
    before = (d / "rows.npy").read_bytes()
    res = tp.run_pass1(proj, cid, variant="study_0700", start_frame=0, end_frame=40, resume=True)
    assert res["status"] == "complete"
    assert (d / "rows.npy").read_bytes() == before
