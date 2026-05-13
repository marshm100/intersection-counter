# Implementation Plan v2 — Intersection Counter

**Status:** Draft for review
**Companion to:** PRD_v2.md, TDD.md
**Date:** 2026-05-13
**Strategy:** Refactor in place. Build the v2 feature set on top of the v1 codebase via incremental, individually-testable steps. No big-bang rewrite.

---

## What's already done (v1, Steps 0–6)

The current branch contains six committed steps that produced a working baseline:

| Step | Title | What it produced |
|---|---|---|
| 0 | Project skeleton and configuration | Folder layout, `config.py`, `database.py`, project_info table, blank routers/services |
| 1 | Projects CRUD | `projects.py` router + frontend Projects page |
| 2 | Video service + Setup page | `video_service.py`, `video.py` router, Setup page with file picker + metadata + thumbnail |
| 3.3 | Vehicle Classification Service | `classifier.py` (FHWA mapping + bbox heuristics) |
| 4.3 | Adaptive Image Preprocessor | `preprocessor.py` (CLAHE + gamma LUTs) |
| 4.4 | Checkpoint Manager + Processing Pipeline | `checkpoint.py`, `pipeline.py`, full vehicle pipeline with pause/resume |
| 5 | Processing Router API + pywebview desktop wrapper | `processing.py` router, `run.py` (pywebview), frontend Processing page |
| 6 | Dashboard + Review API and frontend | `dashboard.py`, `review.py` routers + corresponding frontend pages |

Steps 3.1, 3.2, 4.1, 4.2 covered foundational services (detector, tracker, origin_detector, trajectory_classifier) — these are also done and in `backend/services/`.

**v1 leaves these as 43-byte stubs:** `calibration.py` (router), `excel_export.py`, `aggregator.py`, `validator.py`, `prescan.py`. v2 fills in the first three and drops the latter two.

---

## v2 work — overview

Twelve steps, in order. Each is one PR-sized increment with tests, ending in a single commit named per CLAUDE.md: `Step X.Y — [title]`.

| Step | Title | Approx. effort |
|---|---|---|
| 7.0 | Cleanup: drop pywebview, consolidate launcher, delete Copy files | ~0.5 day |
| 7.1 | Update CLAUDE.md and README.md for localhost framing | ~1 hour |
| 7.2 | Schema migration: videos table, video_id FK, rejected flag, drop pedestrians | ~0.5 day |
| 7.3 | GPU/CPU device detection | ~0.5 day |
| 7.4 | Multi-video router and service | ~1 day |
| 7.5 | Multi-video Setup page | ~1 day |
| 7.6 | Auto-calibration service | ~2 days |
| 7.7 | Calibration router (auto + manual fallback) | ~1 day |
| 7.8 | Calibration page (frontend, full implementation) | ~2 days |
| 7.9 | Multi-video pipeline orchestration | ~1 day |
| 7.10 | Aggregator service + updated dashboard router | ~1 day |
| 7.11 | Review enhancements (rejected, preview, keyboard) | ~1 day |
| 7.12 | Excel export service + endpoint + frontend button | ~1.5 days |

Total: ~12 working days. Each step is independently mergeable — the app remains usable after every commit.

---

## Step 7.0 — Cleanup

**Goal:** A single canonical launcher, no pywebview, no stale duplicates.

### Files

**Delete:**
- `run.py` (replaced — see below)
- `start_server.py`
- `serve.bat`
- `requirements - Copy.txt`
- `.claude/settings.local - Copy.json`
- `.claude/settings.local - Copy (2).json`

**Modify:**
- `requirements.txt` — drop `pywebview>=4.4.1`.

**Add (replacing run.py):**

```python
# run.py — canonical launcher for the localhost web app.
"""Print the URL and start uvicorn. No pywebview, no auto-open.

Read HOST, PORT, DEVICE from env vars with sensible defaults.
"""

import os
import sys

import uvicorn

HOST = os.environ.get("INTERSECTION_COUNTER_HOST", "127.0.0.1")
PORT = int(os.environ.get("INTERSECTION_COUNTER_PORT", "5000"))


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    print(f"\n  Intersection Counter\n  Open in your browser: {url}\n")
    if HOST == "0.0.0.0":
        print(
            "  WARNING: Listening on 0.0.0.0 — anyone on your LAN can read and "
            "modify projects. There is no authentication.\n"
        )
    uvicorn.run("backend.app:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    sys.exit(main())
```

### Acceptance

- `python run.py` starts the server, prints the URL, does not open a browser.
- `pip install -r requirements.txt` succeeds without pywebview.
- `git status` shows the Copy files are gone.

### Commit

`Step 7.0 — Cleanup: drop pywebview, unify launcher`

---

## Step 7.1 — Docs framing

**Goal:** Documentation reflects "localhost web app" rather than "desktop app."

### Files

**Modify:**
- `CLAUDE.md` — change "Desktop app" → "Localhost web app". Add reference to PRD_v2.md / TDD.md / Implementation_Plan_v2.md (already implied by current text). Add quick-start command (`python run.py`).
- `README.md` — rewrite quick-start, point to docs, note GPU support requirement and fallback.

### Acceptance

- `CLAUDE.md` no longer says "desktop."
- `README.md` has a working quick-start that includes the GPU install hint and the URL print.

### Commit

`Step 7.1 — Docs: localhost framing`

---

## Step 7.2 — Schema migration

**Goal:** The v2 database schema as specified in `TDD.md §5`.

This is a **destructive** schema change. There is no migration tool. v1 projects that have already processed events will not migrate — they're test data. The schema applies to new projects only.

### Files

**Modify:**
- `backend/database.py`:
  - Replace `SCHEMA` constant with the full v2 SQL (see TDD.md §5).
  - Add `videos`, `calibration_frame` tables.
  - Add `video_id`, `rejected` to `vehicle_events`. Update its CREATE statement and indexes.
  - Add `current_video_id` to `checkpoint`.
  - Drop `pedestrian_events` and `low_confidence_segments` from `SCHEMA`.

**Add:**
- `backend/database.py` helper functions:
  - `add_video(project_id, path, metadata) -> int` — returns `video_id`.
  - `list_videos(project_id) -> list[dict]`.
  - `remove_video(project_id, video_id) -> None` — cascades event deletion.
  - `set_calibration_frame(project_id, video_id, frame_number, jpeg_bytes) -> None`.
  - `get_calibration_frame(project_id) -> tuple[int, int, bytes] | None`.

**Remove:**
- All references to `pedestrian_events` in `dashboard.py`, `review.py`, frontend. Schema constants `PEDESTRIAN_CLASSES` stay in `config.py` because `detector.py` still filters by them (we just no longer write rows).
- Wait — actually: drop `PEDESTRIAN_CLASSES` from `detector.py`'s class filter. Save inference time. Update `tracker.py` to drop pedestrian fields. See **subtask 7.2a** below.

### Subtask 7.2a — Strip pedestrians from inference

- `detector.py`: change `RELEVANT_CLASSES` to `sorted(VEHICLE_CLASSES.keys())`. Remove `is_pedestrian` from each detection dict.
- `tracker.py`: same.
- `pipeline.py`: remove the `pedestrian_count` counter and any `is_pedestrian` branches. `_process_single_frame` becomes vehicle-only.
- `processing.py` router: remove `pedestrian_count` from progress payload.
- `frontend/js/processing.js`, `dashboard.js`: remove pedestrian cells.

### Tests

- Existing pipeline tests with mocked pedestrian detections must be updated or removed.
- New test: `test_database.py` must assert `videos`, `calibration_frame`, the new columns, and indexes.

### Acceptance

- New projects DB has the v2 schema. Old projects fail loudly if opened (acceptable — test data).
- `python -m pytest backend/tests/` passes.

### Commit

`Step 7.2 — Schema migration: videos, rejected, drop pedestrians`

---

## Step 7.3 — Device detection

**Goal:** Pipeline runs on GPU when available, falls back to CPU. Model size adapts.

### Files

**Add:**
- `backend/services/device.py`:
  ```python
  def detect_device(override: str | None = None) -> str:
      """Return 'cuda' if CUDA is available and override allows, else 'cpu'.

      `override` accepts 'auto' (or None), 'cuda', 'cpu'.
      Raises if 'cuda' is requested but unavailable.
      """

  def default_model_path(device: str) -> str:
      """Return 'yolov8s.pt' for GPU, 'yolov8n.pt' for CPU."""
  ```

**Modify:**
- `backend/config.py`:
  - Read `DEVICE` env var with default `"auto"`.
  - Read `YOLO_MODEL` env var with default `None` (fall through to device-dependent default).
- `backend/services/detector.py`:
  - `VehicleDetector.__init__(model_path, device)` — accept device, pass to `self.model(...)`.
  - Default `model_path` resolved via `default_model_path(device)`.
- `backend/services/pipeline.py`:
  - `ProcessingPipeline.__init__` accepts `device`. Pass through to `VehicleDetector`.
- `backend/routers/processing.py`:
  - Read device once on first use; cache.
- `backend/app.py`:
  - On startup: `app.state.device = detect_device(os.environ.get('DEVICE'))`.
  - Update `/api/health` to return `{status, device, model}`.

### Tests

- `test_device.py`: mock `torch.cuda.is_available()` to test all branches.
- `test_health.py`: assert device and model are in the response.

### Acceptance

- `python run.py` on a CUDA machine: `/api/health` returns `device="cuda"`.
- On a CPU-only machine: `device="cpu"`, model is `yolov8n.pt`.
- Setting `DEVICE=cpu` env var on a GPU machine forces CPU.
- Setting `DEVICE=cuda` on a CPU machine raises a clear error at startup.

### Commit

`Step 7.3 — GPU/CPU device detection`

---

## Step 7.4 — Multi-video router and service

**Goal:** Backend supports multiple videos per project (PRD §6.2).

### Files

**Rename:**
- `backend/routers/video.py` → `backend/routers/videos.py`.

**Modify `videos.py`:**

Replace single-video endpoints with the multi-video API from TDD §6.2:

```python
@router.get("/projects/{pid}/videos")
def list_videos(pid: str) -> list[dict]: ...

@router.post("/projects/{pid}/videos/browse")
async def browse_video(pid: str) -> dict: ...   # native file picker

@router.post("/projects/{pid}/videos")
def add_video(pid: str, body: AddVideoBody) -> dict: ...

@router.delete("/projects/{pid}/videos/{vid}")
def remove_video(pid: str, vid: int, confirm: bool = False) -> dict: ...

@router.put("/projects/{pid}/videos/{vid}/start_time")
def set_start_time(pid: str, vid: int, body: StartTimeBody) -> dict: ...

@router.get("/projects/{pid}/videos/{vid}/frame")
def get_frame(pid: str, vid: int, seconds: float = 0.0) -> Response: ...

@router.put("/projects/{pid}/videos/{vid}/order")
def set_order(pid: str, vid: int, body: OrderBody) -> dict: ...
```

`video_service.py` is reusable as-is; it operates on file paths and doesn't care about projects.

**Modify `backend/app.py`:**
- `from backend.routers import projects, videos, calibration, processing, dashboard, review, export`
- `app.include_router(videos.router, prefix="/api")`
- Remove the old `video.py` import.

**Modify all callers that previously read `video_path` from `project_info`:**
- `backend/routers/processing.py`: load videos via `list_videos()`. Loop in pipeline orchestration (Step 7.9).
- `backend/services/pipeline.py`: pipeline gets a single video at a time; orchestration is a level above (Step 7.9).
- `backend/routers/dashboard.py`, `review.py`: events already have `video_id`, no change required here.

### Tests

- `test_videos_api.py` (formerly `test_video_api.py`): full CRUD coverage.
- Remove any test that asserts `video_path` lives in `project_info`.

### Acceptance

- A project can hold ≥1 video. The DB carries one `videos` row per added video.
- Removing a video deletes its `vehicle_events`.
- Setting `recording_start_time` per video persists.
- The native file picker still works (uses `tkinter` in a thread).

### Commit

`Step 7.4 — Multi-video router and service`

---

## Step 7.5 — Multi-video Setup page

**Goal:** Setup page lists all videos in the project, supports add/remove/reorder/start-time.

### Files

**Replace `frontend/js/setup.js`:** the page now consists of:

- Project name (top, editable as today).
- Settings: number-of-legs hint, interval minutes, screen-orientation hint, prescan duration.
- "Videos" section: list of cards (thumbnail + filename + duration + start-time field + remove button + drag handle).
- "Add video" button → file picker.
- "Start calibration" button (disabled until ≥1 video).
- "Proceed to processing" button (disabled until calibration is complete).

**Add `frontend/js/videos.js`:** the per-video card UI helpers.

**Update `frontend/index.html`:**
- Add `<script src="/static/js/videos.js"></script>` before `setup.js`.

### Acceptance

- User can add 3 videos to a project. They appear in order, each with a thumbnail.
- User can drag to reorder. Backend `sort_order` is updated.
- User can set per-video recording start time.
- Setup page calls `loadSetupPage()` cleanly on navigation.

### Commit

`Step 7.5 — Multi-video Setup page`

---

## Step 7.6 — Auto-calibration service

**Goal:** A pure-backend service that, given a video, infers legs (PRD §6.3, TDD §7).

### Files

**Add `backend/services/auto_calibrator.py`:**

```python
from dataclasses import dataclass

@dataclass
class ProposedLeg:
    label: str
    cardinal_direction: str
    sort_order: int
    origin_zone: list[list[float]]    # [[x1, y1], [x2, y2]]
    reference_heading: float
    trajectory_count: int             # for the confidence check

@dataclass
class CalibrationResult:
    success: bool
    legs: list[ProposedLeg]
    intersection_center: list[float]  # [x, y]
    frame_jpeg: bytes                 # the frame the user will see
    frame_number: int
    reason: str | None = None         # populated when success=False


def auto_calibrate(
    video_path: str,
    prescan_seconds: int,
    screen_north_direction: str,      # 'up' | 'down' | 'left' | 'right'
    num_legs_hint: int | None,        # 2 | 3 | 4 | None for auto
    device: str,
    progress_callback: callable | None = None,
) -> CalibrationResult:
    """Prescan, cluster, propose calibration. Synchronous, long-running.

    Caller runs in a thread.
    """
```

The body follows TDD §7.2 — prescan → filter → cluster (DBSCAN) → place lines → cardinal labels → confidence check.

**Add `_cluster_endpoints(points)` helper** using `sklearn.cluster.DBSCAN(eps=80, min_samples=5)`.

**Add `_assign_cardinals(legs, intersection_center, screen_north)` helper** that converts screen bearings to cardinals.

### Tests

`test_auto_calibrator.py`:
- Synthetic trajectories representing a 4-way intersection (constructed by hand). Assert 4 legs are inferred with correct cardinals.
- Synthetic trajectories for a T-intersection. Assert 3 legs.
- Low-trajectory case. Assert `success=False` with reason.
- Screen-orientation hint test: same trajectories, different `screen_north_direction`, different cardinal labels.

These tests use the **real** classifier and origin_detector functions but **mock** the YOLO detector — `auto_calibrate` accepts an injected detector for testability.

### Acceptance

- Test suite passes including the new ones.
- On a real 5-minute traffic video clip, `auto_calibrate` returns 4 legs with sensible origin lines.
- Runtime: ≤60 s on GPU, ≤5 min on CPU at frame-skip 3.

### Commit

`Step 7.6 — Auto-calibration service`

---

## Step 7.7 — Calibration router

**Goal:** Wire `auto_calibrator` to HTTP endpoints (TDD §6.3).

### Files

**Replace `backend/routers/calibration.py` (currently a 43-byte stub):**

Endpoints per TDD §6.3:
- `POST /api/projects/{pid}/calibration/auto` — start a background thread, return `{job_id}`.
- `GET  /api/projects/{pid}/calibration/auto/status` — poll job state.
- `GET  /api/projects/{pid}/calibration` — read the saved calibration.
- `PUT  /api/projects/{pid}/calibration` — save calibration (legs + frame ref).
- `POST /api/projects/{pid}/calibration/manual` — initialize empty for manual mode.
- `DELETE /api/projects/{pid}/calibration` — clear.

State: a module-level `_calibration_jobs: dict[str, dict]` (job_id → status payload), guarded by a lock. Same pattern as `processing.py`.

**Modify `backend/app.py`** to register the calibration router.

### Tests

`test_calibration_api.py`:
- Start auto-calibration with a mocked `auto_calibrate` that returns canned legs.
- Poll status → confirm `completed` and the result payload.
- Save legs via PUT, read back via GET.
- Manual init + GET → empty legs.

### Acceptance

- Frontend can drive the full auto-calibration flow via these endpoints.
- A failed auto-calibration returns `{success: false, reason: ...}` and the user can fall back to manual.

### Commit

`Step 7.7 — Calibration router (auto + manual)`

---

## Step 7.8 — Calibration page (frontend, full implementation)

**Goal:** Replace the "coming in Step 7" stub with a full calibration UX (PRD §6.3).

### Files

**Replace `frontend/js/calibration.js`:**

The page has three states:

1. **Pre-prescan:** "Run auto-calibration" panel with sliders/dropdowns for prescan duration, screen-orientation hint, num-legs hint. Big button.
2. **Prescan running:** progress bar + "this can take a minute" message.
3. **Review proposed calibration:** the prescan frame as an `<img>` with an SVG overlay drawing each proposed leg (line + arrow) and the intersection center. Buttons:
   - Confirm
   - Adjust (drag endpoints, rename, set cardinal)
   - Redo (back to state 1)
   - Switch to manual (state 4)
4. **Manual mode:** click 2 points per leg + 1 for intersection center. Live SVG redraw as the user clicks.

Use plain SVG inside a `<div>`. No libraries.

**Update `frontend/css/styles.css`** with calibration-specific styles.

### Acceptance

- Full auto + adjust + confirm flow works on a real video.
- Manual fallback flow works.
- Saved calibration is loaded on page revisit.

### Commit

`Step 7.8 — Calibration page (frontend)`

---

## Step 7.9 — Multi-video pipeline orchestration

**Goal:** Processing handles N videos sequentially with correct `video_id` propagation and checkpoint resume across the video boundary (PRD §6.4, TDD §8).

### Files

**Modify `backend/services/pipeline.py`:**

`ProcessingPipeline` already processes a single video. Add a thin orchestrator:

```python
class MultiVideoOrchestrator:
    """Drives a sequence of ProcessingPipeline runs, one per video."""

    def __init__(self, project_id, db_path, videos, legs, device, video_start_times):
        ...

    def run(self, callback=None, start_video_id=None, start_frame=0):
        """Iterate through videos starting from start_video_id (or first).
        Reset tracker between videos. Forward callback up to caller."""

    def pause(self): ...
    def resume_from_checkpoint(self) -> tuple[int, int]: ...
```

The `MultiVideoOrchestrator` becomes the object stored in `_pipelines[project_id]`. Internally it owns a `ProcessingPipeline` for the current video.

**Modify `backend/services/pipeline.py::ProcessingPipeline`:**
- Accept a `video_id` and write it into every `vehicle_events` row.
- Accept a `device` and pass it through.

**Modify `backend/services/checkpoint.py`:**
- `save_checkpoint(...)` now takes `current_video_id`.
- `load_checkpoint(...)` returns `current_video_id` in the dict.

**Modify `backend/routers/processing.py`:**
- `start_processing` loads `list_videos(pid)` and instantiates `MultiVideoOrchestrator`.
- Status payload reports `current_video_id`, total frames across all videos, percent across all videos.

### Tests

`test_pipeline.py`:
- New test: process two short fixture videos in one project. Assert events from both, with correct `video_id`s.
- New test: pause mid-second-video, resume, assert correct continuation.

### Acceptance

- A project with 2 videos processes both. Events from both videos appear in `vehicle_events`.
- Pause mid-video-2, resume → continues from checkpoint without re-processing video-1.

### Commit

`Step 7.9 — Multi-video pipeline orchestration`

---

## Step 7.10 — Aggregator + updated dashboard

**Goal:** TMC pivot and time series across all videos in the project (PRD §6.5, TDD §3.2 + §8.3).

### Files

**Replace `backend/services/aggregator.py` (currently a 43-byte stub):**

```python
def compute_tmc_matrix(
    project_id: str, interval_minutes: int = 15
) -> dict:
    """Aggregate vehicle_events into TMC matrix + time series.

    Excludes rejected events. Returns:
    {
        'tmc_matrix': [{leg_label, cardinal_direction, through, left, right,
                        u_turn, total, by_class: {motorcycle, car, ...}}, ...],
        'time_series': [{interval_start, vehicle_count, by_leg: {...}}, ...],
        'class_breakdown': {motorcycle: int, car: int, ...},
        'totals': {vehicles: int},
        'interval_minutes': int,
    }
    """
```

Uses SQL with GROUP BY, no Python aggregation. Time bucketing by `CAST(timestamp_video / (? * 60) AS INTEGER)`.

**Modify `backend/routers/dashboard.py`:**
- Delegate to `aggregator.compute_tmc_matrix`.
- Remove the inline SQL pivot.
- Remove pedestrian fields.

**Modify `frontend/js/dashboard.js`:**
- Remove pedestrian column from totals line.
- Add per-class breakdown table below the TMC matrix.

### Tests

`test_aggregator.py`:
- Seed a DB with hand-crafted events (multiple videos, multiple legs, mix of rejected/edited). Assert correct aggregation.
- Edge case: empty project → all zeros.
- Edge case: all events rejected → all zeros.

### Acceptance

- Dashboard matches v1 visually except for the pedestrian column.
- Cross-video aggregation: a project with 2 videos shows their events combined in the matrix.

### Commit

`Step 7.10 — Aggregator service + dashboard update`

---

## Step 7.11 — Review enhancements

**Goal:** Reviewer can soft-delete events, see a frame thumbnail with trajectory, and use keyboard shortcuts (PRD §6.6).

### Files

**Modify `backend/routers/review.py`:**
- Accept `rejected` filter param (`?rejected=true|false`).
- `PATCH` accepts `rejected: bool`.
- Add `GET /api/projects/{pid}/review/{event_id}/preview` — opens the relevant video, seeks to the event's frame, draws the trajectory polyline using OpenCV on the frame, returns JPEG.

**Modify `frontend/js/review.js`:**
- Add a thumbnail column with the preview image lazy-loaded on row hover/click.
- Add a "Reject" button per row.
- Add `rejected` filter toggle.
- Wire keyboard shortcuts: `j` (next), `k` (prev), `1/2/3/4` (set movement), `r` (toggle rejected), `Enter` (save).

### Tests

`test_review_api.py`:
- PATCH with `rejected=true` sets the flag and `manually_edited=1`.
- Filter `?rejected=false` excludes rejected rows.
- Preview endpoint returns valid JPEG (assert `image/jpeg`).

### Acceptance

- User can mark an event rejected and it disappears from dashboard totals.
- Hovering an event row shows a thumbnail with the trajectory line.
- Keyboard shortcuts work in Chrome and Firefox.

### Commit

`Step 7.11 — Review enhancements: reject, preview, keyboard`

---

## Step 7.12 — Excel export

**Goal:** One-click `.xlsx` download in the standard FHWA TMC format (PRD §6.7).

### Files

**Replace `backend/services/excel_export.py` (stub):**

```python
from openpyxl import Workbook

def build_tmc_workbook(
    project_id: str,
    interval_minutes: int,
    aggregation: dict,           # the dict from aggregator.compute_tmc_matrix
    project_meta: dict,          # name, location notes, recording dates
) -> bytes:
    """Build the FHWA TMC workbook in memory, return .xlsx bytes."""
```

Layout (per PRD §6.7 [ASSUMPTION], to be confirmed against a real DeShazo template if you provide one):

- **Summary sheet** (default tab):
  - Header rows: project name, dates, intervals.
  - TMC totals table (rows = legs, cols = movements).
  - Class breakdown table.
  - Peak-hour highlight (compute argmax over rolling-hour buckets, mark in red).

- **One sheet per leg** (e.g., "North Approach," "East Approach," etc.):
  - Header: leg label, cardinal direction, total volume.
  - Per-interval table: rows = 15-min start times (or whatever `interval_minutes` is set to), cols = `Through | Left | Right | U-Turn | Total | Motorcycles | Cars | Pickup/Van/SUV | Buses | Single-Unit Trucks | Multi-Unit Trucks`.
  - All cells are integer literals — **no formulas**.

**Replace `backend/routers/export.py` (stub):**

```python
@router.get("/projects/{pid}/export/xlsx")
def export_xlsx(pid: str) -> Response:
    interval = int(get_project_info(pid, "interval_minutes") or 15)
    agg = compute_tmc_matrix(pid, interval)
    meta = get_all_project_info(pid)
    xlsx_bytes = build_tmc_workbook(pid, interval, agg, meta)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{meta.get("project_name","tmc")}.xlsx"'}
    )
```

**Modify `frontend/js/dashboard.js` (or `export.js`):**
- Add an "Export Excel" button on the Dashboard page.
- Button triggers `window.location.href = '/api/projects/{pid}/export/xlsx'`.

### Tests

`test_excel_export.py`:
- Seed a project with 2 legs and 100 events spanning 2 hours.
- Generate the workbook. Open with `openpyxl.load_workbook(BytesIO(bytes))`.
- Assert sheet names. Assert specific cell values (e.g., total Through count for North leg).
- Assert all numeric cells are integers, not formulas.

### Acceptance

- "Export Excel" button on Dashboard downloads `project_name.xlsx`.
- File opens in Excel without errors or warnings.
- Counts in the file match the dashboard.

### Commit

`Step 7.12 — Excel export service + endpoint + button`

---

## Conventions across all steps

### Commits

Every step ends in a single commit. Message format from CLAUDE.md:

```
Step X.Y — [title]
```

If a step balloons (auto-calibration, calibration page), split into 7.6a / 7.6b / 7.6c sub-commits, all closed before moving to the next numbered step.

### Tests

Each step adds tests for new code and keeps the existing suite green:

```
python -m pytest backend/tests/ -v
```

Tests that no longer apply (pedestrian-specific) are deleted, not commented out.

### What this plan deliberately leaves out

- **Schema migration for existing v1 projects.** Per Step 7.2: there is no migration tool. v1 test projects are abandoned. If a real customer project lives on v1 schema at the time we cut over, we'll add a migration script then — not now.
- **Performance benchmarking.** PRD §7.1 sets targets. We don't profile or optimize until the implementation is feature-complete.
- **CI / GitHub Actions.** Out of scope.
- **Packaging / distribution.** The app runs from a `git clone` + `pip install`. Building a Windows installer is a separate v3 concern.
- **Telemetry, crash reporting, analytics.** Not in v2. Local-only app.

### Order matters

The steps are sequenced so each one builds on the previous and the app remains runnable after every commit. Don't skip ahead — e.g., 7.10 (aggregator) depends on 7.9 (multi-video orchestration) producing `video_id`-tagged events. Skipping 7.9 to build the dashboard would lock in single-video assumptions.

### Mid-flight checkpoints

After Steps 7.4, 7.8, and 7.10, do a manual end-to-end smoke test on a real video before proceeding:

- After 7.4: confirm multi-video CRUD works in the UI.
- After 7.8: confirm full auto-calibration flow on a real intersection video.
- After 7.10: confirm dashboard shows correct aggregated counts from a real processing run across 2+ videos.
