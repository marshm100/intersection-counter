import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from backend.config import PROJECTS_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS project_info (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    video_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sort_order           INTEGER NOT NULL,
    path                 TEXT NOT NULL,
    filename             TEXT NOT NULL,
    fps                  REAL NOT NULL,
    width                INTEGER NOT NULL,
    height               INTEGER NOT NULL,
    total_frames         INTEGER NOT NULL,
    duration_seconds     REAL NOT NULL,
    file_size_bytes      INTEGER NOT NULL,
    codec                TEXT,
    creation_time        TEXT,
    recording_start_time TEXT,
    added_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legs (
    leg_id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    cardinal_direction TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    origin_zone TEXT NOT NULL,
    reference_heading REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicle_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER DEFAULT NULL,
    vehicle_track_id INTEGER NOT NULL,
    origin_leg_id INTEGER NOT NULL,
    movement TEXT NOT NULL,
    trajectory_data TEXT NOT NULL,
    trajectory_confidence REAL NOT NULL,
    vehicle_class TEXT NOT NULL,
    fhwa_class INTEGER DEFAULT NULL,
    detection_confidence REAL NOT NULL,
    timestamp_video REAL NOT NULL,
    timestamp_real TEXT DEFAULT NULL,
    frame_number INTEGER NOT NULL,
    start_frame INTEGER DEFAULT NULL,
    manually_edited INTEGER DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (origin_leg_id) REFERENCES legs(leg_id),
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

CREATE INDEX IF NOT EXISTS idx_events_video ON vehicle_events(video_id);

CREATE TABLE IF NOT EXISTS checkpoint (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_video_id INTEGER DEFAULT NULL,
    frame_number INTEGER NOT NULL,
    timestamp_video REAL NOT NULL,
    tracker_state BLOB,
    active_trajectories BLOB,
    vehicle_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS low_confidence_segments (
    segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    start_timestamp_video REAL NOT NULL,
    end_timestamp_video REAL NOT NULL,
    reason TEXT NOT NULL
);
"""


def get_project_dir(project_id: str) -> Path:
    """Return the directory for a project. Creates it if needed."""
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def get_db_path(project_id: str) -> Path:
    """Return the path to a project's SQLite database."""
    return get_project_dir(project_id) / "project.db"


def get_connection(project_id: str) -> sqlite3.Connection:
    """Open a connection to a project's database.
    Creates DB and all 6 tables if they don't exist.
    MUST set: PRAGMA journal_mode=WAL
    MUST set: PRAGMA foreign_keys=ON
    Returns the connection. Caller closes it."""
    db_path = get_db_path(project_id)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)

    # Migrations for existing DBs created under earlier schemas.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(vehicle_events)").fetchall()]
    if "start_frame" not in cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN start_frame INTEGER DEFAULT NULL")
    if "rejected" not in cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN rejected INTEGER NOT NULL DEFAULT 0")
    if "video_id" not in cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN video_id INTEGER DEFAULT NULL")

    cp_cols = [r[1] for r in conn.execute("PRAGMA table_info(checkpoint)").fetchall()]
    if "current_video_id" not in cp_cols:
        conn.execute("ALTER TABLE checkpoint ADD COLUMN current_video_id INTEGER DEFAULT NULL")

    return conn


def set_project_info(project_id: str, key: str, value: str) -> None:
    """Upsert a key-value pair in project_info. Use INSERT OR REPLACE."""
    conn = get_connection(project_id)
    try:
        conn.execute("INSERT OR REPLACE INTO project_info (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()


def get_project_info(project_id: str, key: str) -> str | None:
    """Get a value from project_info, or None if not found."""
    conn = get_connection(project_id)
    try:
        row = conn.execute("SELECT value FROM project_info WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_all_project_info(project_id: str) -> dict:
    """Get all key-value pairs from project_info as a dict."""
    conn = get_connection(project_id)
    try:
        rows = conn.execute("SELECT key, value FROM project_info").fetchall()
        return {k: v for k, v in rows}
    finally:
        conn.close()


# -- videos table helpers ----------------------------------------------------

_VIDEO_FIELDS = (
    "video_id", "sort_order", "path", "filename", "fps", "width", "height",
    "total_frames", "duration_seconds", "file_size_bytes", "codec",
    "creation_time", "recording_start_time", "added_at",
)


def _row_to_video(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in _VIDEO_FIELDS}


def add_video(project_id: str, metadata: dict) -> int:
    """Insert a video row from a video_service.get_video_info() metadata dict.

    Returns the new video_id. Auto-assigns sort_order = max(existing)+1.
    """
    conn = get_connection(project_id)
    try:
        next_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM videos"
        ).fetchone()[0]
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """INSERT INTO videos
               (sort_order, path, filename, fps, width, height, total_frames,
                duration_seconds, file_size_bytes, codec, creation_time,
                recording_start_time, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                next_order,
                metadata["path"],
                metadata["filename"],
                metadata["fps"],
                metadata["width"],
                metadata["height"],
                metadata["total_frames"],
                metadata["duration_seconds"],
                metadata["file_size_bytes"],
                metadata.get("codec"),
                metadata.get("creation_time"),
                metadata.get("recording_start_time"),
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_videos(project_id: str) -> list[dict]:
    """Return all videos for the project, ordered by sort_order."""
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM videos ORDER BY sort_order, video_id"
        ).fetchall()
        return [_row_to_video(r) for r in rows]
    finally:
        conn.close()


def get_video(project_id: str, video_id: int) -> dict | None:
    """Return one video row by id, or None."""
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM videos WHERE video_id = ?", (video_id,)
        ).fetchone()
        return _row_to_video(row) if row else None
    finally:
        conn.close()


def find_video_by_path(project_id: str, path: str) -> dict | None:
    """Return the video row whose `path` matches, or None."""
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM videos WHERE path = ?", (path,)
        ).fetchone()
        return _row_to_video(row) if row else None
    finally:
        conn.close()


def remove_video(project_id: str, video_id: int) -> None:
    """Delete a video and cascade-delete its vehicle_events."""
    conn = get_connection(project_id)
    try:
        conn.execute("DELETE FROM vehicle_events WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
        conn.commit()
    finally:
        conn.close()


def set_video_recording_start_time(
    project_id: str, video_id: int, start_time: str | None
) -> None:
    """Update recording_start_time on a video row."""
    conn = get_connection(project_id)
    try:
        conn.execute(
            "UPDATE videos SET recording_start_time = ? WHERE video_id = ?",
            (start_time, video_id),
        )
        conn.commit()
    finally:
        conn.close()
