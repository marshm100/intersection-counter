import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from backend.config import PROJECTS_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS project_info (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- v3: intersection-day cards (one row per intersection_name x recording_date)
CREATE TABLE IF NOT EXISTS intersections (
    intersection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    date            TEXT NOT NULL,        -- YYYY-MM-DD
    sort_order      INTEGER NOT NULL,
    leg_count       INTEGER NOT NULL DEFAULT 4,
    created_at      TEXT NOT NULL,
    UNIQUE(name, date)
);

-- v3: cameras at an intersection-day
CREATE TABLE IF NOT EXISTS cameras (
    camera_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    intersection_id INTEGER NOT NULL,
    label           TEXT NOT NULL,
    sort_order      INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (intersection_id) REFERENCES intersections(intersection_id),
    UNIQUE(intersection_id, label)
);

-- v3: wall-clock processing windows per intersection-day
CREATE TABLE IF NOT EXISTS trims (
    trim_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    intersection_id INTEGER NOT NULL,
    start_wallclock TEXT NOT NULL,        -- HH:MM:SS
    end_wallclock   TEXT NOT NULL,        -- HH:MM:SS
    sort_order      INTEGER NOT NULL,
    FOREIGN KEY (intersection_id) REFERENCES intersections(intersection_id)
);

CREATE TABLE IF NOT EXISTS videos (
    video_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id                INTEGER DEFAULT NULL,                 -- v3
    sort_order               INTEGER NOT NULL,
    path                     TEXT NOT NULL,
    filename                 TEXT NOT NULL,
    fps                      REAL NOT NULL,
    width                    INTEGER NOT NULL,
    height                   INTEGER NOT NULL,
    total_frames             INTEGER NOT NULL,
    duration_seconds         REAL NOT NULL,
    file_size_bytes          INTEGER NOT NULL,
    codec                    TEXT,
    creation_time            TEXT,
    recording_start_time     TEXT,
    -- v3: filename-parsed and user-labeled fields
    camera_label_parsed      TEXT,
    intersection_name_label  TEXT,
    recording_start_datetime TEXT,
    parse_confidence         REAL DEFAULT 1.0,
    added_at                 TEXT NOT NULL,
    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id)
);

CREATE TABLE IF NOT EXISTS legs (
    leg_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id          INTEGER DEFAULT NULL,                       -- v3: per-camera legs
    label              TEXT NOT NULL,
    cardinal_direction TEXT NOT NULL,
    sort_order         INTEGER NOT NULL,
    origin_zone        TEXT NOT NULL,
    reference_heading  REAL NOT NULL,
    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id)
);

CREATE TABLE IF NOT EXISTS vehicle_events (
    event_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id              INTEGER DEFAULT NULL,
    camera_id             INTEGER DEFAULT NULL,                    -- v3: denormalized
    trim_id               INTEGER DEFAULT NULL,                    -- v3
    vehicle_track_id      INTEGER NOT NULL,
    origin_leg_id         INTEGER NOT NULL,
    movement              TEXT NOT NULL,
    trajectory_data       TEXT NOT NULL,
    trajectory_confidence REAL NOT NULL,
    vehicle_class         TEXT NOT NULL,
    fhwa_class            INTEGER DEFAULT NULL,
    detection_confidence  REAL NOT NULL,
    timestamp_video       REAL NOT NULL,
    timestamp_real        TEXT DEFAULT NULL,
    frame_number          INTEGER NOT NULL,
    start_frame           INTEGER DEFAULT NULL,
    manually_edited       INTEGER DEFAULT 0,
    rejected              INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (origin_leg_id) REFERENCES legs(leg_id),
    FOREIGN KEY (video_id) REFERENCES videos(video_id),
    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id),
    FOREIGN KEY (trim_id) REFERENCES trims(trim_id)
);

CREATE INDEX IF NOT EXISTS idx_events_video  ON vehicle_events(video_id);
CREATE INDEX IF NOT EXISTS idx_events_camera ON vehicle_events(camera_id);
CREATE INDEX IF NOT EXISTS idx_events_trim   ON vehicle_events(trim_id);

CREATE TABLE IF NOT EXISTS checkpoint (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    current_video_id    INTEGER DEFAULT NULL,
    current_camera_id   INTEGER DEFAULT NULL,                      -- v3
    current_trim_id     INTEGER DEFAULT NULL,                      -- v3
    frame_number        INTEGER NOT NULL,
    timestamp_video     REAL NOT NULL,
    tracker_state       BLOB,
    active_trajectories BLOB,
    vehicle_count       INTEGER NOT NULL DEFAULT 0,
    error_count         INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT NOT NULL
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
    ev_cols = [r[1] for r in conn.execute("PRAGMA table_info(vehicle_events)").fetchall()]
    if "start_frame" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN start_frame INTEGER DEFAULT NULL")
    if "rejected" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN rejected INTEGER NOT NULL DEFAULT 0")
    if "video_id" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN video_id INTEGER DEFAULT NULL")
    if "camera_id" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN camera_id INTEGER DEFAULT NULL")
    if "trim_id" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN trim_id INTEGER DEFAULT NULL")

    cp_cols = [r[1] for r in conn.execute("PRAGMA table_info(checkpoint)").fetchall()]
    if "current_video_id" not in cp_cols:
        conn.execute("ALTER TABLE checkpoint ADD COLUMN current_video_id INTEGER DEFAULT NULL")
    if "current_camera_id" not in cp_cols:
        conn.execute("ALTER TABLE checkpoint ADD COLUMN current_camera_id INTEGER DEFAULT NULL")
    if "current_trim_id" not in cp_cols:
        conn.execute("ALTER TABLE checkpoint ADD COLUMN current_trim_id INTEGER DEFAULT NULL")

    vid_cols = [r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()]
    if "camera_id" not in vid_cols:
        conn.execute("ALTER TABLE videos ADD COLUMN camera_id INTEGER DEFAULT NULL")
    if "camera_label_parsed" not in vid_cols:
        conn.execute("ALTER TABLE videos ADD COLUMN camera_label_parsed TEXT")
    if "intersection_name_label" not in vid_cols:
        conn.execute("ALTER TABLE videos ADD COLUMN intersection_name_label TEXT")
    if "recording_start_datetime" not in vid_cols:
        conn.execute("ALTER TABLE videos ADD COLUMN recording_start_datetime TEXT")
    if "parse_confidence" not in vid_cols:
        conn.execute("ALTER TABLE videos ADD COLUMN parse_confidence REAL DEFAULT 1.0")

    leg_cols = [r[1] for r in conn.execute("PRAGMA table_info(legs)").fetchall()]
    if "camera_id" not in leg_cols:
        conn.execute("ALTER TABLE legs ADD COLUMN camera_id INTEGER DEFAULT NULL")

    conn.commit()
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
    "video_id", "camera_id", "sort_order", "path", "filename",
    "fps", "width", "height", "total_frames", "duration_seconds",
    "file_size_bytes", "codec", "creation_time", "recording_start_time",
    "camera_label_parsed", "intersection_name_label",
    "recording_start_datetime", "parse_confidence", "added_at",
)


def _row_to_video(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in _VIDEO_FIELDS}


def add_video(project_id: str, metadata: dict) -> int:
    """Insert a video row from a video_service.get_video_info() metadata dict.

    Returns the new video_id. Auto-assigns sort_order = max(existing)+1.

    Optional v3 fields the metadata dict may carry (pre-populated by the
    filename parser at upload time):
      camera_label_parsed, intersection_name_label,
      recording_start_datetime, parse_confidence
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
                recording_start_time, camera_label_parsed,
                intersection_name_label, recording_start_datetime,
                parse_confidence, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                metadata.get("camera_label_parsed"),
                metadata.get("intersection_name_label"),
                metadata.get("recording_start_datetime"),
                metadata.get("parse_confidence", 1.0),
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


# -- v3: video labeling helpers ----------------------------------------------

def update_video_labels(
    project_id: str,
    video_id: int,
    *,
    intersection_name: str | None = None,
    recording_start_datetime: str | None = None,
    camera_label: str | None = None,
) -> None:
    """Patch any subset of the user-editable v3 labels on a video."""
    sets, params = [], []
    if intersection_name is not None:
        sets.append("intersection_name_label = ?")
        params.append(intersection_name)
    if recording_start_datetime is not None:
        sets.append("recording_start_datetime = ?")
        params.append(recording_start_datetime)
    if camera_label is not None:
        sets.append("camera_label_parsed = ?")
        params.append(camera_label)
    if not sets:
        return
    params.append(video_id)
    conn = get_connection(project_id)
    try:
        conn.execute(
            f"UPDATE videos SET {', '.join(sets)} WHERE video_id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def link_video_to_camera(project_id: str, video_id: int, camera_id: int | None) -> None:
    conn = get_connection(project_id)
    try:
        conn.execute(
            "UPDATE videos SET camera_id = ? WHERE video_id = ?",
            (camera_id, video_id),
        )
        conn.commit()
    finally:
        conn.close()


# -- v3: intersections table helpers ----------------------------------------

_INTERSECTION_FIELDS = (
    "intersection_id", "name", "date", "sort_order", "leg_count", "created_at",
)


def _row_to_intersection(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in _INTERSECTION_FIELDS}


def upsert_intersection(
    project_id: str,
    name: str,
    date: str,
    leg_count: int = 4,
) -> int:
    """Get-or-create an intersection by (name, date). Returns intersection_id."""
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT intersection_id FROM intersections WHERE name = ? AND date = ?",
            (name, date),
        ).fetchone()
        if row:
            return int(row["intersection_id"])
        next_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM intersections"
        ).fetchone()[0]
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """INSERT INTO intersections
               (name, date, sort_order, leg_count, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (name, date, next_order, leg_count, now),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_intersections(project_id: str) -> list[dict]:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM intersections ORDER BY sort_order, intersection_id"
        ).fetchall()
        return [_row_to_intersection(r) for r in rows]
    finally:
        conn.close()


def get_intersection(project_id: str, intersection_id: int) -> dict | None:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM intersections WHERE intersection_id = ?",
            (intersection_id,),
        ).fetchone()
        return _row_to_intersection(row) if row else None
    finally:
        conn.close()


def update_intersection(
    project_id: str,
    intersection_id: int,
    *,
    name: str | None = None,
    leg_count: int | None = None,
    sort_order: int | None = None,
) -> None:
    sets, params = [], []
    if name is not None:
        sets.append("name = ?"); params.append(name)
    if leg_count is not None:
        sets.append("leg_count = ?"); params.append(leg_count)
    if sort_order is not None:
        sets.append("sort_order = ?"); params.append(sort_order)
    if not sets:
        return
    params.append(intersection_id)
    conn = get_connection(project_id)
    try:
        conn.execute(
            f"UPDATE intersections SET {', '.join(sets)} WHERE intersection_id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def remove_intersection(project_id: str, intersection_id: int) -> None:
    """Cascade-delete: trims, cameras, legs (via camera FK), and unlink videos."""
    conn = get_connection(project_id)
    try:
        with conn:
            cam_ids = [r[0] for r in conn.execute(
                "SELECT camera_id FROM cameras WHERE intersection_id = ?",
                (intersection_id,),
            ).fetchall()]
            for cid in cam_ids:
                conn.execute("DELETE FROM legs WHERE camera_id = ?", (cid,))
                conn.execute("UPDATE videos SET camera_id = NULL WHERE camera_id = ?", (cid,))
            conn.execute("DELETE FROM cameras WHERE intersection_id = ?", (intersection_id,))
            conn.execute("DELETE FROM trims WHERE intersection_id = ?", (intersection_id,))
            conn.execute("DELETE FROM intersections WHERE intersection_id = ?", (intersection_id,))
    finally:
        conn.close()


# -- v3: cameras table helpers ----------------------------------------------

_CAMERA_FIELDS = ("camera_id", "intersection_id", "label", "sort_order", "created_at")


def _row_to_camera(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in _CAMERA_FIELDS}


def upsert_camera(project_id: str, intersection_id: int, label: str) -> int:
    """Get-or-create camera at this intersection by label. Returns camera_id."""
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT camera_id FROM cameras WHERE intersection_id = ? AND label = ?",
            (intersection_id, label),
        ).fetchone()
        if row:
            return int(row["camera_id"])
        next_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM cameras WHERE intersection_id = ?",
            (intersection_id,),
        ).fetchone()[0]
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """INSERT INTO cameras (intersection_id, label, sort_order, created_at)
               VALUES (?, ?, ?, ?)""",
            (intersection_id, label, next_order, now),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_cameras(project_id: str, intersection_id: int) -> list[dict]:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM cameras WHERE intersection_id = ? ORDER BY sort_order, camera_id",
            (intersection_id,),
        ).fetchall()
        return [_row_to_camera(r) for r in rows]
    finally:
        conn.close()


def get_camera(project_id: str, camera_id: int) -> dict | None:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM cameras WHERE camera_id = ?",
            (camera_id,),
        ).fetchone()
        return _row_to_camera(row) if row else None
    finally:
        conn.close()


def update_camera(
    project_id: str,
    camera_id: int,
    *,
    label: str | None = None,
    sort_order: int | None = None,
) -> None:
    sets, params = [], []
    if label is not None:
        sets.append("label = ?"); params.append(label)
    if sort_order is not None:
        sets.append("sort_order = ?"); params.append(sort_order)
    if not sets:
        return
    params.append(camera_id)
    conn = get_connection(project_id)
    try:
        conn.execute(
            f"UPDATE cameras SET {', '.join(sets)} WHERE camera_id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def remove_camera(project_id: str, camera_id: int) -> None:
    """Cascade-delete: legs, unlink videos."""
    conn = get_connection(project_id)
    try:
        with conn:
            conn.execute("DELETE FROM legs WHERE camera_id = ?", (camera_id,))
            conn.execute("UPDATE videos SET camera_id = NULL WHERE camera_id = ?", (camera_id,))
            conn.execute("DELETE FROM cameras WHERE camera_id = ?", (camera_id,))
    finally:
        conn.close()


def list_videos_for_camera(project_id: str, camera_id: int) -> list[dict]:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM videos WHERE camera_id = ? ORDER BY sort_order, video_id",
            (camera_id,),
        ).fetchall()
        return [_row_to_video(r) for r in rows]
    finally:
        conn.close()


# -- v3: trims table helpers ------------------------------------------------

_TRIM_FIELDS = (
    "trim_id", "intersection_id", "start_wallclock", "end_wallclock", "sort_order",
)


def _row_to_trim(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in _TRIM_FIELDS}


def add_trim(
    project_id: str,
    intersection_id: int,
    start_wallclock: str,
    end_wallclock: str,
) -> int:
    conn = get_connection(project_id)
    try:
        next_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM trims WHERE intersection_id = ?",
            (intersection_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """INSERT INTO trims (intersection_id, start_wallclock, end_wallclock, sort_order)
               VALUES (?, ?, ?, ?)""",
            (intersection_id, start_wallclock, end_wallclock, next_order),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_trims(project_id: str, intersection_id: int) -> list[dict]:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM trims WHERE intersection_id = ? ORDER BY sort_order, trim_id",
            (intersection_id,),
        ).fetchall()
        return [_row_to_trim(r) for r in rows]
    finally:
        conn.close()


def remove_trim(project_id: str, trim_id: int) -> None:
    conn = get_connection(project_id)
    try:
        conn.execute("DELETE FROM trims WHERE trim_id = ?", (trim_id,))
        conn.commit()
    finally:
        conn.close()


def update_trim(
    project_id: str,
    trim_id: int,
    *,
    start_wallclock: str | None = None,
    end_wallclock: str | None = None,
    sort_order: int | None = None,
) -> None:
    sets, params = [], []
    if start_wallclock is not None:
        sets.append("start_wallclock = ?"); params.append(start_wallclock)
    if end_wallclock is not None:
        sets.append("end_wallclock = ?"); params.append(end_wallclock)
    if sort_order is not None:
        sets.append("sort_order = ?"); params.append(sort_order)
    if not sets:
        return
    params.append(trim_id)
    conn = get_connection(project_id)
    try:
        conn.execute(
            f"UPDATE trims SET {', '.join(sets)} WHERE trim_id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


# -- v3: post-migration auto-bootstrap for v2 projects ----------------------

def ensure_default_intersection_for_legacy(project_id: str) -> int | None:
    """If a v2 project has videos with no camera_id (i.e., legacy flat list),
    auto-create one intersection + one camera + one default trim, and link
    existing videos/legs/events to them. Idempotent.

    Returns the intersection_id of the default intersection if one was
    created (or already existed for legacy data); None if there's nothing
    to migrate.
    """
    conn = get_connection(project_id)
    try:
        # If there are no videos at all, nothing to migrate.
        n_videos = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        if n_videos == 0:
            return None

        # If every video already has a camera_id, we're already on v3.
        n_unlinked = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE camera_id IS NULL"
        ).fetchone()[0]
        if n_unlinked == 0:
            return None

        # Pick a date: earliest recording_start_time or recording_start_datetime
        # among unlinked videos, falling back to today.
        date_row = conn.execute(
            """SELECT COALESCE(MIN(recording_start_datetime),
                               MIN(recording_start_time),
                               MIN(creation_time))
               FROM videos WHERE camera_id IS NULL"""
        ).fetchone()
        date_str = (date_row[0] or datetime.now().isoformat())[:10]
    finally:
        conn.close()

    iid = upsert_intersection(project_id, "Main intersection", date_str, leg_count=4)
    cid = upsert_camera(project_id, iid, "Camera 1")

    conn = get_connection(project_id)
    try:
        with conn:
            conn.execute(
                "UPDATE videos SET camera_id = ? WHERE camera_id IS NULL",
                (cid,),
            )
            conn.execute(
                "UPDATE legs SET camera_id = ? WHERE camera_id IS NULL",
                (cid,),
            )
            conn.execute(
                "UPDATE vehicle_events SET camera_id = ? WHERE camera_id IS NULL",
                (cid,),
            )
    finally:
        conn.close()

    # Auto-add one default trim spanning each video's wall-clock coverage.
    # If we can't compute wall-clock coverage, leave the trims table empty —
    # callers can add trims explicitly.
    existing_trims = list_trims(project_id, iid)
    if not existing_trims:
        conn = get_connection(project_id)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT MIN(recording_start_datetime) AS first_start,
                          MAX(recording_start_datetime) AS last_start,
                          MAX(duration_seconds)         AS max_dur
                   FROM videos WHERE camera_id = ?""",
                (cid,),
            ).fetchone()
        finally:
            conn.close()
        if row and row["first_start"]:
            try:
                start_dt = datetime.fromisoformat(row["first_start"])
                last_dt = datetime.fromisoformat(row["last_start"])
                end_dt = last_dt + timedelta(seconds=float(row["max_dur"] or 0))
                add_trim(
                    project_id, iid,
                    start_dt.strftime("%H:%M:%S"),
                    end_dt.strftime("%H:%M:%S"),
                )
            except Exception:
                pass

    return iid
