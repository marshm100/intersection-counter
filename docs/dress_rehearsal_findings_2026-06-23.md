# Dress Rehearsal Findings — 2026-06-23

A complete dry run of the new-site / Miovision-replacement procedure
(`docs/new_site_runbook.md`) on a **brand-new fresh project**, to find where the
flow snags before it's run for a client. It snagged a lot — which is the point.

## Setup
- **Project:** "Dress Rehearsal 2026-06-23" — project id `0acb12c0`.
- **Site:** intersection **FM51-CORD4699 — 2026-04-30**, camera **405051**
  (camera_id=2 in this project). Video: `405051_0029_20260430_000003 FM51-CORD4699.mp4`,
  ~24 h @ **10 fps**, covers 00:00:03–24:00.
- A 2nd camera (405061 / FM51-FM2123, camera_id=3) was also uploaded but not worked.
- Drive model: operator (user) drives the UI in a Playwright-opened browser; Claude
  scripts + diagnoses + monitors.

## Findings

### #8 — Auto-cal Cancel was a no-op  — FIXED ✅
- **Symptom:** the "Cancel" button on the auto-calibration banner did nothing; the
  bar stayed at "running 5%".
- **Root cause (two stacked defects):**
  1. `auto_calibrator_v2._run_job` checked `cancel_requested` only **after**
     `run_auto_cal()` returned; the `collect_trajectories` frame loop
     (`scripts/auto_calibrate.py`) never polled it → cancel ignored until the whole
     pass finished (minutes, CPU-pinned).
  2. `calibration.js v3CalibrationCancelAutoCal` fired the POST but never stopped
     polling or cleared the banner → zero feedback.
- **Fix:** `should_cancel` callback threaded into `collect_trajectories`/`run`
  (polled every ~30 frames, raises `AutoCalCancelled`); `auto_calibrator_v2` passes
  `lambda: cancel_requested` and catches it → marks **cancelled**; frontend flips to
  "Cancelling…" via new `_autoCalCancelling` flag and stops the poll race.

### #11 — App ran detection on CPU, never the iGPU (~3.5×)  — FIXED ✅
- **Symptom:** live "Confirm & process" crawled at **0.447 fps** (ETA ~44 h/segment).
- **Root cause:** `start_server.py` sets no `DEVICE`; `detect_device("auto")` only
  ever returned `cuda`-or-`cpu` — `openvino` was opt-in via `DEVICE=openvino`. CLI
  `reprocess` scripts pass it; the interactive app does not. So every app run used
  CPU on this CPU-only Intel laptop.
- **Measured:** `DEVICE=openvino` → **1.58 fps** (3.5×; matches documented ~3.7×).
  OV sees `['CPU','GPU']`; exports `yolo26s_openvino_model/.imgsz=960` and
  `yolo26l_openvino_model/.imgsz=1280` both match mode imgsz, load clean.
- **Fix:** `detect_device("auto")` now prefers **CUDA → Intel iGPU → CPU**
  (`_openvino_igpu_available()` helper). `detector.py`: an **auto**-selected iGPU with
  a missing export falls back to CPU with a warning; an **explicit** `DEVICE=openvino`
  still fails loud (preserves the anti-silent-stall contract). `test_device.py`
  updated (12 pass). Verified: plain `py start_server.py` now loads `intel:gpu`.
- **Caveat:** even at 3.5×, this 8 GB i5/Iris Xe laptop is slow — 30-min cache ~3.2 h,
  full day = multiple days. The iGPU is the only software lever; hardware is the ceiling.

### #10 — `build_bank_gtfree.py` is corridor-hardcoded, NOT new-site-ready — FIXED ✅ (2026-06-25)
**Fix:** both `build_bank_gtfree.py` and `apply_bank.py` now take `--project` (default
`97a7849a` to preserve corridor behavior) and derive the video start from the DB's
`videos.recording_start_datetime` instead of importing the corridor `groundtruth.VIDEO_START`.
The `groundtruth` import is gone from both. Added robustness guards (the rehearsal proved the
flow snags here): null `recording_start_datetime` → clear message + exit 2; missing detection
cache → clear "process this window first" message + exit 2 (point 3 below — no code removes the
iGPU time ceiling, but the failure is now actionable not cryptic); `apply_bank` warns when the
bank's embedded `project` differs from `--project`.
**Verified:** corridor cam3 bank rebuild is byte-identical to baseline (invariant: all 5 corridor
cams have `recording_start_datetime == 2026-05-12T00:00:02 == old VIDEO_START`); apply_bank measure
on cam3 retracks + writes 192 events end-to-end; `--project 0acb12c0 --camera 2` targets the
rehearsal DB (rec_start 2026-04-30) and hits the no-cache guard correctly. `build_bank.py` (the
GT/Miovision builder) is intentionally left corridor-bound — it is not part of the new-site flow.
Runbook §2 updated.

Original diagnosis (kept for reference):
The heart of the new-site procedure (runbook §2) cannot target a fresh project:
1. `PROJECT = "97a7849a"` hardcoded (line 56) for the DB path (122) + `parquet_path`
   (159); **no `--project` arg**. The documented `--camera 2 --minutes 30` would
   silently read the **Sunnyvale corridor** DB, not `0acb12c0`.
2. Imports `VIDEO_START` from the corridor `groundtruth` module (line 54) for the
   frame-range math (160-161) — wrong for any other video/date.
3. Requires a pre-built detection-cache `*.parquet` a fresh project doesn't have.
   The live pipeline writes one as it runs, but at ~1.58 fps (iGPU) a 30-min window
   is ~3.2 h.
- **Likely** `apply_bank.py` is similarly corridor-bound (verify).
- **Robust fix:** add `--project`; derive video start from
  `videos.recording_start_datetime`; drop the `groundtruth` import; document/produce
  the cache step. Then correct `new_site_runbook.md §2`.

### #9 — No pre-process validation (lets you run garbage) — OPEN GAP
"Confirm & process" only checks that trims exist. It happily started a run with
**invalid leg cardinals** AND **no path bank** → the pipeline burned CPU producing
~0 attributed events. Add a pre-process guard/warning: validate cardinals form a sane
set (opposing pairs, headings within tolerance of the cardinal) and warn when no
bank/suggestion exists for a camera. Surface in the Confirm dialog.

### #2 — Operator calibration was invalid — NEEDS OPERATOR FIX
Legs were labelled **W, E, S, SE** — no **North**, and a nonsensical diagonal **SE**;
`reference_heading`s didn't match the labels (the "W" leg pointed 144.5° ≈ SE). The
GT-free builder labels movements from cardinal pairs, so this would mislabel/drop
every movement and the leg-sanity QA would reject the bank. Per the cam1 incident,
bad cardinals poison naming + attribution + Excel join + the bank. **Must relabel to
proper N/E/S/W in the calibration UI before the bank step.**

## Conceptual clarification captured (channels vs paths)
- **Runtime classifier matches against `paths` only** (`pipeline.py` →
  `list_paths_for_camera`; Fréchet/DTW in `trajectory_classifier.py`). **Channels are
  never read at runtime.**
- **Channels are read only at bank-build time** (`build_bank_gtfree.py`): declare the
  movement set, label clusters by corridor containment, and provide `channel_fallback`
  polylines for movements the data didn't cover.
- So: **channel = coarse human prior (day-0, 3 clicks); path = precise data-derived
  reference the matcher consumes.** Drawing channels without running the builder does
  **nothing at runtime** — which is exactly why the rehearsal run produced ~0 counts.

## Gotcha re-confirmed: Playwright + native dialogs
Driving the app in the Playwright-opened browser freezes it: native
`confirm()`/`alert()`/`prompt()` are intercepted and queue silently (looked like a
"broken UI" twice). For a human-driven session, drive in a **normal browser** at the
same `http://127.0.0.1:5000` and leave Playwright for observation only. (Also, the
project list has stray Delete buttons that fire confirms easily — none were accepted.)

## Where we stopped / resume plan (tomorrow)
Server is running via plain `py start_server.py` (auto-iGPU). Open work, in order:
1. ~~**#10** — generalize `build_bank_gtfree.py` (+ check `apply_bank.py`) to `--project`
   + DB-derived video start.~~ **DONE 2026-06-25** (see #10 above).
2. **#2** — operator relabels cam 405051 legs to proper **N/E/S/W** + fix headings.
   Verify with leg-sanity. (Operator + Claude.)
3. Build a ~30-min detection cache on the iGPU (~3.2 h), run the generalized
   `build_bank_gtfree`, read `gtfree_bank_cam2_qa.json`, `apply_bank`.
4. Process the window → QA tab (single intersection = spot count carries the gate,
   aim ≥850 vehicles) → targeted review → export TMC Excel.
5. **#9** — add the pre-process validation guard. Then correct `new_site_runbook.md`.

## Code state
Uncommitted on branch `claude/accuracy-impl-2026-05-27`:
- `scripts/auto_calibrate.py`, `backend/services/auto_calibrator_v2.py`,
  `frontend/js/calibration.js` (finding #8)
- `backend/services/device.py`, `backend/services/detector.py`,
  `backend/tests/test_device.py` (finding #11)
Not yet committed — decide tomorrow.
