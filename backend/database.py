import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from backend.config import PROJECTS_DIR
from backend.services.posterior import margin_from_json

SCHEMA = """
CREATE TABLE IF NOT EXISTS project_info (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- v3: intersection-day cards (one row per intersection_name x recording_date)
-- The four "calib_*" columns are nullable per-intersection overrides for the
-- corresponding global constants in backend/config.py. NULL = use the global
-- default. Surfaced in the leg-calibration UI so the engineer can tune them
-- per intersection without changing global behavior.
CREATE TABLE IF NOT EXISTS intersections (
    intersection_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name                         TEXT NOT NULL,
    date                         TEXT NOT NULL,        -- YYYY-MM-DD
    sort_order                   INTEGER NOT NULL,
    leg_count                    INTEGER NOT NULL DEFAULT 4,
    created_at                   TEXT NOT NULL,
    calib_tripwire_half_length_px       REAL,    -- origin attribution
    calib_trajectory_through_max_angle  REAL,    -- classification
    calib_trajectory_turn_min_angle     REAL,    -- classification
    calib_trajectory_uturn_min_angle    REAL,    -- classification
    UNIQUE(name, date)
);

-- v3: cameras at an intersection-day
CREATE TABLE IF NOT EXISTS cameras (
    camera_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    intersection_id INTEGER NOT NULL,
    label           TEXT NOT NULL,
    sort_order      INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    -- v3.calibration: per-CAMERA detection/tracking knobs (override or NULL=fall
    -- back to backend/config.py). These are camera+resolution artifacts (e.g. the
    -- detector double-boxing one vehicle, the tracker duplicating IDs), distinct
    -- from the per-INTERSECTION classification tunables on the intersections table.
    calib_pre_track_nms_iou             REAL,    -- class-agnostic pre-track NMS IoU
    calib_tracker_lost_buffer           INTEGER, -- frames a lost track survives
    calib_tracker_match_threshold       REAL,    -- IoU match threshold
    calib_tracker_activation_threshold  REAL,    -- detection conf to start a track
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

-- Per-(origin_leg, destination_leg) road path through the intersection.
-- One polyline encodes the full natural trajectory from off-frame entry
-- on the origin leg, through the intersection, to off-frame exit on the
-- destination leg. The pipeline uses these for:
--   * origin attribution     (match traj's first K points to entry segment)
--   * destination scoring    (match traj's full path to a candidate polyline)
--   * movement labeling      (path stores the label, no derive_movement needed)
-- Auto-cal populates these from clustered observed trajectories; the
-- engineer reviews/adjusts in the calibration UI. When a camera has no
-- rows here, the pipeline falls back to today's tripwire+heading logic.
CREATE TABLE IF NOT EXISTS intersection_paths (
    path_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id            INTEGER NOT NULL,
    origin_leg_id        INTEGER NOT NULL,
    destination_leg_id   INTEGER NOT NULL,
    polyline             TEXT    NOT NULL,                  -- JSON [[x,y], ...]
    movement_label       TEXT    NOT NULL,                  -- through|left|right|u_turn
    supporting_count     INTEGER NOT NULL DEFAULT 0,
    expected_speed       REAL,                              -- median px/step of supporting tracks (speed-tiebreak signature; NULL = unset)
    sample_window_seconds REAL,                             -- duration of the sample supporting_count was observed over (scales the turn-merge volume gate; NULL = unknown/legacy)
    source               TEXT    NOT NULL DEFAULT 'manual', -- manual|auto
    last_observed_at     TEXT,
    created_at           TEXT    NOT NULL,
    FOREIGN KEY (camera_id)          REFERENCES cameras(camera_id),
    FOREIGN KEY (origin_leg_id)      REFERENCES legs(leg_id),
    FOREIGN KEY (destination_leg_id) REFERENCES legs(leg_id),
    UNIQUE(camera_id, origin_leg_id, destination_leg_id)
);

-- Operator-drawn movement channels (Phase 2.1 — implementation_plan_architecture
-- 2026-06-11). A channel is a tapered corridor (entry -> apex -> exit quadratic,
-- per-mouth widths) declaring that a movement EXISTS and where it runs. The
-- GT-free bank builder (scripts/build_bank_gtfree.py) uses channels two ways:
-- corridor-claiming tracks before anchor binning (the only reliable fix for
-- anchor-on-through-path geometries, e.g. cam1/cam5), and as hand-drawn
-- fallback polylines for movements the bootstrap window never collected.
CREATE TABLE IF NOT EXISTS channels (
    channel_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id            INTEGER NOT NULL,
    origin_leg_id        INTEGER NOT NULL,
    destination_leg_id   INTEGER NOT NULL,
    movement             TEXT    NOT NULL,        -- through|left|right|u_turn
    entry_pt             TEXT    NOT NULL,        -- JSON [x,y]
    apex_pt              TEXT    NOT NULL,        -- JSON [x,y] (curve passes through it)
    exit_pt              TEXT    NOT NULL,        -- JSON [x,y]
    width_in             REAL    NOT NULL DEFAULT 40,
    width_out            REAL    NOT NULL DEFAULT 40,
    created_at           TEXT    NOT NULL,
    FOREIGN KEY (camera_id)          REFERENCES cameras(camera_id),
    FOREIGN KEY (origin_leg_id)      REFERENCES legs(leg_id),
    FOREIGN KEY (destination_leg_id) REFERENCES legs(leg_id)
);

-- Manual spot counts (Phase 4): an engineer hand-counts a short random window
-- from the raw video; the comparison against system counts (with CIs) is the
-- zero-ground-truth accuracy estimate feeding the acceptance gate.
CREATE TABLE IF NOT EXISTS spot_counts (
    spot_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id            INTEGER NOT NULL,
    start_seconds        REAL    NOT NULL,
    duration_seconds     REAL    NOT NULL,
    manual_counts        TEXT    NOT NULL,    -- JSON {"N through": 123, ...}
    notes                TEXT    NOT NULL DEFAULT '',
    created_at           TEXT    NOT NULL,
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
    -- Phase A instrumentation for the turn classifier: store the
    -- decision factors so a misclassification can be audited after
    -- the fact without re-running detection. Nullable for backfill
    -- compatibility with rows written before this column landed.
    classifier_net_heading_change   REAL,
    classifier_cumulative_curvature REAL,
    classifier_path_straightness    REAL,
    classifier_path_distance        REAL,
    classifier_num_points           INTEGER,
    -- Destination-leg classification (bug #5 Phase B). The pipeline now
    -- picks a destination leg per track and derives movement from the
    -- (origin, destination) geometry, replacing the angle-bucket
    -- classifier that biased everything toward "through". Posterior is
    -- the full softmax over all legs so review tools can re-pick.
    destination_leg_id              INTEGER,
    destination_confidence          REAL,
    destination_posterior_json      TEXT,
    -- Precomputed near-tie margin P(top)-P(2nd) of the posterior (1.0 = peaked),
    -- so the review flag feeder can filter ambiguous-movement events in SQL
    -- instead of parsing every posterior in Python. See services/posterior.py.
    destination_margin              REAL,
    -- Partial-evidence posterior (item-8 mechanism 1, posterior half): the
    -- ORIGIN posterior for tracks with no entry-gate evidence, counted at the
    -- posterior max. Margin below ORIGIN_POSTERIOR_MARGIN_FLOOR feeds the
    -- origin_ambiguous flag subtype. NULL everywhere else (incl. legacy).
    origin_posterior_json           TEXT,
    origin_margin                   REAL,
    -- Which posterior branch produced this event (conservation-pass join key
    -- + run-2 instrumentation): 'branch1' / 'rescue_full' / 'rescue_supports'
    -- / 'dest_tie'. NULL = the legacy chain (non-additive).
    posterior_source                TEXT,
    -- §3-D articulated: the vehicle's max bbox length + center-y at that max, for
    -- the view-invariant size test (semi vs box truck). See services/articulated.py.
    bbox_length                     REAL,
    bbox_center_y                   REAL,
    FOREIGN KEY (origin_leg_id) REFERENCES legs(leg_id),
    FOREIGN KEY (video_id) REFERENCES videos(video_id),
    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id),
    FOREIGN KEY (trim_id) REFERENCES trims(trim_id)
);

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

-- v3: per-intersection processing status that survives app restart.
-- Without this, _v3_jobs (memory only) is lost on restart and the UI
-- can't tell a mid-run shutdown from an idle intersection — so a user
-- clicks Start and double-counts on top of partial prior events.
CREATE TABLE IF NOT EXISTS v3_run_state (
    intersection_id INTEGER PRIMARY KEY,
    status          TEXT NOT NULL,        -- queued|running|interrupted|complete|cancelled|error
    error_message   TEXT,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (intersection_id) REFERENCES intersections(intersection_id)
);

-- Phase 3: auto-calibration suggestion produced by the background worker.
-- One row per camera; older suggestions get overwritten when a fresh run
-- finishes. payload_json holds the full AutoCalibrator output (zones,
-- paths, polylines, supporting counts). Engineer reviews + accepts via
-- the suggestion API; on apply, paths are copied to intersection_paths.
CREATE TABLE IF NOT EXISTS calibration_suggestions (
    suggestion_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id       INTEGER NOT NULL UNIQUE,
    payload_json    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending', -- pending|applied|rejected
    generated_at    TEXT    NOT NULL,
    applied_at      TEXT,
    job_metadata    TEXT,                                -- sample window, n_trajectories, etc
    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id)
);

-- Phase B review flag queue (MASTER_PLAN §3-B). Two feeders write here:
--   kind='uncertain_event' — event-anchored, low confidence / ambiguous class —
--                            "what the system is unsure about".
--   kind='suspected_gap'   — an interval+approach the run looks to UNDER-count,
--                            from the blind coverage/conservation diagnostic —
--                            "what it MISSED" (an undetected vehicle emits no
--                            event, so a confidence queue alone can never see it).
-- `impact` (estimated affected vehicles) drives worklist ordering. Rebuild is
-- idempotent: it clears status='open' rows and re-derives, keeping worked history.
-- `event_id` is deliberately NOT a foreign key: apply_bank.py deletes/rebuilds
-- vehicle_events on every re-bank, and an enforced child->parent FK would crash
-- that delete or cascade away resolved-flag history. Enrichment LEFT-JOINs and
-- tolerates a vanished event (it is skipped and auto-cleared on next rebuild).
CREATE TABLE IF NOT EXISTS review_flags (
    flag_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    intersection_id        INTEGER NOT NULL,
    camera_id              INTEGER,
    kind                   TEXT NOT NULL,                 -- uncertain_event | suspected_gap
    subtype                TEXT NOT NULL,                 -- low_traj_conf | ambiguous_dest | coverage_sag | ...
    event_id               INTEGER,                       -- nullable; NO FK (see note above)
    interval_start_seconds REAL,                          -- nullable; gap window (video time)
    interval_end_seconds   REAL,
    approach               TEXT,                          -- bound-approach label, e.g. 'NB'
    movement               TEXT,                          -- through|left|right|u_turn
    impact                 REAL NOT NULL DEFAULT 1,
    reason                 TEXT NOT NULL DEFAULT '',       -- human "why flagged"
    evidence_json          TEXT,                           -- JSON: baseline/observed/posterior
    batch_key              TEXT,                           -- groups identically-resolvable flags
    status                 TEXT NOT NULL DEFAULT 'open',   -- open|accepted|dismissed|resolved
    created_at             TEXT NOT NULL,
    resolved_at            TEXT,
    FOREIGN KEY (intersection_id) REFERENCES intersections(intersection_id),
    FOREIGN KEY (camera_id)       REFERENCES cameras(camera_id)
);
"""

# Indexes are kept out of SCHEMA because they reference columns added by the
# migration pass below; on legacy DBs the columns don't exist yet at the time
# SCHEMA runs, so the indexes have to be created AFTER migrations.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_events_video  ON vehicle_events(video_id);
CREATE INDEX IF NOT EXISTS idx_events_camera ON vehicle_events(camera_id);
CREATE INDEX IF NOT EXISTS idx_events_trim   ON vehicle_events(trim_id);
-- Covering index for the conservation/acceptance aggregations
-- (_cardinal_volumes GROUP BY origin/dest over a camera set). The DB lives on a
-- OneDrive-synced path where scattered table-row reads are pathologically slow
-- (~26s/intersection cold); this index makes the grouped query index-only
-- (USING COVERING INDEX), cutting the export/QA gate from ~100s to seconds.
-- video_id is appended so coverage_qa._binned_io (the flag-rebuild corridor-gap
-- scan, which JOINs videos for recording_start) is ALSO index-only — else its
-- GROUP BY drags in every row's trajectory_data blob (the >2-min rebuild hang).
-- New name (not IF-NOT-EXISTS on the old one) so the one-time widen is idempotent.
DROP INDEX IF EXISTS idx_events_cardinal;
CREATE INDEX IF NOT EXISTS idx_events_cardinal_v ON vehicle_events(camera_id, rejected, destination_leg_id, origin_leg_id, timestamp_video, video_id);
-- Covering index for the export/preview TMC aggregation (GROUP BY origin_leg_id,
-- movement[, fhwa_class]). Without it a full-table scan drags in every row's large
-- trajectory_data blob (~50s cold on the OneDrive DB); index-only here. Includes
-- fhwa_class so the L/M/A class breakdown (Phase 3E) is index-only too. Supersedes
-- the earlier 2-col idx_events_origin_movement (dropped).
DROP INDEX IF EXISTS idx_events_origin_movement;
CREATE INDEX IF NOT EXISTS idx_events_tmv ON vehicle_events(origin_leg_id, movement, fhwa_class);
-- feed_uncertain_events seeks only the events that could trip a standalone flag
-- (low detection confidence OR small destination margin), within the active,
-- non-edited set. The precomputed destination_margin lets that filter run on the
-- index (no per-event posterior parse, no 30k-row Python materialize); the OR is
-- evaluated index-only within each camera's (rejected=0, manually_edited=0)
-- partition, and only the few candidates read their full rows.
CREATE INDEX IF NOT EXISTS idx_events_uncertain ON vehicle_events(camera_id, rejected, manually_edited, detection_confidence, destination_margin);
CREATE INDEX IF NOT EXISTS idx_paths_camera  ON intersection_paths(camera_id);
CREATE INDEX IF NOT EXISTS idx_flags_isect_status ON review_flags(intersection_id, status);
CREATE INDEX IF NOT EXISTS idx_flags_event        ON review_flags(event_id);
"""


def get_project_dir(project_id: str) -> Path:
    """Return the directory for a project. Creates it if needed."""
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def get_db_path(project_id: str) -> Path:
    """Return the path to a project's SQLite database."""
    return get_project_dir(project_id) / "project.db"


def _backfill_destination_margin(conn: sqlite3.Connection) -> None:
    """Populate destination_margin for events that lack it. On the initial
    migration this is every legacy event (one-time; heavy on the OneDrive DB but
    bounded); in steady state it is zero, because the pipeline sets the margin at
    write time. Targets only NULL rows so a stray writer that forgot the column
    triggers a cheap incremental fix, not a full re-scan."""
    rows = conn.execute(
        "SELECT event_id, destination_posterior_json FROM vehicle_events "
        "WHERE destination_margin IS NULL").fetchall()
    if not rows:
        return
    conn.executemany(
        "UPDATE vehicle_events SET destination_margin = ? WHERE event_id = ?",
        [(margin_from_json(pj), eid) for eid, pj in rows])


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
    # Wait up to 5s for a write lock instead of failing instantly with
    # "database is locked" — matters under WAL when connections churn rapidly
    # (and on OneDrive-backed paths that briefly hold file locks).
    conn.execute("PRAGMA busy_timeout=5000")
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
    # Classifier instrumentation (Phase A of bug #5 turn-classifier work).
    # Nullable so legacy rows simply have NULL — no need to backfill.
    if "classifier_net_heading_change" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN classifier_net_heading_change REAL")
    if "classifier_cumulative_curvature" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN classifier_cumulative_curvature REAL")
    if "classifier_path_straightness" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN classifier_path_straightness REAL")
    if "classifier_path_distance" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN classifier_path_distance REAL")
    if "classifier_num_points" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN classifier_num_points INTEGER")
    # Phase B columns: destination-leg classification.
    if "destination_leg_id" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN destination_leg_id INTEGER")
    if "destination_confidence" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN destination_confidence REAL")
    if "destination_posterior_json" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN destination_posterior_json TEXT")
    if "destination_margin" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN destination_margin REAL")
    # 2026-07-06: per-vehicle max bbox length + its center-y, for the §3-D
    # articulated size test (exact from the tracker -> no cache re-linking).
    if "bbox_length" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN bbox_length REAL")
    if "bbox_center_y" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN bbox_center_y REAL")
    # 2026-07-15: partial-evidence posterior (posterior half) — origin
    # posterior + margin for unevidenced tracks. Nullable, no backfill:
    # legacy rows and evidenced tracks simply have NULL (never flagged).
    if "origin_posterior_json" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN origin_posterior_json TEXT")
    if "origin_margin" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN origin_margin REAL")
    if "posterior_source" not in ev_cols:
        conn.execute("ALTER TABLE vehicle_events ADD COLUMN posterior_source TEXT")
    # One-time backfill, guarded by an O(1) sentinel — the NULL-margin probe is a
    # full scan, so we must NOT run it on every connection. New events get their
    # margin at write time; any stray NULL is still caught by the feeder's
    # `destination_margin IS NULL` net, so a single backfill is sufficient.
    if conn.execute("SELECT value FROM project_info WHERE key = "
                    "'destination_margin_backfilled'").fetchone() is None:
        _backfill_destination_margin(conn)
        conn.execute("INSERT OR REPLACE INTO project_info (key, value) "
                     "VALUES ('destination_margin_backfilled', '1')")

    # Detection cache (Attribution v2 / Step 1): a stable content hash per video
    # keys the per-(camera, hash) Parquet detection cache. Nullable; computed
    # lazily on first cache write. See backend/services/detection_cache.py.
    vid_cols = [r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()]
    if "content_hash" not in vid_cols:
        conn.execute("ALTER TABLE videos ADD COLUMN content_hash TEXT DEFAULT NULL")
    if "content_hash_method" not in vid_cols:
        conn.execute("ALTER TABLE videos ADD COLUMN content_hash_method TEXT DEFAULT NULL")

    cp_cols = [r[1] for r in conn.execute("PRAGMA table_info(checkpoint)").fetchall()]
    if "current_video_id" not in cp_cols:
        conn.execute("ALTER TABLE checkpoint ADD COLUMN current_video_id INTEGER DEFAULT NULL")
    if "current_camera_id" not in cp_cols:
        conn.execute("ALTER TABLE checkpoint ADD COLUMN current_camera_id INTEGER DEFAULT NULL")
    if "current_trim_id" not in cp_cols:
        conn.execute("ALTER TABLE checkpoint ADD COLUMN current_trim_id INTEGER DEFAULT NULL")

    # v3.calibration: per-intersection overrides for tunables the user can edit
    # in the leg-calibration UI. Nullable; NULL = fall back to backend/config.py.
    isect_cols = [r[1] for r in conn.execute("PRAGMA table_info(intersections)").fetchall()]
    if "calib_tripwire_half_length_px" not in isect_cols:
        conn.execute("ALTER TABLE intersections ADD COLUMN calib_tripwire_half_length_px REAL")
    if "calib_trajectory_through_max_angle" not in isect_cols:
        conn.execute("ALTER TABLE intersections ADD COLUMN calib_trajectory_through_max_angle REAL")
    if "calib_trajectory_turn_min_angle" not in isect_cols:
        conn.execute("ALTER TABLE intersections ADD COLUMN calib_trajectory_turn_min_angle REAL")
    if "calib_trajectory_uturn_min_angle" not in isect_cols:
        conn.execute("ALTER TABLE intersections ADD COLUMN calib_trajectory_uturn_min_angle REAL")

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

    # v3.calibration: per-camera detection/tracking knobs (NULL = use config.py).
    cam_cols = [r[1] for r in conn.execute("PRAGMA table_info(cameras)").fetchall()]
    if "calib_pre_track_nms_iou" not in cam_cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN calib_pre_track_nms_iou REAL")
    if "calib_tracker_lost_buffer" not in cam_cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN calib_tracker_lost_buffer INTEGER")
    if "calib_tracker_match_threshold" not in cam_cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN calib_tracker_match_threshold REAL")
    if "calib_tracker_activation_threshold" not in cam_cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN calib_tracker_activation_threshold REAL")
    # Phase 1 tracker knobs (docs/implementation_plan_architecture_2026-06-11.md):
    # buffered-IoU box inflation, finalize-time track-quality gate, and the
    # BoT-SORT birth threshold (distinct from activation/track_high).
    if "calib_bbox_buffer_scale" not in cam_cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN calib_bbox_buffer_scale REAL")
    if "calib_track_quality_filter" not in cam_cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN calib_track_quality_filter INTEGER")
    if "calib_new_track_thresh" not in cam_cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN calib_new_track_thresh REAL")
    # Phase 2.3: per-camera joint-scorer cost metric (NULL = config default).
    if "calib_cost_metric" not in cam_cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN calib_cost_metric TEXT")
    # 2026-07-02: per-camera speed-tiebreak opt-in (NULL = config default, 0 off, 1 on).
    if "calib_speed_tiebreak" not in cam_cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN calib_speed_tiebreak INTEGER")
    # 2026-07-10 (two-pass stage 3): per-camera pass-1 tracking recipe.
    # NULL = 'bytetrack' (live default). 'botsort' / 'botsort+reid' where the
    # A2 tier-2 context showed the live table depends on it (cam1 ReID
    # recovers -529 NB-thru; cam2's live table is a BoT product).
    if "calib_pass1_backend" not in cam_cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN calib_pass1_backend TEXT")

    # 2026-07-02: per-path pixel-speed signature (median step of supporting
    # tracks) feeding the shared-exit collinear speed-tiebreak; NULL = unset.
    ip_cols = [r[1] for r in conn.execute("PRAGMA table_info(intersection_paths)").fetchall()]
    if "expected_speed" not in ip_cols:
        conn.execute("ALTER TABLE intersection_paths ADD COLUMN expected_speed REAL")
    # 2026-07-10 (A4a): duration the supporting_count sample covered — scales
    # the turn-merge volume gate to the counting window. NULL = unknown; the
    # merge falls back to 1800 s (the corridor banks were 30-min samples) with
    # a logged warning. Corpus-built banks (§3-A) write the corpus window.
    if "sample_window_seconds" not in ip_cols:
        conn.execute("ALTER TABLE intersection_paths ADD COLUMN sample_window_seconds REAL")

    # Indexes after migrations so legacy DBs that gained columns above
    # can be indexed on them now that they exist.
    conn.executescript(INDEXES)

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
    "calib_tripwire_half_length_px",
    "calib_trajectory_through_max_angle",
    "calib_trajectory_turn_min_angle",
    "calib_trajectory_uturn_min_angle",
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


_CALIB_PARAM_COLUMNS = (
    "calib_tripwire_half_length_px",
    "calib_trajectory_through_max_angle",
    "calib_trajectory_turn_min_angle",
    "calib_trajectory_uturn_min_angle",
)
# Sentinel for "explicitly clear this override back to default" — distinct from
# "don't touch this field." Pass None as the SQL value to revert to NULL.
class _ClearToDefault:
    pass
CLEAR_TO_DEFAULT = _ClearToDefault()


def update_intersection(
    project_id: str,
    intersection_id: int,
    *,
    name: str | None = None,
    leg_count: int | None = None,
    sort_order: int | None = None,
    calib_tripwire_half_length_px: float | None | _ClearToDefault = None,
    calib_trajectory_through_max_angle: float | None | _ClearToDefault = None,
    calib_trajectory_turn_min_angle: float | None | _ClearToDefault = None,
    calib_trajectory_uturn_min_angle: float | None | _ClearToDefault = None,
) -> None:
    """Update an intersection. Each calib_* arg is three-state:
      - default (None): don't touch this column
      - CLEAR_TO_DEFAULT: set the column to NULL (revert to global default)
      - float value: set the column to that value
    """
    sets, params = [], []
    if name is not None:
        sets.append("name = ?"); params.append(name)
    if leg_count is not None:
        sets.append("leg_count = ?"); params.append(leg_count)
    if sort_order is not None:
        sets.append("sort_order = ?"); params.append(sort_order)
    for col, val in (
        ("calib_tripwire_half_length_px", calib_tripwire_half_length_px),
        ("calib_trajectory_through_max_angle", calib_trajectory_through_max_angle),
        ("calib_trajectory_turn_min_angle", calib_trajectory_turn_min_angle),
        ("calib_trajectory_uturn_min_angle", calib_trajectory_uturn_min_angle),
    ):
        if val is None:
            continue  # don't touch
        sets.append(f"{col} = ?")
        params.append(None if isinstance(val, _ClearToDefault) else float(val))
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


def get_calibration_params(project_id: str, intersection_id: int) -> dict:
    """Return the effective tunables for this intersection: each value is the
    per-intersection override when present, otherwise the global default from
    backend/config.py. Always returns a complete dict — callers can rely on
    every key existing.

    Raises ValueError if the intersection doesn't exist.
    """
    from backend.config import (
        TRIPWIRE_HALF_LENGTH_PX,
        TRAJECTORY_THROUGH_MAX_ANGLE,
        TRAJECTORY_TURN_MIN_ANGLE,
        TRAJECTORY_UTURN_MIN_ANGLE,
    )
    row = get_intersection(project_id, intersection_id)
    if row is None:
        raise ValueError(f"intersection {intersection_id} not found in {project_id}")
    overrides = {
        "tripwire_half_length_px": row.get("calib_tripwire_half_length_px"),
        "trajectory_through_max_angle": row.get("calib_trajectory_through_max_angle"),
        "trajectory_turn_min_angle": row.get("calib_trajectory_turn_min_angle"),
        "trajectory_uturn_min_angle": row.get("calib_trajectory_uturn_min_angle"),
    }
    defaults = {
        "tripwire_half_length_px": TRIPWIRE_HALF_LENGTH_PX,
        "trajectory_through_max_angle": TRAJECTORY_THROUGH_MAX_ANGLE,
        "trajectory_turn_min_angle": TRAJECTORY_TURN_MIN_ANGLE,
        "trajectory_uturn_min_angle": TRAJECTORY_UTURN_MIN_ANGLE,
    }
    return {k: (overrides[k] if overrides[k] is not None else defaults[k])
            for k in defaults}


# Per-camera detection/tracking knob keys. Stored as calib_<key> columns on the
# cameras table; resolved against backend/config.py defaults. Kept distinct from
# the per-intersection classification tunables above (different table, different
# concern: these are camera+resolution artifacts).
_CAMERA_CALIB_KEYS = (
    "pre_track_nms_iou",
    "tracker_lost_buffer",
    "tracker_match_threshold",
    "tracker_activation_threshold",
    "bbox_buffer_scale",
    "track_quality_filter",
    "new_track_thresh",
    "cost_metric",
)


def get_camera_calibration_params(project_id: str, camera_id: int) -> dict:
    """Effective tunables for one camera's pipeline run: the per-INTERSECTION
    classification tunables (from get_calibration_params, resolved to override-
    or-default) MERGED with the per-CAMERA detection/tracking knobs.

    NOTE the deliberate asymmetry: the per-camera knobs are returned as the RAW
    OVERRIDE — the configured value, or **None when unset** — NOT resolved to a
    config default. This is what feeds the pipeline's precedence chain
    (per-camera override > explicit/mode arg > config default): returning a
    resolved default here would make an unset knob indistinguishable from a real
    override and clobber a deliberate explicit/sweep value. Use
    resolve_camera_knob_defaults() for a display-friendly resolved view.

    Raises ValueError if the camera doesn't exist.
    """
    cam = get_camera(project_id, camera_id)
    if cam is None:
        raise ValueError(f"camera {camera_id} not found in {project_id}")
    params = get_calibration_params(project_id, cam["intersection_id"])

    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT calib_pre_track_nms_iou, calib_tracker_lost_buffer, "
            "calib_tracker_match_threshold, calib_tracker_activation_threshold, "
            "calib_bbox_buffer_scale, calib_track_quality_filter, "
            "calib_new_track_thresh, calib_cost_metric, calib_speed_tiebreak, "
            "calib_pass1_backend "
            "FROM cameras WHERE camera_id = ?",
            (camera_id,),
        ).fetchone()
    finally:
        conn.close()
    params["pre_track_nms_iou"] = row["calib_pre_track_nms_iou"]
    params["tracker_lost_buffer"] = row["calib_tracker_lost_buffer"]
    params["tracker_match_threshold"] = row["calib_tracker_match_threshold"]
    params["tracker_activation_threshold"] = row["calib_tracker_activation_threshold"]
    params["bbox_buffer_scale"] = row["calib_bbox_buffer_scale"]
    params["track_quality_filter"] = row["calib_track_quality_filter"]
    params["new_track_thresh"] = row["calib_new_track_thresh"]
    params["cost_metric"] = row["calib_cost_metric"]
    # None when unset -> pipeline resolves to the config default; 0/1 = explicit.
    params["speed_tiebreak"] = row["calib_speed_tiebreak"]
    # None -> 'bytetrack' at the pass-1 job (two-pass stage 3).
    params["pass1_backend"] = row["calib_pass1_backend"]
    return params


def resolve_camera_knob_defaults(knobs: dict) -> dict:
    """Resolve the per-camera knobs (raw overrides, None when unset) to their
    effective values against backend/config.py — for display in the calibration
    UI. The pipeline does NOT use this; it needs the raw overrides for its
    precedence chain. NMS resolves to the global PRE_TRACK_NMS_IOU (may be None).
    """
    from backend.config import (
        JOINT_SCORER_COST_METRIC, PRE_TRACK_NMS_IOU, TRACKER_LOST_BUFFER,
        TRACKER_MATCH_THRESHOLD, TRACKER_ACTIVATION_THRESHOLD,
    )
    defaults = {
        "pre_track_nms_iou": PRE_TRACK_NMS_IOU,
        "tracker_lost_buffer": TRACKER_LOST_BUFFER,
        "tracker_match_threshold": TRACKER_MATCH_THRESHOLD,
        "tracker_activation_threshold": TRACKER_ACTIVATION_THRESHOLD,
        # Phase 1 knobs: defaults = feature off / library default.
        "bbox_buffer_scale": 1.0,
        "track_quality_filter": 0,
        "new_track_thresh": 0.3,   # BoT-SORT wrapper default (tracker.py)
        "cost_metric": JOINT_SCORER_COST_METRIC,
    }
    return {k: (knobs[k] if knobs.get(k) is not None else defaults[k]) for k in defaults}


def update_camera_calibration(
    project_id: str,
    camera_id: int,
    *,
    calib_pre_track_nms_iou: float | None | _ClearToDefault = None,
    calib_tracker_lost_buffer: int | None | _ClearToDefault = None,
    calib_tracker_match_threshold: float | None | _ClearToDefault = None,
    calib_tracker_activation_threshold: float | None | _ClearToDefault = None,
    calib_bbox_buffer_scale: float | None | _ClearToDefault = None,
    calib_track_quality_filter: int | None | _ClearToDefault = None,
    calib_new_track_thresh: float | None | _ClearToDefault = None,
    calib_cost_metric: str | None | _ClearToDefault = None,
    calib_speed_tiebreak: int | None | _ClearToDefault = None,
) -> None:
    """Update a camera's per-camera detection/tracking knobs. Each arg is
    three-state (mirrors update_intersection):
      - default (None): don't touch this column
      - CLEAR_TO_DEFAULT: set the column to NULL (revert to config default)
      - value: set the column to that value
    """
    sets, params = [], []
    for col, val, cast in (
        ("calib_pre_track_nms_iou", calib_pre_track_nms_iou, float),
        ("calib_tracker_lost_buffer", calib_tracker_lost_buffer, int),
        ("calib_tracker_match_threshold", calib_tracker_match_threshold, float),
        ("calib_tracker_activation_threshold", calib_tracker_activation_threshold, float),
        ("calib_bbox_buffer_scale", calib_bbox_buffer_scale, float),
        ("calib_track_quality_filter", calib_track_quality_filter, int),
        ("calib_new_track_thresh", calib_new_track_thresh, float),
        ("calib_cost_metric", calib_cost_metric, str),
        ("calib_speed_tiebreak", calib_speed_tiebreak, int),
    ):
        if val is None:
            continue  # don't touch
        sets.append(f"{col} = ?")
        params.append(None if isinstance(val, _ClearToDefault) else cast(val))
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


def remove_intersection(project_id: str, intersection_id: int) -> None:
    """Cascade-delete: trims, cameras, legs (via camera FK), review flags, and
    unlink videos."""
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
            conn.execute("DELETE FROM review_flags WHERE intersection_id = ?", (intersection_id,))
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
    """Cascade-delete: legs, review flags, unlink videos."""
    conn = get_connection(project_id)
    try:
        with conn:
            conn.execute("DELETE FROM legs WHERE camera_id = ?", (camera_id,))
            conn.execute("UPDATE videos SET camera_id = NULL WHERE camera_id = ?", (camera_id,))
            conn.execute("DELETE FROM review_flags WHERE camera_id = ?", (camera_id,))
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


# -- v3: per-intersection run state ----------------------------------------

# Statuses that mean "a pipeline thread should be running, or was running
# when something interrupted it". We refuse a fresh Start in any of these,
# and the startup heal step downgrades 'running' to 'interrupted'.
_V3_RUN_STATE_ACTIVE = ("queued", "running", "interrupted")


def set_v3_run_state(
    project_id: str,
    intersection_id: int,
    status: str,
    error_message: str | None = None,
) -> None:
    """Upsert the persisted processing status for one intersection."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection(project_id)
    try:
        conn.execute(
            """INSERT INTO v3_run_state
                 (intersection_id, status, error_message, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(intersection_id) DO UPDATE SET
                 status = excluded.status,
                 error_message = excluded.error_message,
                 updated_at = excluded.updated_at""",
            (intersection_id, status, error_message, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_v3_run_state(project_id: str, intersection_id: int) -> dict | None:
    """Read the persisted processing status. None if no row exists (= idle)."""
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM v3_run_state WHERE intersection_id = ?",
            (intersection_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "intersection_id": row["intersection_id"],
            "status": row["status"],
            "error_message": row["error_message"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def clear_v3_run_state(project_id: str, intersection_id: int) -> None:
    """Delete the run-state row entirely (back to idle)."""
    conn = get_connection(project_id)
    try:
        conn.execute(
            "DELETE FROM v3_run_state WHERE intersection_id = ?",
            (intersection_id,),
        )
        conn.commit()
    finally:
        conn.close()


def heal_v3_running_to_interrupted(project_id: str) -> list[int]:
    """Server-start cleanup: any 'running' row had its thread killed by
    the restart, so flip it to 'interrupted' (the state the resume UI
    cares about). Returns the intersection_ids that were healed.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection(project_id)
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT intersection_id FROM v3_run_state WHERE status = 'running'"
        ).fetchall()]
        if ids:
            conn.execute(
                """UPDATE v3_run_state
                   SET status = 'interrupted', updated_at = ?
                   WHERE status = 'running'""",
                (now,),
            )
            conn.commit()
        return ids
    finally:
        conn.close()


# -- v3: intersection_paths helpers ------------------------------------------
#
# The polyline-based calibration table. One row per (origin_leg,
# destination_leg) pair per camera. Pipeline reads these to do origin
# attribution, destination scoring, and movement labeling in a single
# polyline-match pass — replacing the per-frame tripwire crossing + the
# softmax destination scorer + derive_movement when paths are present.

_PATH_FIELDS = (
    "path_id", "camera_id", "origin_leg_id", "destination_leg_id",
    "polyline", "movement_label", "supporting_count", "expected_speed", "source",
    "last_observed_at", "created_at",
)


def _row_to_path(row: sqlite3.Row) -> dict:
    out = {k: row[k] for k in _PATH_FIELDS}
    # Parse the polyline JSON eagerly — callers always want the list form.
    if isinstance(out["polyline"], str):
        try:
            out["polyline"] = json.loads(out["polyline"])
        except (TypeError, ValueError):
            out["polyline"] = []
    return out


def list_paths_for_camera(project_id: str, camera_id: int) -> list[dict]:
    """All paths for a camera, ordered by (origin_leg_id, destination_leg_id)."""
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM intersection_paths WHERE camera_id = ? "
            "ORDER BY origin_leg_id, destination_leg_id",
            (camera_id,),
        ).fetchall()
        return [_row_to_path(r) for r in rows]
    finally:
        conn.close()


def upsert_path(
    project_id: str,
    camera_id: int,
    origin_leg_id: int,
    destination_leg_id: int,
    polyline: list,
    movement_label: str,
    *,
    source: str = "manual",
    supporting_count: int = 0,
    last_observed_at: str | None = None,
) -> int:
    """Insert-or-replace a path keyed by (camera_id, origin_leg, dest_leg).
    Returns path_id."""
    now = datetime.now(timezone.utc).isoformat()
    poly_json = json.dumps(polyline)
    conn = get_connection(project_id)
    try:
        with conn:
            existing = conn.execute(
                "SELECT path_id, created_at FROM intersection_paths "
                "WHERE camera_id = ? AND origin_leg_id = ? AND destination_leg_id = ?",
                (camera_id, origin_leg_id, destination_leg_id),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE intersection_paths
                       SET polyline = ?, movement_label = ?,
                           supporting_count = ?, source = ?,
                           last_observed_at = COALESCE(?, last_observed_at)
                     WHERE path_id = ?""",
                    (poly_json, movement_label, supporting_count, source,
                     last_observed_at, existing[0]),
                )
                return int(existing[0])
            cur = conn.execute(
                """INSERT INTO intersection_paths
                   (camera_id, origin_leg_id, destination_leg_id,
                    polyline, movement_label, supporting_count,
                    source, last_observed_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (camera_id, origin_leg_id, destination_leg_id,
                 poly_json, movement_label, supporting_count,
                 source, last_observed_at, now),
            )
            return int(cur.lastrowid)
    finally:
        conn.close()


def delete_path(project_id: str, path_id: int) -> None:
    """Delete a single path row."""
    conn = get_connection(project_id)
    try:
        conn.execute("DELETE FROM intersection_paths WHERE path_id = ?", (path_id,))
        conn.commit()
    finally:
        conn.close()


def clear_paths_for_camera(project_id: str, camera_id: int) -> int:
    """Remove all paths for a camera. Returns count deleted."""
    conn = get_connection(project_id)
    try:
        cur = conn.execute(
            "DELETE FROM intersection_paths WHERE camera_id = ?", (camera_id,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# -- Operator-drawn channels (Phase 2.1) --------------------------------------

def _row_to_channel(row: sqlite3.Row) -> dict:
    return {
        "channel_id": row["channel_id"],
        "camera_id": row["camera_id"],
        "origin_leg_id": row["origin_leg_id"],
        "destination_leg_id": row["destination_leg_id"],
        "movement": row["movement"],
        "entry": json.loads(row["entry_pt"]),
        "apex": json.loads(row["apex_pt"]),
        "exit": json.loads(row["exit_pt"]),
        "width_in": row["width_in"],
        "width_out": row["width_out"],
        "created_at": row["created_at"],
    }


def list_channels_for_camera(project_id: str, camera_id: int) -> list[dict]:
    """All operator-drawn channels for a camera."""
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM channels WHERE camera_id = ? "
            "ORDER BY origin_leg_id, destination_leg_id, channel_id",
            (camera_id,),
        ).fetchall()
        return [_row_to_channel(r) for r in rows]
    finally:
        conn.close()


def replace_channels_for_camera(project_id: str, camera_id: int,
                                channels: list[dict]) -> list[dict]:
    """Full replace of a camera's channels (the editor saves the whole set).
    Touches ONLY the channels table — never events or paths."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection(project_id)
    try:
        with conn:
            conn.execute("DELETE FROM channels WHERE camera_id = ?", (camera_id,))
            for ch in channels:
                conn.execute(
                    """INSERT INTO channels
                       (camera_id, origin_leg_id, destination_leg_id, movement,
                        entry_pt, apex_pt, exit_pt, width_in, width_out, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (camera_id, ch["origin_leg_id"], ch["destination_leg_id"],
                     ch["movement"], json.dumps(ch["entry"]), json.dumps(ch["apex"]),
                     json.dumps(ch["exit"]), float(ch.get("width_in", 40)),
                     float(ch.get("width_out", 40)), now),
                )
    finally:
        conn.close()
    return list_channels_for_camera(project_id, camera_id)


# -- v3: auto-calibration suggestions ----------------------------------------
#
# Phase 3 storage for the background AutoCalibrator's output. One row per
# camera (unique constraint). Engineers review via the suggestion API and
# either apply (copies paths into intersection_paths) or reject.

_SUGGESTION_FIELDS = (
    "suggestion_id", "camera_id", "payload_json", "status",
    "generated_at", "applied_at", "job_metadata",
)


def _row_to_suggestion(row: sqlite3.Row) -> dict:
    out = {k: row[k] for k in _SUGGESTION_FIELDS}
    if isinstance(out.get("payload_json"), str):
        try:
            out["payload"] = json.loads(out["payload_json"])
        except (TypeError, ValueError):
            out["payload"] = {}
    else:
        out["payload"] = out.get("payload_json") or {}
    if isinstance(out.get("job_metadata"), str):
        try:
            out["job_metadata"] = json.loads(out["job_metadata"])
        except (TypeError, ValueError):
            pass
    return out


def get_calibration_suggestion(project_id: str, camera_id: int) -> dict | None:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM calibration_suggestions WHERE camera_id = ?",
            (camera_id,),
        ).fetchone()
        return _row_to_suggestion(row) if row else None
    finally:
        conn.close()


def save_calibration_suggestion(
    project_id: str, camera_id: int, payload: dict,
    job_metadata: dict | None = None,
) -> int:
    """Insert-or-replace the suggestion for this camera. Always resets
    status to 'pending' so a fresh suggestion is reviewable again."""
    now = datetime.now(timezone.utc).isoformat()
    payload_str = json.dumps(payload)
    meta_str = json.dumps(job_metadata or {})
    conn = get_connection(project_id)
    try:
        with conn:
            existing = conn.execute(
                "SELECT suggestion_id FROM calibration_suggestions "
                "WHERE camera_id = ?", (camera_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE calibration_suggestions
                       SET payload_json = ?, status = 'pending',
                           generated_at = ?, applied_at = NULL,
                           job_metadata = ?
                     WHERE camera_id = ?""",
                    (payload_str, now, meta_str, camera_id),
                )
                return int(existing[0])
            cur = conn.execute(
                """INSERT INTO calibration_suggestions
                   (camera_id, payload_json, status, generated_at, job_metadata)
                   VALUES (?, ?, 'pending', ?, ?)""",
                (camera_id, payload_str, now, meta_str),
            )
            return int(cur.lastrowid)
    finally:
        conn.close()


def mark_suggestion_applied(project_id: str, camera_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection(project_id)
    try:
        conn.execute(
            "UPDATE calibration_suggestions SET status='applied', applied_at=? "
            "WHERE camera_id=?", (now, camera_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_suggestion_rejected(project_id: str, camera_id: int) -> None:
    conn = get_connection(project_id)
    try:
        conn.execute(
            "UPDATE calibration_suggestions SET status='rejected' WHERE camera_id=?",
            (camera_id,),
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
    # Once a project has been initialized under v3 (via save-labels or a prior
    # bootstrap), never auto-create a default intersection again — otherwise
    # deleting an intersection (which unlinks its videos) would resurrect a
    # phantom 'Main intersection' on the next list.
    if get_project_info(project_id, "v3_initialized"):
        return None

    conn = get_connection(project_id)
    try:
        n_videos = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        n_unlinked = (
            conn.execute(
                "SELECT COUNT(*) FROM videos WHERE camera_id IS NULL"
            ).fetchone()[0]
            if n_videos else 0
        )
        date_str = None
        if n_videos and n_unlinked:
            # Earliest recording time among unlinked videos; fall back to today.
            date_row = conn.execute(
                """SELECT COALESCE(MIN(recording_start_datetime),
                                   MIN(recording_start_time),
                                   MIN(creation_time))
                   FROM videos WHERE camera_id IS NULL"""
            ).fetchone()
            date_str = (date_row[0] or datetime.now().isoformat())[:10]
    finally:
        conn.close()

    if n_videos == 0:
        return None
    if n_unlinked == 0:
        # Already linked by a v3 path — mark initialized so a later unlink
        # (e.g. an intersection delete) can't trigger a phantom bootstrap.
        set_project_info(project_id, "v3_initialized", "1")
        return None

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

    set_project_info(project_id, "v3_initialized", "1")
    return iid


# -- Phase B: review flag queue ----------------------------------------------
#
# The two-feeder blind-QA queue (MASTER_PLAN §3-B). insert_flag() takes the same
# kwargs the feeders build, so a feeder can return a list of dicts and the
# orchestrator just does insert_flag(**f). evidence_json is eager-parsed back to
# a dict on read (the same convention as intersection_paths.polyline).

_FLAG_FIELDS = (
    "flag_id", "intersection_id", "camera_id", "kind", "subtype", "event_id",
    "interval_start_seconds", "interval_end_seconds", "approach", "movement",
    "impact", "reason", "evidence_json", "batch_key", "status",
    "created_at", "resolved_at",
)

# auto_resolved is MACHINE state (queue_autoresolve rules): terminal for
# resolved_at stamping, but cleared+re-derived on rebuild and NOT counted
# as operator-worked by the feeders (self-healing; reopenable).
_FLAG_TERMINAL_STATUSES = ("accepted", "dismissed", "resolved", "auto_resolved")
_FLAG_STATUSES = ("open",) + _FLAG_TERMINAL_STATUSES


def _row_to_flag(row: sqlite3.Row) -> dict:
    out = {k: row[k] for k in _FLAG_FIELDS}
    raw = out.pop("evidence_json")
    if isinstance(raw, str):
        try:
            out["evidence"] = json.loads(raw)
        except (TypeError, ValueError):
            out["evidence"] = {}
    else:
        out["evidence"] = raw or {}
    return out


def insert_flag(
    project_id: str,
    *,
    intersection_id: int,
    kind: str,
    subtype: str,
    camera_id: int | None = None,
    event_id: int | None = None,
    interval_start_seconds: float | None = None,
    interval_end_seconds: float | None = None,
    approach: str | None = None,
    movement: str | None = None,
    impact: float = 1.0,
    reason: str = "",
    evidence: dict | None = None,
    batch_key: str | None = None,
    status: str = "open",
) -> int:
    """Insert one review flag. Returns flag_id."""
    now = datetime.now(timezone.utc).isoformat()
    ev = json.dumps(evidence) if evidence is not None else None
    conn = get_connection(project_id)
    try:
        cur = conn.execute(
            """INSERT INTO review_flags
               (intersection_id, camera_id, kind, subtype, event_id,
                interval_start_seconds, interval_end_seconds, approach, movement,
                impact, reason, evidence_json, batch_key, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (intersection_id, camera_id, kind, subtype, event_id,
             interval_start_seconds, interval_end_seconds, approach, movement,
             float(impact), reason, ev, batch_key, status, now),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def insert_flags(project_id: str, intersection_id: int, flags: list[dict]) -> int:
    """Batch-insert review flags in ONE transaction. rebuild_flags inserts
    hundreds at once; per-flag insert_flag() opens + commits + closes a connection
    each time, and on the OneDrive-backed DB each commit is a slow fsync/sync
    (533 flags took ~16 min). One connection + executemany + one commit collapses
    that to a single sync. Each dict uses the insert_flag(...) keyword names (minus
    project_id/intersection_id). Returns the number inserted."""
    if not flags:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for f in flags:
        ev = f.get("evidence")
        status = f.get("status", "open")
        rows.append((
            intersection_id, f.get("camera_id"), f["kind"], f["subtype"], f.get("event_id"),
            f.get("interval_start_seconds"), f.get("interval_end_seconds"),
            f.get("approach"), f.get("movement"), float(f.get("impact", 1.0)),
            f.get("reason", ""), json.dumps(ev) if ev is not None else None,
            f.get("batch_key"), status, now,
            now if status in _FLAG_TERMINAL_STATUSES else None))
    conn = get_connection(project_id)
    try:
        conn.executemany(
            """INSERT INTO review_flags
               (intersection_id, camera_id, kind, subtype, event_id,
                interval_start_seconds, interval_end_seconds, approach, movement,
                impact, reason, evidence_json, batch_key, status, created_at,
                resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def list_flags(
    project_id: str,
    intersection_id: int,
    *,
    status: str | None = "open",
    kind: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """Flags for an intersection, impact-DESC then oldest-first. status=None or
    'all' returns every status; otherwise filter to that one status."""
    where = ["intersection_id = ?"]
    params: list = [intersection_id]
    if status not in (None, "all"):
        where.append("status = ?"); params.append(status)
    if kind is not None:
        where.append("kind = ?"); params.append(kind)
    sql = (f"SELECT * FROM review_flags WHERE {' AND '.join(where)} "
           "ORDER BY impact DESC, created_at ASC, flag_id ASC")
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"; params += [int(limit), int(offset)]
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_flag(r) for r in rows]
    finally:
        conn.close()


def get_flag(project_id: str, flag_id: int) -> dict | None:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM review_flags WHERE flag_id = ?", (flag_id,),
        ).fetchone()
        return _row_to_flag(row) if row else None
    finally:
        conn.close()


def update_flag_status(project_id: str, flag_id: int, status: str) -> None:
    """Set a flag's status; stamps resolved_at when terminal, clears it on reopen."""
    resolved_at = (datetime.now(timezone.utc).isoformat()
                   if status in _FLAG_TERMINAL_STATUSES else None)
    conn = get_connection(project_id)
    try:
        conn.execute(
            "UPDATE review_flags SET status = ?, resolved_at = ? WHERE flag_id = ?",
            (status, resolved_at, flag_id),
        )
        conn.commit()
    finally:
        conn.close()


def clear_open_flags(project_id: str, intersection_id: int) -> int:
    """Delete this intersection's OPEN and auto_resolved flags (the
    idempotent-rebuild primitive) — both are machine state, re-derived by
    the feeders + auto-resolution rules. Operator-worked flags
    (accepted/dismissed/resolved) are kept as history. Returns the number
    deleted."""
    conn = get_connection(project_id)
    try:
        cur = conn.execute(
            "DELETE FROM review_flags WHERE intersection_id = ? "
            "AND status IN ('open', 'auto_resolved')",
            (intersection_id,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def flag_summary(project_id: str, intersection_id: int) -> dict:
    """Counts by status and (open-only) by kind, plus the open-flag impact total
    — the remaining-work signal for the acceptance gate / stopping rule."""
    conn = get_connection(project_id)
    try:
        status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM review_flags WHERE intersection_id = ? "
            "GROUP BY status", (intersection_id,)).fetchall()
        kind_rows = conn.execute(
            "SELECT kind, COUNT(*), COALESCE(SUM(impact), 0) FROM review_flags "
            "WHERE intersection_id = ? AND status = 'open' GROUP BY kind",
            (intersection_id,)).fetchall()
        open_impact = conn.execute(
            "SELECT COALESCE(SUM(impact), 0) FROM review_flags "
            "WHERE intersection_id = ? AND status = 'open'",
            (intersection_id,)).fetchone()[0]
        # Worklist CARDS: batch-keyed flags collapse to one card per key;
        # unkeyed flags are one card each (plan_flood_control_2026-07-09).
        open_cards = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(batch_key, 'f' || flag_id)) "
            "FROM review_flags WHERE intersection_id = ? AND status = 'open'",
            (intersection_id,)).fetchone()[0]
    finally:
        conn.close()
    by_status = {s: n for s, n in status_rows}
    return {
        "intersection_id": intersection_id,
        "open": by_status.get("open", 0),
        "accepted": by_status.get("accepted", 0),
        "dismissed": by_status.get("dismissed", 0),
        "resolved": by_status.get("resolved", 0),
        # machine-closed (queue_autoresolve): shown so the operator can see
        # and audit what the rules decided for them (child-test visibility)
        "auto_resolved": by_status.get("auto_resolved", 0),
        "by_kind": {k: n for k, n, _imp in kind_rows},
        # Per-kind OPEN impact — the gate needs suspected_gap impact (estimated
        # missed vehicles) separately from uncertain_event count, since their
        # units differ and must NOT be summed. See spot_check.acceptance().
        "open_impact_by_kind": {k: round(float(imp), 1) for k, _n, imp in kind_rows},
        "open_impact": round(float(open_impact), 1),
        "open_cards": open_cards,
    }


def batch_resolve_flags(project_id: str, intersection_id: int, batch_key: str,
                        status: str, movement: str | None = None) -> dict:
    """Apply a status to ALL open flags sharing a batch_key in an intersection,
    optionally setting `movement` on their anchored events first (mirrors the
    single-edit path in routers/review.py: movement + manually_edited=1). Powers
    the worklist's one-key batch resolve.

    Returns {"affected": n, "changes": [...]} where changes carries each
    member's PRIOR values (captured in the same transaction, before the
    UPDATEs) — the worklist's undo stack needs them to revert a batch without
    leaving events falsely marked operator-edited (plan_C_polish §3b)."""
    resolved_at = (datetime.now(timezone.utc).isoformat()
                   if status in _FLAG_TERMINAL_STATUSES else None)
    conn = get_connection(project_id)
    try:
        with conn:
            rows = conn.execute(
                "SELECT f.flag_id, f.event_id, e.movement, e.manually_edited "
                "FROM review_flags f "
                "LEFT JOIN vehicle_events e ON e.event_id = f.event_id "
                "WHERE f.intersection_id = ? AND f.batch_key = ? "
                "AND f.status = 'open'",
                (intersection_id, batch_key)).fetchall()
            if not rows:
                return {"affected": 0, "changes": []}
            changes = [{"flag_id": r[0], "event_id": r[1],
                        "prior_movement": r[2], "prior_manually_edited": r[3]}
                       for r in rows]
            flag_ids = [r[0] for r in rows]
            event_ids = [r[1] for r in rows if r[1] is not None]
            if movement and event_ids:
                ph = ",".join("?" * len(event_ids))
                conn.execute(
                    f"UPDATE vehicle_events SET movement = ?, manually_edited = 1 "
                    f"WHERE event_id IN ({ph})", [movement, *event_ids])
            ph = ",".join("?" * len(flag_ids))
            conn.execute(
                f"UPDATE review_flags SET status = ?, resolved_at = ? "
                f"WHERE flag_id IN ({ph})", [status, resolved_at, *flag_ids])
        return {"affected": len(flag_ids), "changes": changes}
    finally:
        conn.close()
