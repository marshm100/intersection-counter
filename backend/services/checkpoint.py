"""Checkpoint manager for processing pipeline pause/resume.

Stores a single checkpoint row (id=1) in the project's SQLite database.
Each method opens its own connection for thread safety.
"""

import sqlite3
from datetime import datetime, timezone


class CheckpointManager:
    """Manages a single checkpoint row for pipeline state persistence."""

    def __init__(self, db_path: str):
        """Store the database path."""
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def save_checkpoint(
        self,
        frame_number: int,
        timestamp_video: float,
        tracker_state: bytes,
        active_trajectories: bytes,
        vehicle_count: int,
        pedestrian_count: int,
        error_count: int,
    ) -> None:
        """Save checkpoint (upsert — always id=1)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO checkpoint
                   (id, frame_number, timestamp_video, tracker_state,
                    active_trajectories, vehicle_count, pedestrian_count,
                    error_count, updated_at)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (frame_number, timestamp_video, tracker_state,
                 active_trajectories, vehicle_count, pedestrian_count,
                 error_count, now),
            )
            conn.commit()
        finally:
            conn.close()

    def load_checkpoint(self) -> dict | None:
        """Load the checkpoint. Returns None if none exists."""
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM checkpoint WHERE id = 1"
            ).fetchone()
            if row is None:
                return None
            return {
                "frame_number": row["frame_number"],
                "timestamp_video": row["timestamp_video"],
                "tracker_state": row["tracker_state"],
                "active_trajectories": row["active_trajectories"],
                "vehicle_count": row["vehicle_count"],
                "pedestrian_count": row["pedestrian_count"],
                "error_count": row["error_count"],
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()

    def has_checkpoint(self) -> bool:
        """Check if a checkpoint exists."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM checkpoint WHERE id = 1"
            ).fetchone()
            return row[0] > 0
        finally:
            conn.close()

    def clear_checkpoint(self) -> None:
        """Delete the checkpoint row."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM checkpoint WHERE id = 1")
            conn.commit()
        finally:
            conn.close()
