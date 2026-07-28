# Plan — F2: live auto-cal perception view (2026-07-28)

MASTER_PLAN §3-F stage 2 (stage 1 shipped 2026-07-07; stage 3 = the
playback studio, NOT this block). The operator-facing defect: auto-cal
"looks stuck" — `_run_job` pins progress_pct at 5.0 for the entire
collection pass, and `collect_trajectories` computes real progress every
30 s then throws it away on stderr (auto_calibrator_v2.py:172,
auto_calibrate.py:137). Everything the live view needs already exists in
the collection loop (frame, detections, tracked boxes, active trails,
finished count) and is discarded.

## Design (observational hook — zero effect on calibration output)

1. `collect_trajectories(..., on_progress=None)` — every ~1 s of wall
   time, call back with {frame_no, start_frame, end_frame, progress,
   active, finished, frame (BGR ndarray), tracked, trails (last ~30 pts
   of each active track)}. Pure observation: no drawing, no state, and
   `on_progress=None` is byte-identical to today (no-regression is
   structural). `run(...)` threads it through.
2. `auto_calibrator_v2._run_job` supplies the callback: honest
   progress_pct = 5 + 85·progress, phase text, active/finished counts;
   renders the preview (boxes + active trails + faint finished-track
   endpoints), downscales to ≤640 w, JPEG q70 into
   `_JOBS[camera_id]["preview_jpeg"]` (bytes, single slot) +
   `preview_seq` bump. `get_status` excludes the bytes (JSON-safe),
   includes seq + counts.
3. Router: `GET .../calibration/suggestion/preview.jpg` — the latest
   frame (404 until one exists, or after process restart — the preview
   is ephemeral by design, like the job store).
4. `calibration.js`: while status=running, poll status (existing loop);
   when preview_seq changes, refresh the preview image over the canvas +
   honest progress bar + "N active / M finished tracks". Vanilla JS, no
   new deps.
5. Cluster view scope (honest): F2 shows EVIDENCE ACCUMULATING (live
   detections + trails + finished-track mass), not mid-pass clustering —
   the clustering itself still runs once at the end, unchanged. The
   "clusters assemble" ambition beyond this is F3 territory.

## Tests + verification

- Unit: collector on_progress fires with correct shapes/cadence and
  None-path unchanged; service callback populates status fields +
  preview bytes (stubbed run); preview endpoint 404-then-200 semantics.
- Live: run the app, start auto-cal on a corridor camera with a ~60 s
  sample window, screenshot the live view mid-pass (screenshots/), and
  confirm the persisted suggestion is unchanged in shape.

## Non-goals

F3 playback studio; any change to clustering/zone fitting; persisting
previews.
