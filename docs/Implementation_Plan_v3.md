# Implementation Plan v3 — Multi-Intersection Project Workflow

## Why v3

v2 (current main) supports `project → flat list of videos` with calibration scoped to the project. This is fine for a single-intersection one-camera study but breaks down for the real DeShazo workflow, which routinely involves:

- **Multiple intersections** per project (a study often covers a corridor or a cluster).
- **Multiple cameras** per intersection (parallel coverage for accuracy, OR gap coverage to span an outage).
- **Multiple clips** per camera (typically time-segmented sequential files from a continuous recording).
- **Multiple recording days** per project (weekday/weekend studies).
- **Multiple processing windows** per intersection-day (peak-only counting: 07:00–09:00 AM peak + 16:00–18:00 PM peak, skip everything in between).

v3 introduces the proper hierarchy, the bulk-upload-then-label flow, multi-trim wall-clock processing, cross-camera deduplication, and an inline-correction playback view.

## Status entering v3

All v2 features are working on `claude/bootstrap-project-structure-TC2A0` at `58eb4b0`:
- Multi-video processing (flat list, single calibration)
- Auto-calibration service + endpoints
- Review screen with reject + per-event preview
- Pedestrian classes stripped per PRD
- Per-prompt admin task logging + `/weekly-report`
- YOLO v26 detector, trajectory classifier, background processing (from Step 15)
- ~300 unit tests passing; HTTP smoke verified

v3 builds on this foundation. Nothing v2 ships gets thrown away.

---

## Confirmed data model

```
Project
├── Video                        Raw bulk-uploaded files (labeled by user).
│                                Source of truth for clip files.
│
└── Intersection-Day             Auto-derived: groupby(intersection_name, date)
                                 across the project's videos. One card per group.
    ├── leg_count                Set in Intersection Settings sub-tab.
    │
    ├── Camera (1+)              Identified by camera_label parsed from filename
    │                            (user can rename in Cameras sub-tab).
    │   │
    │   ├── Legs (leg_count)     Per-camera calibration data. Each leg has:
    │   │                        - label (e.g., "North")
    │   │                        - cardinal_direction
    │   │                        - sort_order
    │   │                        - origin_zone (polygon in this camera's frame)
    │   │                        - reference_heading (degrees)
    │   │
    │   └── Video (1+)           Sequential clips from this camera at this
    │                            intersection-day.
    │
    └── Trim (1+)                Wall-clock processing windows. Each:
                                 - start_wallclock (HH:MM:SS)
                                 - end_wallclock   (HH:MM:SS)
                                 - sort_order
                                 Defaults to one trim covering full coverage.
```

### Key relationships and invariants

- **Intersection-Day is the unit of organization.** Same physical intersection filmed on Tue and Wed = two intersection-day cards. Intersection name + date is the primary key (per project).
- **Camera identity** persists across all the clips from one camera at one intersection-day. The system groups videos with the same parsed `camera_label` into one Camera entity per intersection-day.
- **Legs are per-camera.** Each camera independently calibrates the legs it sees (label, cardinal direction, origin zone, reference heading). Two cameras at the same intersection-day might both have a "North" leg, but their origin zones and reference headings differ because they see the intersection from different angles. The system does not enforce label consistency across cameras; cross-camera reconciliation uses label match as a soft signal during dedup.
- **leg_count** is set at the intersection-day level. All cameras at that intersection-day are expected to have the same number of legs (configured slots). A camera with a blocked view still gets the same N leg slots, even if some are sparsely calibrated.
- **Trims are intersection-day-scoped.** A trim ("07:00–09:00") applies across all cameras at that intersection-day. The orchestrator translates wall-clock to per-video offsets at runtime.

### Coverage classification (derived, not stored)

For a given (intersection_name, date), the system can compute at any time:
- **Parallel coverage** between two cameras: their video time windows overlap.
- **Gap coverage** between two cameras: their video time windows are non-overlapping but together span more time than either alone.
- **Coverage gaps**: wall-clock intervals during the day where no camera has video.

These are not stored in the schema. They're computed on demand from video metadata (start_datetime + duration) when needed for trim validation or aggregation.

---

## Schema changes

### New tables (in each project's `project.db`)

```sql
CREATE TABLE intersections (
    intersection_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    date              TEXT NOT NULL,           -- YYYY-MM-DD
    sort_order        INTEGER NOT NULL,
    leg_count         INTEGER NOT NULL DEFAULT 4,
    created_at        TEXT NOT NULL,
    UNIQUE(name, date)
);

CREATE TABLE cameras (
    camera_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    intersection_id   INTEGER NOT NULL,
    label             TEXT NOT NULL,           -- "Camera 1", from filename
    sort_order        INTEGER NOT NULL,
    created_at        TEXT NOT NULL,
    FOREIGN KEY (intersection_id) REFERENCES intersections(intersection_id),
    UNIQUE(intersection_id, label)
);

CREATE TABLE trims (
    trim_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    intersection_id   INTEGER NOT NULL,
    start_wallclock   TEXT NOT NULL,           -- HH:MM:SS
    end_wallclock     TEXT NOT NULL,           -- HH:MM:SS
    sort_order        INTEGER NOT NULL,
    FOREIGN KEY (intersection_id) REFERENCES intersections(intersection_id)
);
```

### Modified tables

```sql
-- videos: previously had only camera-blind metadata. Add:
ALTER TABLE videos ADD COLUMN camera_id INTEGER REFERENCES cameras(camera_id);
ALTER TABLE videos ADD COLUMN camera_label_parsed TEXT;
ALTER TABLE videos ADD COLUMN intersection_name_label TEXT;   -- user-set
ALTER TABLE videos ADD COLUMN recording_start_datetime TEXT;  -- ISO

-- legs: was per-project; make per-camera.
ALTER TABLE legs ADD COLUMN camera_id INTEGER REFERENCES cameras(camera_id);

-- vehicle_events: already has video_id (joins up to camera). Add trim_id
-- so post-processing can group counts by trim if needed (we'll merge in
-- the final Excel, but the data preserves the breakdown).
ALTER TABLE vehicle_events ADD COLUMN trim_id INTEGER REFERENCES trims(trim_id);
ALTER TABLE vehicle_events ADD COLUMN camera_id INTEGER REFERENCES cameras(camera_id);  -- denormalized for query speed

-- checkpoint: track which camera + trim we're currently processing.
ALTER TABLE checkpoint ADD COLUMN current_camera_id INTEGER;
ALTER TABLE checkpoint ADD COLUMN current_trim_id INTEGER;
```

### Migration plan for existing projects

On first `get_connection()` call after the v3 schema lands, the runtime migration:

1. Creates the new tables if they don't exist.
2. Adds the new columns to existing tables.
3. **If the project has videos with no `camera_id`** (existing v2 data):
   - Auto-creates one `intersections` row: `name="Main intersection"`, `date=<derived from first video's start_datetime or file mtime>`, `leg_count=<count of existing legs rows>`.
   - Auto-creates one `cameras` row: `label="Camera 1"`, `intersection_id=<that intersection>`.
   - Backfills `videos.camera_id` and `vehicle_events.camera_id` to point at Camera 1.
   - Backfills `legs.camera_id` to Camera 1.
   - Auto-creates one `trims` row spanning the full video coverage so existing processing semantics are preserved (no time window filtering by default).
4. **If the project is empty** (no videos): no migration action; the user will populate from scratch via the new bulk-upload flow.

This is non-destructive. Old data continues to work.

---

## UX flow (12 steps, per user's spec)

1. **Project page → "Create Project"** — user names it.
2. **Project page (top-level)** — three primary tabs: **Videos** (raw uploads), **Intersections** (organized cards), and (later) processing status.
3. **Videos tab → "Upload Videos"** — user drag-drops a batch of clips. Files copy to the project's data dir.
4. **Videos tab → label** — for each row, filename parsing auto-fills `camera_label`, `date`, `recording_start_time`. The user fills in `intersection_name`. Editable.
5. **Videos tab → "Save"** — system derives intersection-day cards: `groupby(intersection_name, date)`. Auto-creates `intersections` rows, `cameras` rows (grouped by `camera_label` within each intersection-day), and links videos to their camera. Intersections tab populates.
6. **Intersections tab → click a card** — opens the card's sub-tabs.
7. **Sub-tab "Intersection Settings"** — leg count input (default 4, editable).
8. **Sub-tab "Cameras"** — list of cameras at this intersection-day. For each, "Calibrate" button opens the per-camera calibration screen (reuses the existing calibration UI, scoped to this camera). Manual and auto-calibration both available.
9. **Sub-tab "Clip Trim"** — list of trim windows. "Add Trim" → wall-clock start/end inputs. Default: one trim covering the union of all video coverage at this intersection-day. Save validates against coverage: any second of a trim without video → error with exact gap times.
10. **Intersection card → "Confirm" button** — opens a popup summarizing leg count, per-camera calibration status, trims. "Process" starts the run, closes the popup, returns to project page.
11. **Project page (intersections tab) → processing chip per card** — shows progress, ETA, "view live" link. User can configure another intersection while one is processing (concurrent up to `MAX_CONCURRENT_PIPELINES`).
12. **When processing finishes** — the per-card "view live" becomes "view dashboard." Clicking it opens the video summary dashboard: playback with overlay; engineer clicks a detection box to reject, clicks an empty area to add a missed vehicle. Corrections write back to `vehicle_events`. Excel download button on the dashboard.

---

## Key algorithms

### Filename parser

Pattern (v2-friendly regex):

```python
FILENAME_RE = re.compile(
    r"^(?P<cam>[A-Za-z0-9]+)_(?P<seq>\d+)_"
    r"(?P<date>\d{8})_(?P<time>\d{6})"
    r"(?:\s+(?P<intersection>.+?))?"
    r"\.(?P<ext>\w+)$"
)
```

Extracts: `cam` (camera label), `seq` (sequence number on that camera), `date` (YYYYMMDD), `time` (HHMMSS), `intersection` (the free-form trailing name; advisory only).

Returns a `ParsedFilename` dataclass:
- `camera_label: str`
- `sequence: int`
- `recording_start_datetime: datetime`
- `intersection_hint: str | None` (NOT used as source of truth — user-set value wins)

Fallback when no match:
- `camera_label = "Unknown"`
- `recording_start_datetime = file_mtime − duration` (best guess)
- `intersection_hint = None`
- A `parse_confidence: float` field records how trustworthy the parse is, so the UI can highlight rows that need user attention.

Lives at `backend/services/filename_parser.py` with full unit tests against a fixture set of real-world filename variations.

### Trim coverage validator

Given a list of cameras at an intersection-day (each with its videos and their `start_datetime`/`duration_seconds`):

1. Build wall-clock coverage intervals per camera: `[(start, end), …]`.
2. Union all intervals → `covered_intervals: list[Interval]`.
3. For each proposed trim `(t_start, t_end)`:
   - Compute the trim's wall-clock interval on the recording date.
   - If `covered_intervals` fully contains the trim → OK. Return per-second breakdown of which camera covers each portion (single-camera vs parallel).
   - Otherwise → return error with the exact uncovered sub-intervals: `"No video covers 08:32:15–08:35:40 of trim 1."`

Lives at `backend/services/coverage.py`. Pure function over interval algebra, fully unit-testable.

### Cross-camera deduplication

For each trim, after per-camera processing produces independent `vehicle_events` lists:

1. Determine **parallel-overlap regions**: wall-clock sub-intervals within the trim covered by 2+ cameras.
2. Determine **single-coverage regions**: sub-intervals covered by exactly 1 camera.
3. For events in single-coverage regions: keep as-is.
4. For events in parallel-overlap regions:
   - Group by leg label + movement.
   - Within each group, attempt to match events across cameras using a time-bucket sliding window (default ±5s).
   - **Matched pair**: collapse into one event. Keep the higher-confidence detection's metadata; record `dedup_source: [camera_id_a, camera_id_b]` in a side table for audit.
   - **Unmatched** (a camera saw a vehicle that no other camera in the overlap saw): keep the event with `dedup_source: [camera_id]`. This is the gap-fill case the user explicitly called out — preserves the vehicle in the count even though one camera missed it.

Configurable parameters (in `config.py`):
- `DEDUP_TIME_WINDOW_SECONDS = 5`
- `DEDUP_USE_CARDINAL_MATCH = True`  (also require cardinal direction match, not just label)

Lives at `backend/services/dedup.py`. Pure function over event lists; testable with synthetic data.

### Wall-clock to video offset translation

Per camera, given its videos' `recording_start_datetime` and `duration_seconds`:

```python
def wallclock_to_offset(camera_videos, target_dt) -> tuple[video_id, offset_seconds] | None:
    """Returns the video and its offset (in seconds from video start) containing
    target_dt, or None if target_dt isn't covered by any of this camera's videos."""
```

The orchestrator uses this to translate a trim window into a list of `(video_id, start_offset, end_offset)` segments for that camera to process.

---

## Phase breakdown

Ten phases. Each delivers something deployable; each is one session.

### Phase 1 — Schema + filename parser + migration

**Backend only.**

Deliverables:
- New tables (`intersections`, `cameras`, `trims`).
- New columns on `videos`, `legs`, `vehicle_events`, `checkpoint`.
- Runtime migration that auto-creates a default intersection + camera + trim for v2 projects.
- `backend/services/filename_parser.py` with unit tests against ~20 realistic filename variants.
- `backend/services/coverage.py` with unit tests over interval algebra.

Acceptance: existing v2 tests still pass. New parser+coverage tests pass. Existing project data round-trips through the new schema with zero loss.

### Phase 2 — Backend: Videos tab API

Deliverables:
- `POST /api/projects/{pid}/videos/bulk` — accept multiple file uploads, parse filenames, store under project's data dir, return preview rows with auto-filled fields.
- `GET /api/projects/{pid}/videos` — already exists; extend the response to include parsed `camera_label`, `recording_start_datetime`, `intersection_name_label`, `parse_confidence`.
- `PATCH /api/projects/{pid}/videos/{vid}/labels` — user-edits to intersection_name, date, start_time.
- `POST /api/projects/{pid}/videos/save-labels` — derive intersections+cameras from current labels, idempotent; preserves prior calibration data when cameras are restructured.

Acceptance: bulk-upload 20 files, derive 3 intersection-day cards, all videos correctly linked. Tests with synthetic file uploads.

### Phase 3 — Backend: Intersection card API

Deliverables:
- CRUD on `intersections` (mostly auto-created; manual edits = rename, leg_count change, delete).
- CRUD on `cameras` (rename, reorder).
- CRUD on `trims` with validation against `coverage.py`.
- `GET /api/projects/{pid}/intersections/{iid}/coverage-report` — visualizes coverage, used by frontend trim editor.
- Per-camera calibration endpoints — refactor existing calibration to take `camera_id` instead of `project_id` directly.

Acceptance: full intersection-day CRUD via HTTP. Coverage validator rejects invalid trims with precise gap times.

### Phase 4 — Backend: Multi-camera orchestrator

Deliverables:
- `_run_pipeline` becomes intersection-day-aware: iterates trims → cameras → per-video offsets.
- Status surfaces per `(intersection_id)`: `_progress` keyed by intersection_id, not project_id.
- `MAX_CONCURRENT_PIPELINES` applies across intersection-days.
- Pause/resume tracks `current_camera_id` + `current_trim_id` in checkpoint.

Acceptance: end-to-end run on a fixture with 2 intersection-days × 2 cameras × 2 trims completes; events written with correct `camera_id` and `trim_id`.

### Phase 5 — Backend: Cross-camera dedup + aggregator + Excel

Deliverables:
- `backend/services/dedup.py` with unit tests.
- Aggregator groups events by `(intersection_id, leg_label, movement)` for the main TMC sheet; by `(intersection_id, camera_id, leg_label, movement)` for the per-camera breakdown sheet.
- Excel export: main TMC sheet (merged), per-camera breakdown sheet, per-trim audit sheet (optional, low priority).

Acceptance: synthetic test with two cameras seeing the same vehicle once each → dedup'd to one count. Test with one camera missing a vehicle the other caught → counted once (gap-fill).

### Phase 6 — Frontend: Videos tab

Deliverables:
- Project page redesigned with top-level tabs: Videos | Intersections | Processing.
- Videos tab: drag-and-drop upload zone, labeling table, "Save" button.
- Auto-fill from filename parse; rows with `parse_confidence < 0.5` highlighted.
- Inline editing per cell; sortable columns; bulk-edit "set intersection name on selected rows."

Acceptance: drag in a folder of clips, table populates, edit intersection names, save, navigate to Intersections tab and see the cards.

### Phase 7 — Frontend: Intersection card + sub-tabs

Deliverables:
- Intersections tab: card grid (one per intersection-day) with summary (camera count, video count, trim count, calibration status).
- Card open: tabbed view (Intersection Settings, Cameras, Clip Trim).
- Intersection Settings: leg count input.
- Cameras sub-tab: list of cameras, each with a "Calibrate" button. Calibration screen is the existing auto-cal/manual-cal UI, scoped to the selected camera.
- Clip Trim sub-tab: table of trims with wall-clock inputs, coverage visualizer (Gantt-chart-like view of which camera covers what wall-clock window, with trim overlays), validator surfaces errors inline.

Acceptance: configure leg count, calibrate 2 cameras, define 2 trims, no validation errors.

### Phase 8 — Frontend: Project-page processing status

Deliverables:
- Confirm popup on intersection card → process kicks off → return to project page.
- Per-intersection-day status chip with ETA.
- "View live processing" deep-links to the existing processing preview, scoped to the active camera at that intersection-day.
- Concurrent processing visualization (multiple chips active simultaneously).

Acceptance: configure two intersection-day cards, kick off both, see both running concurrently with independent ETAs.

### Phase 9 — Frontend: Playback verification view (inline correction)

Largest frontend phase.

Deliverables:
- "Open dashboard" on completed intersection-day → playback view.
- Video player (HTML5 video, scrubable, variable speed) for any camera at that intersection-day.
- Detection overlay: bounding boxes + trajectories drawn on each frame using the existing `frame_annotator` rendering.
- **Click on a box → reject** that event (PATCH `/api/projects/{pid}/review/{event_id}` with `rejected: true`).
- **Click on empty area → "Add missed vehicle"** modal: pick origin leg, pick movement, confirm position; POST new event.
- Running count display updates live.
- Per-camera selector (switch between Camera 1 view, Camera 2 view at the same intersection-day).
- Excel download button.

Acceptance: play a fixture video, reject 2 detected events, add 1 missed event, counts update, Excel reflects the corrections.

### Phase 10 — Tests + smoke + polish

Deliverables:
- Update all existing tests to v3 model (video → camera scoping, etc.).
- New end-to-end test: bulk-upload → label → calibrate → trim → process → dedup → Excel.
- HTTP smoke checklist.
- Migration test with a real v2 project DB.
- Documentation pass: update `CLAUDE.md` to reference v3, update `Implementation_Plan_v3.md` with any deviations made during execution.

Acceptance: full test suite green. Smoke flow works end-to-end. v2 project DBs auto-migrate cleanly.

---

## Migration / backward compatibility

- **Existing v2 single-intersection projects**: continue to work without user action. On first DB connection under v3 schema, default intersection + camera + trim are created and existing data is linked to them.
- **In-progress processing at upgrade time**: defer — if the user is mid-processing when v3 ships, they should let it finish before upgrading. The release note must call this out.
- **External dependencies**: no new pip packages required for Phases 1–5. Phase 9 may want a small JS video-overlay library, but vanilla HTML5 `<video>` + canvas overlay is sufficient and consistent with the no-build-tools constraint.

---

## Risks and open questions

1. **Cross-camera dedup tuning** — the ±5s time window and label-match logic is a starting point. Real-world data may show ID drift between cameras that requires looser matching, or false-positive dedups that require stricter matching. Plan: ship with conservative defaults, expose the threshold in config, and add a "dedup audit" sheet to Excel so engineers can spot-check decisions.
2. **Click-to-add-missed-vehicle UX (Phase 9)** is fiddly. Selecting an origin leg from a 2D image, identifying the movement, picking a vehicle class — that's 3 dropdowns minimum on top of the click. Worth a quick UI prototype before committing the full implementation.
3. **Filename parsing failures** — if more than 20% of a batch has unparseable filenames, the labeling table becomes painful. Mitigation: bulk-edit operations ("set intersection name on selected rows", "set date on selected rows") and a clear "needs attention" highlight.
4. **Trim coverage edge cases** — videos that span midnight, daylight-saving transitions during a recording, cameras with subtly different system clocks. Phase 1's `coverage.py` tests should include these. For DST and clock drift, document the assumption that all recording clocks are correct ±1 second; surface a warning if camera clocks at the same intersection appear to differ by more than 30 seconds.
5. **Concurrency at the database level** — multiple intersection-day pipelines writing to the same `vehicle_events` table on the same DB file. SQLite WAL mode handles this but the events writes may contend. Probably fine at our scale (typically 2 concurrent pipelines), but worth profiling once Phase 4 lands.

---

## Out of scope (deferred to v4 or later)

- Multi-project comparison views (e.g., "compare counts for Main St between this study and last year's study").
- Cross-day analytics within a project ("typical weekday vs weekend at this intersection").
- Camera health monitoring (drift detection, recording-gap alerting).
- Automatic re-processing when calibration is changed (currently a manual re-process required).
- A11y / keyboard-driven correction in the playback view.
- Mobile / tablet-friendly UI.
- Export formats other than the existing FHWA TMC Excel.

---

## Effort and cadence

- **Total scope**: ~10 sessions, larger than the v2 integration but more incremental (each phase reviewable independently).
- **Recommended cadence**: 1 phase per session with a brief checkpoint pause between. Frontend phases (6, 7, 8, 9) are the riskiest for UX surprises; budget extra time for iteration.
- **No code is written until the plan is reviewed and signed off.**

---

## Document conventions

- All times stored in ISO format with timezone (`2026-05-14T07:00:00-05:00`) unless otherwise noted.
- Wall-clock trim inputs are local-time `HH:MM:SS` (the recording date supplies the rest).
- Database is per-project SQLite at `data/projects/{project_id}/project.db` (unchanged from v2).
- Vanilla HTML/CSS/JS only on the frontend. No React, no npm, no build tools (per CLAUDE.md hard constraint).
- Python 3.11+ with type hints (per CLAUDE.md hard constraint).
