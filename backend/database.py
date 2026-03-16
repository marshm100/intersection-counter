import sqlite3
from pathlib import Path
from backend.config import PROJECTS_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS project_info (
    key TEXT PRIMARY KEY,
    value TEXT
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
    FOREIGN KEY (origin_leg_id) REFERENCES legs(leg_id)
);

CREATE TABLE IF NOT EXISTS pedestrian_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crossing_leg_id INTEGER NOT NULL,
    confidence REAL NOT NULL,
    timestamp_video REAL NOT NULL,
    timestamp_real TEXT DEFAULT NULL,
    frame_number INTEGER NOT NULL,
    FOREIGN KEY (crossing_leg_id) REFERENCES legs(leg_id)
);

CREATE TABLE IF NOT EXISTS checkpoint (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    frame_number INTEGER NOT NULL,
    timestamp_video REAL NOT NULL,
    tracker_state BLOB,
    active_trajectories BLOB,
    vehicle_count INTEGER NOT NULL DEFAULT 0,
    pedestrian_count INTEGER NOT NULL DEFAULT 0,
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

    # Migration: add start_frame column if missing (existing DBs)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(vehicle_events)").fetchall()]
    if "start_frame" not in cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN start_frame INTEGER DEFAULT NULL")

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
