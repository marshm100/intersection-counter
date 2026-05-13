# PRD v2 — Intersection Counter

**Status:** Draft for review
**Owner:** DeShazo Group, Inc.
**Date:** 2026-05-13

> Sections marked **[ASSUMPTION]** are defaults the author chose because they weren't explicitly stated. Flag any that need to change before we lock in the TDD and Implementation Plan.

---

## 1. Problem

Traffic engineers at DeShazo run intersection turning-movement counts (TMCs) from camera video. Today they pay per-video for commercial services (GoodVision, Miovision). Those services are accurate but cost money, leak data to a third party, and add turnaround time.

Intersection Counter is the in-house replacement: a single-operator desktop-class web app, run on the engineer's own machine, that ingests one or more video files of an intersection and produces a standard FHWA TMC Excel report — without sending the video off-machine.

## 2. Users

Single user: a traffic engineer at DeShazo.

- Comfortable with desktop software. Not a developer.
- Runs the app locally on their own workstation.
- Cares about: accuracy of vehicle counts and movements, ability to spot-check and correct mistakes, Excel output that matches what their clients expect.
- Does **not** care about: cloud, sharing, multi-tenancy, mobile, real-time.

## 3. Product shape

**Localhost web app.** A Python backend (FastAPI) serves a static HTML/JS frontend at `http://127.0.0.1:5000`. The user launches the app from a terminal or shortcut, copies the URL into their browser, and works there. No installer, no electron, no pywebview. No internet connection required after the initial install.

**Single-operator.** No login, no roles, no concurrent users. The app assumes one person is driving it.

**Per-project state.** Each TMC job (one intersection, one time window) is a "project" — its own directory on disk with a SQLite database and the source video file paths. Projects are independent; deleting one never affects another.

## 4. Hard constraints

These are inherited from the v1 work and remain non-negotiable:

- **Frontend:** Vanilla HTML/CSS/JavaScript. **No** React, Vue, Svelte, or any framework. **No** npm, no bundlers, no build step. Frontend code is loaded as plain `<script>` tags.
- **Database:** Raw `sqlite3`. **No** ORM, no SQLAlchemy, no migrations framework. Schema is created from a `CREATE TABLE IF NOT EXISTS` block in code.
- **Turn classification:** Trajectory shape analysis based on net heading change. **No** exit-zone geometry. **No** turn matrix lookup tables.
- **Excel output:** Hard-coded integer cell values. **No** Excel formulas in output.
- **Resilience:** The processing pipeline **never** halts on single-frame errors. Bad frames are logged and counted; the pipeline continues.
- **Python 3.11+** with type hints throughout.

## 5. Out of scope for v2

Listing these explicitly so they don't sneak in:

- **Pedestrians.** v1 had a pedestrian_events table but no processing. v2 drops pedestrian counting entirely. Schema, UI, and Excel output exclude pedestrians. (Reversible in v3 if needed.)
- **Crosswalk classification.** Same as pedestrians.
- **Multi-user / authentication.** Localhost, single user.
- **Cloud sync / sharing.** All data stays on the user's machine.
- **Mobile / responsive design.** Desktop-class viewport only (≥1280px).
- **Real-time processing.** Video processing is offline (faster-than-real-time on GPU, slower than real-time on CPU). No live camera ingestion.
- **Reprocessing only part of a video.** A processing run is whole-video; pausing/resuming is supported, but "process frames 5000–8000 only" is not.
- **Vehicle classification beyond FHWA-13.** No license plate reading, no make/model.

## 6. Functional requirements

### 6.1 Projects

- Create a project with a name. Project ID is a generated short hex string.
- List all projects with: name, status (`created` → `configured` → `processing` → `paused` → `complete` → `error`), created date.
- Open a project (loads its state into the current session).
- Rename a project.
- Delete a project (with confirmation). Deletes the entire project directory.
- A project's data lives entirely under `data/projects/<project_id>/`.

### 6.2 Videos (multi-video per project)

A project holds **N videos** (`N ≥ 1`). Multiple cameras of the same intersection during the same time window, or sequential chunks of one long recording, can be added to a single project and aggregated into one TMC report.

- Add a video file: native file picker, MP4/MOV/AVI supported.
- Display per-video metadata: filename, duration, fps, resolution, codec, file size, embedded creation timestamp (if present, used as a default for "recording start time").
- Manually set "recording start time" for each video (local wall-clock datetime).
- Remove a video from a project (with confirmation — clears its events).
- View the first frame of each video as a thumbnail.

**[ASSUMPTION]** Calibration is done once per project and is shared across all the project's videos. Justification: multi-video usually means same camera angle (sequential chunks) or same intersection from similar angles (multi-camera setup with consistent framing). If videos have meaningfully different angles, the user creates separate projects.

### 6.3 Auto-calibration with manual confirm

The user does **not** manually drag origin lines onto a video frame. Instead:

1. After videos are loaded, the user clicks **"Auto-calibrate."**
2. The app runs a **prescan** over the first **5 minutes** (configurable, capped at video duration) of the first video.
   - YOLO detection + ByteTrack tracking on every Nth frame (frame-skip 3 default).
   - Records all completed trajectories: entry point, exit point, path length.
3. The auto-calibration service clusters trajectory endpoints to infer:
   - The number of legs (2, 3, or 4) — based on density of entry/exit clusters near the frame edges.
   - The position and orientation of each leg's **origin line** — perpendicular to the dominant traffic flow at that leg, placed just inside the frame.
   - The **intersection center** — centroid of all trajectory crossings.
   - Each leg's **reference heading** — direction from the origin line's midpoint toward the intersection center.
   - Each leg's **cardinal direction** label (N/S/E/W) — based on the screen-relative bearing of the leg from the intersection center, with a screen-orientation hint from the user (see below).
4. The user is presented with a single video frame overlaid with the proposed legs (line + arrow showing reference heading) and intersection center marker. They can:
   - **Confirm** the calibration as-is.
   - **Adjust** any leg by dragging its endpoints or label, or change its cardinal direction via a dropdown.
   - **Reject and redo** — re-run prescan over a different segment of the video.
   - **Manual fallback** — fully manual click-to-place mode if auto-detect failed too badly.

**Inputs to auto-calibration:**
- **Screen-orientation hint:** the user is asked once at calibration start, "which direction is north on this video?" — choices: up, down, left, right. This is needed to translate screen bearings into cardinal labels.
- **Expected number of legs:** optional (2/3/4/auto). Default auto.

**[ASSUMPTION] Confidence threshold for "calibration succeeded":** if the auto-calibration produces fewer than 3 legs with ≥30 trajectories each over 5 minutes, the app warns the user and recommends manual fallback or a longer prescan.

**[ASSUMPTION] Manual fallback UX:** click 2 points per leg to draw the origin line, then click once for the intersection center. Cardinal direction defaults from the screen-orientation hint and can be overridden per leg.

### 6.4 Processing

For each video in the project, the pipeline:

1. Loads the AI models once (YOLO + ByteTrack).
2. Iterates frames at `frame_skip` (default 3), preprocesses each (adaptive CLAHE/gamma based on lighting), detects vehicles, updates the tracker.
3. For each tracked vehicle, watches for an origin-line crossing. Once crossed, accumulates the trajectory until the track is lost.
4. On track loss, classifies the trajectory as `through`, `left`, `right`, `u_turn`, or `insufficient_data` (discarded). Writes a `vehicle_events` row.
5. Saves a checkpoint to the project DB every **120 seconds of video time**.

**Controls (per project):**
- **Start:** begin processing from frame 0 of the first unprocessed video.
- **Pause:** signal the loop to save a checkpoint and exit cleanly.
- **Resume:** restart from the most recent checkpoint (rewinds ~60 seconds for tracker re-warmup).
- **Cancel:** stop processing, clear the checkpoint, reset status to `idle`. Events from prior runs are kept unless the user explicitly clears.
- **Reset events:** delete all events for the project, leaving calibration intact.

**Progress display (live, polled at 1 Hz from frontend):**
- Per-video and overall progress percentage.
- Frames processed, current video timestamp.
- Running vehicle count.
- Processing FPS.
- ETA.
- Error frame count.

**Multi-video handling:**
- Videos process sequentially (one at a time) within a project.
- The tracker is **reset between videos** — track IDs do not bridge videos (we cannot assume the same vehicle reappears).
- Each vehicle event carries a `video_id` foreign key. Aggregation across videos happens at the report layer.

**[ASSUMPTION]** Only one project may process at a time per server instance. Starting processing on a second project while one is running returns HTTP 409 with a helpful error.

### 6.5 Dashboard

Read-only summary of processed events for the current project, aggregated across all videos:

- **Totals:** total vehicles, total events flagged as low-confidence.
- **TMC matrix:** rows are approach legs (sorted by sort_order), columns are `Through | Left | Right | U-Turn | Total`. Integer counts.
- **Time series chart:** vehicles per **15-minute interval** (interval is configurable per-project, default 15 min, per FHWA standard). Bars labeled with start time in `HH:MM` (uses real-world clock time if a recording start time is set, else `MM:SS` from video start).
- **Per-vehicle-class breakdown:** count by simplified class (`motorcycle / car / pickup_van_suv / bus / single_unit_truck / multi_unit_truck`).

**[ASSUMPTION]** The dashboard does not compute peak-hour or warrant analysis — that lives in Excel. The dashboard is for in-app QA only.

### 6.6 Review

Per-event manual correction interface:

- Paginated table of `vehicle_events` for the project.
- **Filters:** by leg, by movement, by vehicle class, low-confidence only, manually-edited only.
- **Per-event actions:**
  - Edit movement (dropdown: through/left/right/u_turn).
  - Edit vehicle class (dropdown: motorcycle/car/pickup_van_suv/bus/single_unit_truck/multi_unit_truck).
  - **[ASSUMPTION]** Mark as "rejected" (a soft delete — excluded from reports). Better than hard delete because it's reversible and auditable.
- **Per-event preview:**
  - Frame thumbnail at the event's frame number, with the vehicle's trajectory overlaid as a polyline.
  - Click-through to the original video frame.
- Any edit sets `manually_edited = 1` on the row; the dashboard and Excel reflect edited values.
- Bulk operations are **out of scope** for v2. (Add in v3 if review is too slow.)

**[ASSUMPTION]** Review supports keyboard shortcuts: `j`/`k` to move between events, `1-4` for movement, `Enter` to save, `r` to mark rejected. Drives faster engineer throughput. If you don't want shortcuts, say so.

### 6.7 Excel export

Single download: a **Standard FHWA Turning Movement Count report** as `.xlsx`.

**[ASSUMPTION] Layout:** based on the most common engineer-facing FHWA TMC template:

- One worksheet per leg ("North Approach," "South Approach," etc.), plus one summary worksheet.
- Each approach sheet has rows for each 15-minute interval (or whatever interval the project is configured to use) and columns: `Time Start | Through | Left | Right | U-Turn | Total | by vehicle class breakdown`.
- Summary sheet: total counts and peak-hour highlight (PM peak by default, computed from the time series).
- All values are integer literals — no formulas, no references.

The exact layout will be refined once you point me at a reference template. **If a specific template exists, drop it in `docs/research/` before we lock the TDD** — I'll match its cell layout exactly.

### 6.8 Settings (per project)

- Recording start time (per video).
- Interval length for TMC bucketing (default 15 min; allowed: 5, 10, 15, 30, 60).
- Frame skip (default 3; allowed: 1–10).
- Prescan duration in seconds for auto-calibration (default 300).
- Number of legs hint (default auto).
- Screen-orientation hint (up/down/left/right).

### 6.9 Settings (global, server-level)

Set via environment variables or `config.py`:

- **Bind address:** default `127.0.0.1`. Set `INTERSECTION_COUNTER_HOST=0.0.0.0` to expose on the LAN. Default is loopback-only.
- **Port:** default 5000.
- **Device:** `auto` (detect CUDA, fall back to CPU) | `cuda` | `cpu`. Default `auto`.
- **YOLO model:** default `yolov8s.pt` on GPU, `yolov8n.pt` on CPU. Override via env var.
- **Data directory:** default `./data`. Override via env var.

The server **prints the URL** on startup. It does **not** auto-open a browser tab.

## 7. Non-functional requirements

### 7.1 Performance

**Aggressive GPU is the recommended path.** YOLOv8s on a modern CUDA GPU runs at ~50–100 fps at 1080p; at frame-skip 3 that's ~150–300x real-time on a 1080p source, plus tracking/classification overhead.

- **Target on RTX 3060+ at 1080p:** **at least 5× real-time** end-to-end (1 hour of video processed in ≤12 minutes).
- **Target on CPU only (Intel i5 / Ryzen 5 class):** **best-effort.** A 1-hour video may take 1–3 hours. Acceptable for occasional use; the app must remain usable (no UI freezes, checkpoints save reliably).
- **Memory:** keep peak RAM under 4 GB regardless of video length. (Achieved by streaming frames, not loading whole video.)
- **Disk:** project size scales with event count, not video length. A 4-leg intersection in a 1-hour video at ~1k events ≈ <10 MB SQLite.

### 7.2 Accuracy

**[ASSUMPTION] Target accuracy** (against engineer-validated ground truth):

- **Total vehicle count per approach per 15-minute interval:** within **±5%** in ≥95% of intervals.
- **Movement classification:** ≥**90%** correct for the four movement classes.
- **Vehicle class:** ≥**80%** correct for the six simplified classes. Vehicle class is the weakest link (truck sub-classification by bbox heuristic is approximate) and is expected to be corrected in Review.

If a project's processed events fall below these bars, the engineer corrects them in Review. The bars are targets for the AI, not gates on the workflow.

### 7.3 Reliability

- **Pipeline never halts on per-frame errors.** Frame-level exceptions are caught, logged, and incremented in `error_count`. The pipeline continues.
- **Checkpoint on disk every 120 video-seconds.** Power loss during processing recovers to the last checkpoint with ≤2 minutes of work lost.
- **Atomic DB writes.** Each vehicle event commits in its own transaction. WAL mode for the SQLite database.
- **No silent data loss.** If a video file disappears mid-processing (e.g., network drive unmounted), the pipeline halts with a clear error visible in the UI.

### 7.4 Security

Localhost binding by default. No authentication. No CSRF protection (single-origin localhost). When the user opts into LAN binding (`HOST=0.0.0.0`), the documentation warns that anyone on the network can read and modify any project. (No auth layer is added in v2.)

### 7.5 Footprint

- Install size: ≤2 GB including PyTorch, CUDA wheels, YOLO weights.
- First-launch network: only required to download YOLO weights (~10–50 MB depending on model size). After that, fully offline.

## 8. Domain model

### 8.1 Movements (vehicles)

Five values, only the first four ever exported:

| Value | Meaning |
|---|---|
| `through` | Net heading change ≤ 30° and path straightness > 0.85 |
| `left` | Net heading change between −45° and −135° (counter-clockwise) |
| `right` | Net heading change between +45° and +135° (clockwise) |
| `u_turn` | Net heading change ≥ 135° (either sign) |
| `insufficient_data` | <10 trajectory points or <50 px path — discarded, not exported |

The exact thresholds match the v1 `trajectory_classifier.py` and are not changing in v2.

### 8.2 Vehicle classes (simplified, six)

| Simplified | YOLO source | FHWA class (default) |
|---|---|---|
| `motorcycle` | YOLO class 3 | 1 |
| `car` | YOLO class 2, bbox area ≤ 4000 | 2 |
| `pickup_van_suv` | YOLO class 2 with bbox area > 4000, **or** YOLO class 7 with aspect ratio ≤ 1.5 | 3 |
| `bus` | YOLO class 5 | 4 |
| `single_unit_truck` | YOLO class 7 with aspect ratio > 1.5 and bbox area ≤ 5000 | 5 |
| `multi_unit_truck` | YOLO class 7 with aspect ratio > 2.0 and bbox area > 5000 | 9 |

Pedestrians (YOLO classes 0, 1) are **not** processed in v2.

The bbox-based truck sub-classification is approximate. Engineers correct misclassifications in Review.

### 8.3 Legs

A leg is an approach to the intersection:

| Field | Description |
|---|---|
| `label` | Human-readable: "North Approach," "Eastbound," etc. |
| `cardinal_direction` | One of `N / S / E / W / NE / NW / SE / SW` |
| `sort_order` | Display order in dashboards/Excel (0-indexed) |
| `origin_zone` | Line segment `[[x1, y1], [x2, y2]]` in pixel coordinates of the calibration frame |
| `reference_heading` | Degrees, 0° = north (up), 90° = east (right), image coordinates |

A vehicle is assigned to a leg the moment its centroid crosses that leg's origin_zone line (entering the intersection).

### 8.4 Intervals

Time bucketing for the TMC report. Default **15 minutes** per FHWA standard. Buckets are aligned to the recording start time (e.g., if the video starts at 14:23, the first bucket is `14:15–14:30`, padded).

## 9. Workflows

### 9.1 Full happy-path flow

1. User opens app, sees projects list.
2. Clicks "Create project," enters a name.
3. Adds one or more video files. Sets recording start time per video.
4. Clicks "Auto-calibrate." Picks screen-orientation hint. Waits ~30 seconds (prescan on 5 min @ frame-skip 3 on GPU).
5. Reviews proposed legs on the calibration frame. Adjusts any cardinal labels. Confirms.
6. Clicks "Start processing." Watches progress.
7. When complete, clicks "View dashboard." Spot-checks the TMC matrix.
8. Clicks "Review events." Filters to low-confidence events. Corrects misclassifications.
9. Clicks "Export Excel." Downloads `.xlsx`. Done.

### 9.2 Pause/resume

User pauses mid-processing (e.g., closing laptop). Project status → `paused`. On reopening the app:
- Project list shows `paused` status.
- Opening the project shows the processing page with `Resume` and `Cancel` buttons.
- Resume continues from the last checkpoint.

### 9.3 Auto-calibration failure

If prescan produces too few trajectories or wildly inconsistent leg counts:
- Auto-calibrate result page shows a warning + the best-guess overlay.
- User options: **redo with longer prescan**, **manual fallback** (click points), or **adjust the auto-result manually** (drag endpoints).

### 9.4 Re-processing

User wants to re-run processing on a project (e.g., after re-calibration):
- "Reset events" button on the processing page clears all `vehicle_events` for the project, preserves calibration, resets status to `idle`.
- "Start processing" begins from frame 0 of the first video.

## 10. Open product decisions

The following decisions need a "yes/no/different" from you before I lock the TDD:

| # | Topic | Default I'm going with |
|---|---|---|
| 1 | Manual fallback UX | Click 2 points per leg + 1 for center. (§6.3) |
| 2 | "Confidence threshold" for auto-calibration to succeed | ≥3 legs with ≥30 trajectories each over 5 minutes. (§6.3) |
| 3 | Soft-delete events in Review | Yes, add a `rejected` flag column. (§6.6) |
| 4 | Keyboard shortcuts in Review | `j/k`/`1-4`/`Enter`/`r`. (§6.6) |
| 5 | Excel template | "Standard FHWA TMC report" — but I need a reference template to match exactly. (§6.7) |
| 6 | Calibration shared across multi-video projects | Yes, one calibration per project. (§6.2) |
| 7 | Concurrent processing | Only one project at a time per server instance. (§6.4) |
| 8 | Accuracy targets | ±5% counts, 90% movement, 80% class. (§7.2) |
| 9 | LAN binding security | No auth, just a doc warning when `HOST=0.0.0.0`. (§7.4) |
| 10 | Vehicle "rejected" vs hard delete | Soft delete (rejected flag). (§6.6) |

## 11. Migration from v1

The current codebase ("v1" — the work in Steps 0–6 on `claude/bootstrap-project-structure-TC2A0`) is preserved and refactored in place rather than rewritten. The Implementation Plan in `Implementation_Plan_v2.md` enumerates which files are kept, modified, added, or removed. No big-bang rewrite.

Highlights of what changes from v1:

- **Schema:** add a `videos` table, add `video_id` foreign key to `vehicle_events`, add `rejected` flag, drop the `pedestrian_events` table.
- **Backend:** add auto-calibration service, Excel exporter, multi-video pipeline orchestration, GPU device selection. Refactor `processing.py` router to handle multi-video.
- **Frontend:** build the calibration page, add multi-video management to Setup, add frame previews to Review, add Excel download button.
- **Launchers:** delete `run.py` (pywebview), `start_server.py`, `serve.bat`. Replace with one canonical entry point.
- **Cleanup:** remove pywebview from requirements, delete stale Copy files, retitle README and CLAUDE.md from "Desktop app" to "Localhost web app."
