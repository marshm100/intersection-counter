"""Tests for CheckpointManager."""

import os
import pickle
import sqlite3
import tempfile

import pytest

from backend.database import SCHEMA
from backend.services.checkpoint import CheckpointManager


@pytest.fixture
def checkpoint_env():
    """Create a temp database with the schema applied."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "project.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.close()
        yield db_path


@pytest.fixture
def mgr(checkpoint_env):
    return CheckpointManager(checkpoint_env)


class TestCheckpointManager:
    def test_no_checkpoint_initially(self, mgr):
        assert mgr.has_checkpoint() is False
        assert mgr.load_checkpoint() is None

    def test_save_and_load(self, mgr):
        mgr.save_checkpoint(
            frame_number=100,
            timestamp_video=3.33,
            tracker_state=b"tracker_bytes",
            active_trajectories=b"traj_bytes",
            vehicle_count=5,
            error_count=1,
        )
        assert mgr.has_checkpoint() is True
        cp = mgr.load_checkpoint()
        assert cp is not None
        assert cp["frame_number"] == 100
        assert cp["timestamp_video"] == pytest.approx(3.33)
        assert cp["tracker_state"] == b"tracker_bytes"
        assert cp["active_trajectories"] == b"traj_bytes"
        assert cp["vehicle_count"] == 5
        assert cp["error_count"] == 1

    def test_upsert_overwrites(self, mgr):
        mgr.save_checkpoint(100, 3.33, b"a", b"b", 1, 0)
        mgr.save_checkpoint(200, 6.66, b"c", b"d", 10, 2)
        cp = mgr.load_checkpoint()
        assert cp["frame_number"] == 200
        assert cp["vehicle_count"] == 10

    def test_clear_checkpoint(self, mgr):
        mgr.save_checkpoint(100, 3.33, b"a", b"b", 1, 0)
        assert mgr.has_checkpoint() is True
        mgr.clear_checkpoint()
        assert mgr.has_checkpoint() is False

    def test_tracker_state_blob(self, mgr):
        blob = b"\x00\x01\x02\xff" * 100
        mgr.save_checkpoint(50, 1.5, blob, b"", 0, 0)
        cp = mgr.load_checkpoint()
        assert cp["tracker_state"] == blob

    def test_active_trajectories_blob(self, mgr):
        data = {"track_1": [(100, 200), (110, 210)], "track_2": [(300, 400)]}
        blob = pickle.dumps(data)
        mgr.save_checkpoint(50, 1.5, b"", blob, 0, 0)
        cp = mgr.load_checkpoint()
        restored = pickle.loads(cp["active_trajectories"])
        assert restored == data

    def test_counts_persist(self, mgr):
        mgr.save_checkpoint(0, 0.0, b"", b"", 42, 7)
        cp = mgr.load_checkpoint()
        assert cp["vehicle_count"] == 42
        assert cp["error_count"] == 7

    def test_updated_at_set(self, mgr):
        mgr.save_checkpoint(0, 0.0, b"", b"", 0, 0)
        cp = mgr.load_checkpoint()
        assert cp["updated_at"] is not None
        assert len(cp["updated_at"]) > 10  # ISO datetime string
