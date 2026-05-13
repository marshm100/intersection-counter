# TDD — Intersection Counter

**Status:** Draft for review
**Companion to:** PRD_v2.md, Implementation_Plan_v2.md
**Date:** 2026-05-13

This document describes how Intersection Counter v2 is built. The *what* and *why* live in `PRD_v2.md`; the *step-by-step build order* lives in `Implementation_Plan_v2.md`. This document covers *how the parts fit together*.

---

## 1. Architecture overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                       USER'S BROWSER (Chrome/Firefox)                │
│                                                                      │
│   index.html  ─────────────────────────────────────────────┐         │
│   <script> projects.js, setup.js, calibration.js,          │         │
│            processing.js, dashboard.js, review.js,         │         │
│            export.js, api.js, app.js                       │         │
│                            │ fetch() over HTTP/JSON         │        │
└────────────────────────────┼─────────────────────────────────────────┘
                             │
                  http://127.0.0.1:5000
                             │
┌────────────────────────────┼─────────────────────────────────────────┐
│                            ▼                                         │
│   FastAPI app (uvicorn, single worker, single process)               │
│   ┌──────────┬──────────┬──────────┬──────────┬──────────┬────────┐  │
│   │projects  │videos    │calibration│processing│dashboard │review  │  │
│   │router    │router    │router    │router    │router    │router  │  │
│   └──────────┴──────────┴──────────┴──────────┴──────────┴────────┘  │
│            │                                                         │
│            │    ┌────────────────────────────────────────┐           │
│            └───▶│ services/                              │           │
│                 │  detector.py        (YOLO)             │           │
│                 │  tracker.py         (ByteTrack)        │           │
│                 │  preprocessor.py    (adaptive CLAHE)   │           │
│                 │  trajectory_classifier.py              │           │
│                 │  classifier.py      (vehicle class)    │           │
│                 │  origin_detector.py (line geometry)    │           │
│                 │  auto_calibrator.py (NEW v2)           │           │
│                 │  pipeline.py        (orchestrator)     │           │
│                 │  checkpoint.py                         │           │
│                 │  video_service.py   (metadata, frames) │           │
│                 │  aggregator.py      (NEW v2: TMC pivot)│           │
│                 │  excel_export.py    (NEW v2: XLSX)     │           │
│                 │  device.py          (NEW v2: GPU/CPU)  │           │
│                 └────────────────────────────────────────┘           │
│                                  │                                   │
│                                  ▼                                   │
│            ┌──────────────────────────────────────────┐              │
│            │  Per-project SQLite (WAL mode):          │              │
│            │  data/projects/<project_id>/project.db   │              │
│            │  + uploaded video files referenced by    │              │
│            │  absolute path (NOT copied into project) │              │
│            └──────────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────────────────┘
```

**Key invariants:**

1. **One process, one event loop.** No multi-process, no Celery, no Redis. Threading is used only for the CPU-bound pipeline so it doesn't block FastAPI's request handlers.
2. **Per-project state isolation.** Two projects share *no* in-memory state and *no* database tables. Each has its own SQLite file.
3. **Video files are referenced, not copied.** The DB stores absolute paths to the user's MP4/MOV files. Deleting a project leaves the video files alone.
4. **Stateless API requests.** Every request can identify its target project from the URL (`/api/projects/{project_id}/…`). No session cookies, no auth headers.
5. **Single-writer SQLite.** WAL mode lets the API read while the pipeline writes. Concurrent writes from two threads to the same DB are *not* expected (pipeline writes from one thread; API writes are user-driven and infrequent).

## 2. Folder layout

```
intersection-counter/
├── backend/
│   ├── __init__.py
│   ├── app.py                  # FastAPI app, router registration, static mount
│   ├── config.py               # Env-driven settings: HOST, PORT, DEVICE, MODEL, paths
│   ├── database.py             # Schema, get_connection, project_info helpers
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── projects.py
│   │   ├── videos.py           # (was video.py — handles multi-video CRUD)
│   │   ├── calibration.py      # (was a stub — full implementation)
│   │   ├── processing.py
│   │   ├── dashboard.py
│   │   ├── review.py
│   │   └── export.py           # (was a stub — Excel + JSON download)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── detector.py
│   │   ├── tracker.py
│   │   ├── preprocessor.py
│   │   ├── trajectory_classifier.py
│   │   ├── classifier.py
│   │   ├── origin_detector.py
│   │   ├── auto_calibrator.py  # NEW
│   │   ├── pipeline.py
│   │   ├── checkpoint.py
│   │   ├── video_service.py
│   │   ├── aggregator.py       # NEW (was a stub)
│   │   ├── excel_export.py     # NEW (was a stub)
│   │   └── device.py           # NEW
│   └── tests/
│       └── …
├── frontend/
│   ├── index.html
│   ├── css/
│   │   └── styles.css
│   └── js/
│       ├── api.js
│       ├── app.js
│       ├── projects.js
│       ├── setup.js
│       ├── videos.js           # NEW
│       ├── calibration.js      # FULL IMPL (was stub)
│       ├── processing.js
│       ├── dashboard.js
│       ├── review.js
│       └── export.js           # FULL IMPL (was stub)
├── data/
│   └── projects/
│       └── <project_id>/
│           └── project.db
├── models/
│   ├── .gitkeep
│   └── (yolov8n.pt / yolov8s.pt downloaded on first run)
├── docs/
│   ├── PRD_v2.md
│   ├── TDD.md
│   ├── Implementation_Plan_v2.md
│   └── research/
├── run.py                      # canonical launcher — prints URL, starts uvicorn
├── requirements.txt
├── CLAUDE.md
└── README.md
```

Deleted relative to v1:
- `start_server.py`, `serve.bat` (consolidated into `run.py`)
- `requirements - Copy.txt`, `.claude/settings.local - Copy*.json`

`run.py` no longer uses pywebview. It prints `Intersection Counter running at http://127.0.0.1:5000` and starts uvicorn.

## 3. Data flow

### 3.1 Video → events

```
┌────────────┐    ┌──────────────┐    ┌──────────┐    ┌─────────┐    ┌─────────────┐
│  cv2 reads │───▶│  Adaptive    │───▶│   YOLO   │───▶│ByteTrack│───▶│  Per-track  │
│  frame N   │    │  preprocess  │    │  detect  │    │  update │    │  trajectory │
└────────────┘    └──────────────┘    └──────────┘    └─────────┘    └─────────────┘
                                                                            │
                  ┌────────────────────────────────────────────────────────┘
                  │
                  ▼
         ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
         │  Did centroid    │───▶│  Once origin     │───▶│  On track lost:  │
         │  cross any leg's │YES │  crossed, append │    │  classify        │
         │  origin line?    │    │  to trajectory   │    │  trajectory      │
         └──────────────────┘    └──────────────────┘    └──────────────────┘
                                                                  │
                                                                  ▼
                                                       ┌────────────────────┐
                                                       │ INSERT INTO        │
                                                       │ vehicle_events     │
                                                       │ (one row per       │
                                                       │  classified track) │
                                                       └────────────────────┘
```

Per-frame steps (≤3 fps on CPU, ≤100 fps on GPU, frame-skip 3):

1. **Read.** `cap.read()` — opencv decodes one frame.
2. **Preprocess.** `AdaptivePreprocessor.preprocess(frame)` returns either the same frame or an enhanced version, based on a brightness/contrast assessment. Day frames pass through unchanged.
3. **Detect.** `VehicleDetector.detect(frame)` returns a list of dicts (bbox, center, class_id, confidence, area).
4. **Track.** `VehicleTracker.update(detections, frame_number)` returns the same detections with a persistent `track_id`.
5. **Origin check.** For each tracked vehicle without an `origin_leg_id` yet: did its centroid cross any leg's origin line between the previous and current frame? If yes, assign that leg.
6. **Accumulate.** For each tracked vehicle with an `origin_leg_id`: append the centroid to its trajectory list.
7. **Finalize.** For each `active_vehicles` track that disappeared this frame: classify its trajectory, build a `vehicle_event`, INSERT it.

### 3.2 Events → TMC report

```
vehicle_events (N rows per video × M videos)
        │
        │ aggregator.compute_tmc_matrix(project_id, interval_minutes)
        ▼
┌─────────────────────────────────────────────────────────────┐
│  Pivot table:                                               │
│    rows    = legs (by sort_order)                           │
│    columns = movements (through/left/right/u_turn)          │
│    cells   = COUNT(*) where rejected=0 AND movement valid   │
│                                                             │
│  Time series:                                               │
│    bucket  = floor(timestamp_video / (interval_min * 60))   │
│    cell    = COUNT(*) per bucket per leg per movement       │
└─────────────────────────────────────────────────────────────┘
        │
        │ excel_export.build_workbook(matrix, time_series, project_meta)
        ▼
┌─────────────────────────────────────────────────────────────┐
│  openpyxl Workbook:                                         │
│    Summary sheet                                            │
│    Per-leg sheets (rows=intervals, cols=movements×classes)  │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
   .xlsx bytes streamed to the browser as a download
```

## 4. Concurrency

### 4.1 Threading model

- **FastAPI request handlers run on the asyncio event loop.** They never do heavy CPU work directly.
- **The processing pipeline runs in a dedicated `threading.Thread`**, one per active project. Started by `POST /api/projects/{id}/processing/start`.
- **`tkinter.filedialog` is the only blocking call from a request handler**, and it's wrapped in `asyncio.to_thread()`.

### 4.2 Shared state

Module-level dicts in `backend/routers/processing.py`:

```python
_pipelines: dict[str, ProcessingPipeline]   # active pipelines by project_id
_progress:  dict[str, dict]                  # latest progress payload per project
_threads:   dict[str, threading.Thread]      # worker threads per project
_state_lock: threading.Lock                  # guards all three dicts
```

**Invariant:** `_pipelines[pid]` exists ⇔ `_threads[pid]` exists ⇔ project `pid` is processing or paused mid-run.

**Concurrent project limit.** Per PRD §6.4 [ASSUMPTION], only one project may process at a time. The `start` endpoint returns `409 Conflict` if any other pipeline is active. Future enhancement: a queue. Not in v2.

### 4.3 SQLite concurrency

Every project's database is opened in **WAL mode** with `PRAGMA foreign_keys=ON`. The pipeline thread writes events; API request handlers read for dashboard/review. WAL allows concurrent reads with the single writer.

**No connection pooling.** Each function opens its own connection and closes it. SQLite connections are not safe to share across threads.

### 4.4 Cancellation

`pipeline.pause_requested: threading.Event`. The pipeline loop checks it at the top of every frame iteration. On set:
1. `_save_checkpoint()` is called.
2. `is_running = False`.
3. Loop breaks. The thread exits its `try/finally`.

The HTTP `pause` endpoint sets the event and returns immediately. The thread is *not* joined synchronously — the client polls `/processing/status` for confirmation.

Cancel additionally joins with a 5-second timeout, clears the checkpoint, and resets project status to `idle`.

## 5. Database schema

One SQLite file per project at `data/projects/<project_id>/project.db`. All tables created from a single `CREATE TABLE IF NOT EXISTS` schema in `backend/database.py`. **No migration framework.** Schema changes between v1 and v2 are handled by deleting and re-creating tables in projects that have not been processed yet; processed v1 projects are not auto-migrated. See `Implementation_Plan_v2.md` for the migration step.

```sql
-- Key-value bag for project-level settings and status
CREATE TABLE IF NOT EXISTS project_info (
    key   TEXT PRIMARY KEY,
    value TEXT
);
-- Common keys:
--   project_name, status, created_at, interval_minutes,
--   frame_skip, prescan_seconds, screen_north_direction,
--   calibration_completed_at, calibration_frame_url

-- One row per source video in this project (NEW in v2)
CREATE TABLE IF NOT EXISTS videos (
    video_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sort_order          INTEGER NOT NULL,
    path                TEXT NOT NULL,
    filename            TEXT NOT NULL,
    fps                 REAL NOT NULL,
    width               INTEGER NOT NULL,
    height              INTEGER NOT NULL,
    total_frames        INTEGER NOT NULL,
    duration_seconds    REAL NOT NULL,
    file_size_bytes     INTEGER NOT NULL,
    codec               TEXT,
    creation_time       TEXT,            -- ISO, from ffprobe if available
    recording_start_time TEXT,           -- ISO, user-entered, optional
    added_at            TEXT NOT NULL
);

-- One row per intersection approach (4 typical, 2-4 allowed)
CREATE TABLE IF NOT EXISTS legs (
    leg_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    label               TEXT NOT NULL,
    cardinal_direction  TEXT NOT NULL,     -- N | S | E | W | NE | NW | SE | SW
    sort_order          INTEGER NOT NULL,
    origin_zone         TEXT NOT NULL,     -- JSON: [[x1,y1],[x2,y2]] in calibration frame px
    reference_heading   REAL NOT NULL      -- degrees, 0=up, 90=right
);

-- One row per classified vehicle trajectory (UPDATED in v2)
CREATE TABLE IF NOT EXISTS vehicle_events (
    event_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id                INTEGER NOT NULL,                   -- NEW in v2
    vehicle_track_id        INTEGER NOT NULL,
    origin_leg_id           INTEGER NOT NULL,
    movement                TEXT NOT NULL,                      -- through|left|right|u_turn
    trajectory_data         TEXT NOT NULL,                      -- JSON array of [x,y]
    trajectory_confidence   REAL NOT NULL,
    vehicle_class           TEXT NOT NULL,                      -- simplified class
    fhwa_class              INTEGER,
    detection_confidence    REAL NOT NULL,
    timestamp_video         REAL NOT NULL,                      -- seconds from video start
    timestamp_real          TEXT,                               -- ISO wall clock if known
    frame_number            INTEGER NOT NULL,
    manually_edited         INTEGER NOT NULL DEFAULT 0,         -- 0|1
    rejected                INTEGER NOT NULL DEFAULT 0,         -- NEW in v2: 0|1 soft delete
    FOREIGN KEY (video_id) REFERENCES videos(video_id),
    FOREIGN KEY (origin_leg_id) REFERENCES legs(leg_id)
);

CREATE INDEX IF NOT EXISTS idx_events_video      ON vehicle_events(video_id);
CREATE INDEX IF NOT EXISTS idx_events_leg        ON vehicle_events(origin_leg_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp  ON vehicle_events(timestamp_video);

-- Single-row table tracking processing position for pause/resume
CREATE TABLE IF NOT EXISTS checkpoint (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    current_video_id        INTEGER NOT NULL,                   -- NEW in v2
    frame_number            INTEGER NOT NULL,
    timestamp_video         REAL NOT NULL,
    tracker_state           BLOB,                               -- pickled ByteTrack
    active_trajectories     BLOB,                               -- pickled active_vehicles
    vehicle_count           INTEGER NOT NULL DEFAULT 0,
    error_count             INTEGER NOT NULL DEFAULT 0,
    updated_at              TEXT NOT NULL
);

-- Caches the calibration frame the user confirmed against (for review thumbnails)
CREATE TABLE IF NOT EXISTS calibration_frame (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    video_id        INTEGER NOT NULL,
    frame_number    INTEGER NOT NULL,
    image_jpeg      BLOB NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);
```

**Dropped from v1:**
- `pedestrian_events` — no pedestrians in v2.
- `low_confidence_segments` — never used in v1, and the dashboard surfaces low confidence at the per-event level via `trajectory_confidence < 0.5`.

## 6. API surface

All endpoints under `/api/`. JSON request/response unless noted. All errors return JSON `{"detail": "…"}` with appropriate HTTP status.

### 6.1 Projects

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/projects` | List all projects |
| POST | `/api/projects` | Create. Body: `{name: str}` |
| GET | `/api/projects/{pid}` | Read project_info bag |
| PUT | `/api/projects/{pid}/name` | Rename. Body: `{name: str}` |
| PUT | `/api/projects/{pid}/settings` | Update settings. Body: `{interval_minutes?, frame_skip?, prescan_seconds?, screen_north_direction?, num_legs_hint?}` |
| DELETE | `/api/projects/{pid}` | Delete project directory |

### 6.2 Videos (multi-video, NEW in v2)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/projects/{pid}/videos` | List videos in project |
| POST | `/api/projects/{pid}/videos/browse` | Open native file picker. Returns `{path: str \| null}` |
| POST | `/api/projects/{pid}/videos` | Add. Body: `{path: str}`. Returns metadata + video_id |
| DELETE | `/api/projects/{pid}/videos/{vid}` | Remove. Deletes its events. Confirm via `?confirm=true` |
| PUT | `/api/projects/{pid}/videos/{vid}/start_time` | Body: `{recording_start_time: ISO datetime}` |
| GET | `/api/projects/{pid}/videos/{vid}/frame` | Returns JPEG of frame at `?seconds=N` |
| PUT | `/api/projects/{pid}/videos/{vid}/order` | Body: `{sort_order: int}`. Reorder videos |

### 6.3 Calibration (NEW in v2 — was a stub)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/projects/{pid}/calibration/auto` | Run auto-calibration. Body: `{video_id, prescan_seconds, screen_north_direction, num_legs_hint?}`. Returns `{job_id}`. Long-running — runs in a thread. |
| GET | `/api/projects/{pid}/calibration/auto/status` | Poll job status. Returns `{status: running|completed|failed, progress_pct, result?, error?}` |
| GET | `/api/projects/{pid}/calibration` | Read current calibration: legs[], calibration_frame_url |
| PUT | `/api/projects/{pid}/calibration` | Save calibration. Body: `{legs: [{label, cardinal_direction, sort_order, origin_zone, reference_heading}, …], frame_video_id, frame_number}` |
| POST | `/api/projects/{pid}/calibration/manual` | Initialize empty calibration for manual mode |
| DELETE | `/api/projects/{pid}/calibration` | Clear calibration |

### 6.4 Processing

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/projects/{pid}/processing/start` | Start. 409 if another project is processing. |
| POST | `/api/projects/{pid}/processing/pause` | Pause. |
| POST | `/api/projects/{pid}/processing/resume` | Resume from checkpoint. |
| POST | `/api/projects/{pid}/processing/cancel` | Cancel + clear checkpoint. |
| POST | `/api/projects/{pid}/processing/reset_events` | Clear all vehicle_events but keep calibration. |
| GET | `/api/projects/{pid}/processing/status` | `{status, is_running, has_checkpoint, progress: {current_video_id, frame, total_frames_all_videos, pct, vehicle_count, fps_processing, error_count, eta_seconds}}` |

### 6.5 Dashboard

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/projects/{pid}/dashboard` | `{tmc_matrix, time_series, class_breakdown, totals, interval_minutes}` |

### 6.6 Review

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/projects/{pid}/review` | Paginated events. Query: `page, page_size, leg_id, movement, vehicle_class, low_confidence, manually_edited, rejected` |
| PATCH | `/api/projects/{pid}/review/{event_id}` | Update fields. Body: `{movement?, vehicle_class?, rejected?}`. Sets `manually_edited = 1`. |
| GET | `/api/projects/{pid}/review/{event_id}/preview` | JPEG of the event's frame with trajectory polyline drawn. Query: `?width=N` for thumbnail size. |

### 6.7 Export

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/projects/{pid}/export/xlsx` | Returns the FHWA TMC `.xlsx` as application/vnd.openxmlformats-officedocument.spreadsheetml.sheet |
| GET | `/api/projects/{pid}/export/csv` | (Stretch) CSV of raw events |

### 6.8 Health / meta

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | `{status: "ok", device: "cuda"\|"cpu", model: "yolov8s.pt"}` |

## 7. Auto-calibration algorithm

Implemented in `backend/services/auto_calibrator.py`. Runs in its own thread (long-running, can take 10–60 s).

### 7.1 Inputs

- Project ID, target video ID, prescan seconds (default 300).
- `num_legs_hint`: `"auto" | 2 | 3 | 4`.
- `screen_north_direction`: `"up" | "down" | "left" | "right"`.

### 7.2 Steps

1. **Prescan.** Run the existing pipeline (preprocess → detect → track) on the first `prescan_seconds` of the target video, with frame_skip 3. Use the existing `VehicleDetector` and `VehicleTracker`. **Do not** assign origin legs (no calibration yet). Record raw per-track trajectories: `{track_id: [(x, y, frame_number), …]}`.

2. **Filter trajectories.** Drop tracks with:
   - Fewer than `TRAJECTORY_MIN_POINTS` (10).
   - Total path distance less than `TRAJECTORY_MIN_DISTANCE_PX` (50).
   - Straight-line distance from start to end less than 100 px (drops parked vehicles, jitter).

3. **Find entry/exit clusters.** Take the first and last point of every surviving trajectory. Build a 2D point set of all entries and all exits combined. Run **K-Means** or **DBSCAN** to cluster these points near the frame edges. (Scikit-learn is already in requirements.)

4. **Infer leg count.** If `num_legs_hint` is set, use it. Otherwise, accept clusters where the number of points is at least `0.05 × total_trajectory_count`. Typical intersections will produce 4 dominant clusters.

5. **Place origin lines.** For each leg-cluster, compute:
   - **Cluster centroid** in pixel space.
   - **Dominant flow direction** = mean unit vector from entries-into-cluster to entries-out-of-cluster (i.e., the average heading of trajectories passing through that cluster's region).
   - **Origin line** = perpendicular to flow direction, length = 0.6 × the cluster's bounding box dimension along the perpendicular axis, centered on the centroid.

6. **Compute intersection center.** Mean of all leg-cluster centroids, weighted by trajectory count. Often the geometric center of the frame, but not always.

7. **Compute reference headings.** For each leg, `reference_heading = compute_reference_heading(line_start, line_end, intersection_center)` from the existing `origin_detector` module.

8. **Assign cardinal labels.** For each leg:
   - Compute the screen-space bearing from intersection center to leg centroid.
   - Rotate that bearing by the user-supplied `screen_north_direction` to convert it into a real-world bearing.
   - Snap to the nearest of `{N, NE, E, SE, S, SW, W, NW}`.
   - Label = `"{Cardinal} Approach"`.

9. **Sort.** `sort_order` = clockwise starting from north (N=0, NE=1, E=2, ...).

10. **Confidence check.** Reject if:
    - fewer than 2 legs were inferred (intersection probably looks weird, or prescan too short).
    - any leg has fewer than 30 trajectories supporting it (per PRD §6.3).
    Return `{success: false, reason: "..."}` and let the user re-run with a longer prescan or fall back to manual.

11. **Output.** Return proposed legs and the JPEG of a representative frame (the first frame after preprocessing) for the user to confirm against. The user adjusts/confirms via `PUT /api/projects/{pid}/calibration`.

### 7.3 Why this works for typical traffic videos

Vehicles enter and exit through narrow regions at the frame edges (approach lanes). Their trajectories naturally form 4 clusters of entries and 4 clusters of exits at a normal 4-way intersection. K-Means or DBSCAN on the combined point cloud separates these cleanly. The dominant flow direction tells us where to draw the origin line (perpendicular to the lane direction).

### 7.4 Failure modes and fallbacks

| Failure | Cause | Fallback |
|---|---|---|
| Too few trajectories | Prescan too short, or low-traffic intersection | Longer prescan (up to `MAX_PRESCAN_SECONDS = 600`). Or manual mode. |
| Wrong number of legs | Asymmetric intersection (Y-shape, T) | Set `num_legs_hint` to 3 or 2 explicitly. |
| Garbage origin lines | Unusual camera angle, vehicles do not enter through frame edges (e.g., camera over the center) | Manual mode. Auto-calibration is **not** guaranteed; PRD §6.3 calls this out. |
| Mixed-direction lanes | Both directions of a leg share the same screen region | Origin line bisects them — vehicle origin assignment still works because we cross-detect direction. Net cardinal label may be ambiguous (e.g., a leg is both "northbound" and "southbound"). The user can edit. |

## 8. Multi-video pipeline orchestration

### 8.1 Sequential video processing

When `start` is called:

1. Load all `videos` rows for the project, sorted by `sort_order`.
2. For each video in order:
   1. Reset the tracker (fresh `ByteTrack` instance).
   2. Reset `active_vehicles`.
   3. Run the per-video pipeline (as in v1's `process_video`), passing the current `video_id` so events carry it.
   4. On completion: persist a "video done" marker in `project_info` (`last_completed_video_id`).
   5. Save a checkpoint with `current_video_id` set.

If the pipeline is paused mid-video, the checkpoint stores `current_video_id` and `frame_number`. Resume restarts that video from `frame_number - overlap_frames`.

### 8.2 Why reset the tracker between videos

ByteTrack track IDs are arbitrary and ephemeral. Across two separate recordings, the same physical vehicle would have unrelated track IDs anyway. Resetting prevents stale lost-tracks from being matched to fresh new vehicles.

### 8.3 Aggregation

`aggregator.compute_tmc_matrix(project_id, interval_minutes)`:

```python
def compute_tmc_matrix(project_id: str, interval_minutes: int) -> dict:
    """Return TMC pivot and time series across ALL videos in a project.

    Excludes rejected events. Counts only valid movements.
    Time series bucketing is based on `timestamp_video` per-video — the
    UI shows wall-clock time when recording_start_time is present.
    """
```

Buckets across videos are *not* fused into a single timeline unless the user has set `recording_start_time` for every video. If any video lacks a start time, the time series shows per-video buckets labeled with video filename.

## 9. Device selection (GPU/CPU)

`backend/services/device.py`:

```python
def detect_device(override: str | None = None) -> str:
    """Return 'cuda' if available and override allows, else 'cpu'."""

def default_model_path(device: str) -> str:
    """yolov8s.pt on GPU, yolov8n.pt on CPU."""
```

- `DEVICE` env var: `auto` | `cuda` | `cpu`. Default `auto`.
- `YOLO_MODEL` env var: full path or filename. Overrides `default_model_path()`.
- On startup, the FastAPI app calls `detect_device()` once and stores the result in `app.state.device`. The `/api/health` endpoint surfaces it.
- `VehicleDetector.__init__` accepts a `device` parameter and passes it to YOLO's inference call. v1 hard-coded `device="cpu"` — v2 reads it from config.

PyTorch CUDA wheels are not bundled. The README documents:
```
# For GPU (NVIDIA only):
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

## 10. Checkpoint design

### 10.1 What's saved

| Field | Why |
|---|---|
| `current_video_id` | Which video we were processing |
| `frame_number` | Where we were in that video |
| `timestamp_video` | Redundant with frame_number / fps, but cheap |
| `tracker_state` | Pickled `sv.ByteTrack` instance — lets us resume mid-track without reinitializing |
| `active_trajectories` | Pickled `active_vehicles` dict — partial trajectories not yet finalized |
| `vehicle_count`, `error_count` | Live counters |
| `updated_at` | For debugging |

### 10.2 When it's saved

- Every **120 seconds of video time** (`CHECKPOINT_INTERVAL_SECONDS`) during processing.
- Immediately when `pause()` is signaled.
- Immediately when a video completes (so a crash during the gap before the next video has a clear resume point).

### 10.3 Resume semantics

`pipeline.resume_from_checkpoint()`:

1. Load the checkpoint row.
2. Restore `vehicle_count` and `error_count`.
3. Try to `pickle.loads(tracker_state)` into the tracker. On failure, log a warning and continue with a fresh tracker (a re-warmup will lose 1–2 seconds of tracking but is correct).
4. Try to `pickle.loads(active_trajectories)` into `active_vehicles`. On failure, log and continue with an empty dict (the affected partial trajectories are lost — acceptable, very rare).
5. Set `current_video_id` and `start_frame = max(0, checkpoint.frame_number - 60 * fps)` so we re-warm the tracker over the overlap window.
6. Skip any earlier videos (we don't reprocess them).

### 10.4 Pickling safety

Pickling `sv.ByteTrack` works across the same supervision version. If the user upgrades supervision between processing sessions, resume may fail. We catch the exception and fall back to a fresh tracker; the only cost is a 60-second re-warmup, which the overlap window already covers.

`pickle.loads` on stored data is annotated with `# noqa: S301` — we control the input (it's our own pickle, in our own DB).

## 11. Error handling philosophy

### 11.1 Three categories

1. **Per-frame errors** (frame decode failure, YOLO failure, tracker assertion). Logged, `error_count` incremented, pipeline continues. **The processing pipeline NEVER halts on a single-frame error.** (Hard constraint from CLAUDE.md.)

2. **Resource errors** (video file missing, DB locked, out of disk). Pipeline halts, project status set to `error`, error message persisted in `project_info["last_error"]`. User sees this in the UI on next status poll.

3. **User errors** (no video set, no calibration, invalid movement value). HTTP 400 with a descriptive `detail` field. No traceback to the client.

### 11.2 Logging

`logging` module at INFO level by default. Per-frame errors at ERROR with frame number. Pipeline lifecycle (start, checkpoint, pause, complete) at INFO. Tracker/detector internals at DEBUG (silent by default).

Logs go to stdout. Future enhancement: rotating file logs. Not in v2.

### 11.3 What the user sees on failure

- **Per-frame error_count > 0:** displayed in the progress stats, no other notification.
- **Pipeline halts:** project status badge turns red; an error banner above the processing controls shows `last_error`.
- **Validation error:** in-page alert with the message from the API.

## 12. Frontend conventions

- One `.js` per page, plus `api.js` (fetch wrappers) and `app.js` (page routing).
- Pages live in `<section id="page-{name}" class="page">` inside `index.html`. `app.js` shows/hides via `.active` class.
- `AppState` is a single global object: `{ currentProject: string | null, currentPage: string }`.
- DOM is rebuilt from scratch when a page is shown (no virtual DOM, no diffing). Each page module exports a `loadXxxPage()` function.
- Long-running operations poll. **No websockets, no SSE** — keeps the stack simple. Polling interval: 1 second for processing status, 500 ms for auto-calibration job status.
- All form values are saved to the backend on blur or change, not on submit. There is no "save" button on Setup.
- HTML escaping is local to each module (`escapeHtml`, `escapeAttr`). Trust no DB value.

## 13. Testing

### 13.1 Backend

- `pytest`. Tests live in `backend/tests/`.
- One test file per service / router.
- DB tests use a temp directory and a fresh project_id.
- Pipeline tests use a small synthetic video (10–30 s) at `backend/tests/fixtures/sample.mp4` — or a mock detector.
- **Don't load YOLO weights in tests.** All pipeline tests use a `MockDetector` that returns scripted detections.

### 13.2 Frontend

- No automated frontend tests in v2. Manual smoke test: full happy-path workflow on a real video before merging anything UX-touching.

### 13.3 What gets tested

| Area | Approach |
|---|---|
| `origin_detector` geometry | Pure-function unit tests. Already done in v1. |
| `trajectory_classifier` | Pure-function unit tests with hand-crafted trajectories. Already done in v1. |
| `classifier` | Pure-function unit tests. Already done in v1. |
| `preprocessor` | Image-fixture tests (assert output shape, dtype, mean brightness change). Already done in v1. |
| `tracker` | Integration test with `MockDetector`. Already done in v1. |
| `checkpoint` | Save → load → verify round-trip. Already done in v1. |
| `pipeline` | Integration test with `MockDetector` over a fixture video. v2 must add multi-video coverage. |
| `auto_calibrator` | Synthetic point-cloud tests (provide hand-crafted trajectories, assert legs cluster correctly). NEW. |
| `aggregator` | Pivot-table tests with seeded events. NEW. |
| `excel_export` | Open generated `.xlsx` with openpyxl, assert cell values. NEW. |
| Routers | `httpx.AsyncClient` integration tests, one per endpoint. Already partial in v1. |

### 13.4 Coverage target

Service-layer modules: ≥80% line coverage. Routers: every endpoint has at least one happy-path and one error-path test.

## 14. Open technical decisions

The following I'm choosing as defaults — flag any that should change before the Implementation Plan locks them in:

| # | Topic | Choice |
|---|---|---|
| 1 | Clustering algorithm for auto-calibration | DBSCAN (handles variable cluster shapes, no need to specify K) |
| 2 | Manual-fallback storage | Same `legs` rows, no flag indicating "auto" vs "manual" — once saved, they're indistinguishable |
| 3 | Cross-video timeline fusion | Only when all videos have `recording_start_time` set. Otherwise, per-video buckets. |
| 4 | Calibration frame storage | BLOB in DB (`calibration_frame` table), not a file. Keeps the project portable as a single DB file. |
| 5 | One model per session | Load YOLO once at first detection request, reuse for the life of the process. Restart server to switch models. |
| 6 | Concurrent project limit | Hard limit of 1 active pipeline. 409 on second `start`. |
| 7 | Pickle safety for tracker | Best-effort. Fall back to fresh tracker on unpickle failure. |
| 8 | Frame skip configurable per project | Yes, via `project_info["frame_skip"]`. Default 3. |
| 9 | Storing trajectories | JSON-encoded in `vehicle_events.trajectory_data`. Acceptable up to ~500 points. |
| 10 | Soft delete vs hard delete | Soft (`rejected = 1`). PRD §6.6. |
