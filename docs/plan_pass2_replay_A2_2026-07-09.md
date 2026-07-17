# Plan — A stage 2: pass-2 replay service + parity gate (2026-07-09)

The core of the two-pass productization (plan_twopass_productize_A_2026-07-09).
Deliverable: a backend service that turns a v2 raw-track dump + the camera's
live calibration/bank into `vehicle_events`, and the measured proof that this
path loses nothing against the retrack path. No UI wiring (stage 3), no ingest
trigger (stage 3), no turn-merge (see scope note).

## Grounding facts (verified in code today)

- **The chain** (`pipeline._finalize_vehicle_data`): track-quality gate (calib)
  → `classify_trajectory` (calib angle thresholds) → `score_path_joint` (incl.
  per-camera `cost_metric` pin, e.g. cam3=dtw_mean) → fallback scorers →
  `_write_vehicle_event`. All knobs flow from `get_camera_calibration_params`
  — the replay gets them identically for free.
- **Vehicle-dict inputs the replay must reconstruct per track:** trajectory
  ([x,y] per frame), per-point confidences (the quality gate consumes them),
  provisional `origin_leg_id` (assigned DURING tracking in live runs — the
  replay re-runs the same origin-assignment logic over the dump in frame
  order), `reference_heading` (leg-derived), per-point class votes → vehicle
  class. **Dump v2 carries all of it** (cx, cy, conf, class_id, bbox size for
  the articulated post-pass).
- **Precedent:** `replay_fullchain.py` already instantiates the real
  ProcessingPipeline with no YOLO/tracker and drives `_finalize`-level
  re-attribution with `_write_vehicle_event` captured. A2 productizes that
  pattern, fed from dumps, writing real events.
- **No camera's live table contains hybrid-combine products** (zero
  `vehicle_track_id=-999` rows corridor-wide) — live tables are plain
  pipeline/retrack recipes, so a replay of that same recipe is the right
  parity reference.
- **Pre-registered parity suspect #1:** the live recipe applies per-camera
  pre-track NMS; `dump_raw_tracks` does not. Corridor blast radius: cam2 only
  (`calib_pre_track_nms_iou=0.85`; all other cams None). The cam2 v2 dump was
  therefore tracked on un-NMS'd detections and does NOT match its live
  tracking input.

## Stage 0 — dumper NMS parity + cam2 re-dump

`dump_raw_tracks` applies `calib_pre_track_nms_iou` to each frame's detections
before `be.update(...)`, mirroring the live/retrack path (reuse the same NMS
helper the pipeline uses — no new implementation). Re-dump cam2 study_0700.
Cams 1/4/5 dumps stay valid (no NMS knob).

## Stage 1 — the replay service (`backend/services/pass2_replay.py`)

`replay_camera(project_id, camera_id, *, variant, start_frame, end_frame,
out_db) -> stats`:
1. Load the dump; group rows by track_id; order by frame.
2. Per track, rebuild the vehicle dict: trajectory + confidences + class votes
   (mirror the live vote rule exactly — read it from pipeline, don't invent),
   origin via the pipeline's own origin-assignment logic replayed point-wise,
   reference_heading from the origin leg.
3. Drive the real `_finalize_vehicle_data` with `_write_vehicle_event`
   redirected to the out-db writer (crossing-timestamped — the pipeline's own
   convention). Vehicle class → FHWA → articulated size post-pass (existing
   `articulated.py` service).
4. Emit run stats (tracks in, events out, drop reasons) — the same counters
   the live pipeline logs, so tier-1 diffs are attributable.
No video decode anywhere; the whole camera-window replays in minutes.

## Stage 2 — the parity gate (two tiers, pre-declared)

- **Tier 1 (HARD, the actual gate): replay-from-dump vs retrack-from-cache.**
  Same camera, window, bank, backend, knobs — `apply_bank` produces the
  reference DB; per-cell tables must agree |Δ| ≤ 2 vehicles/cell per 2 h, no
  acceptance-verdict flips. This isolates the dump+replay MECHANICS; inputs
  are identical by construction. Failure = hidden statefulness; pre-registered
  suspects, in order: pre-track NMS (stage 0), origin-assignment timing
  (mid-track reassignment the replay orders differently), `recently_lost`
  coasting finalization, track-filter confidence provenance. Investigate,
  never tune past.
- **Tier 2 (context, NOT a gate): replay vs the live shipped tables** + the
  acceptance metric, per camera. Documents drift from each camera's recipe
  history; feeds the stage-3 switchover decision. Expected ≈0 where live was a
  plain recipe run (the cam2 bank-session precedent: arm A matched live
  exactly).
- Run order: cams 1/4/5 (10 fps, no NMS) → cam2 (post stage-0). cam3 joins
  when its full-day v2 dump lands (overnight job); it does not block the gate
  on the other four.

## Scope note — turn-merge

The live tables carry NO hybrid turn-merge today, so A2 replays WITHOUT it —
parity is against what actually ships. The production combine (+ S5 emitter,
+ the blind bank gate) enters in stage A4 as its own gated change on top of a
parity-proven base. One variable at a time.

## Out of scope

UI/ingest wiring (stage 3), QA hooks (stage 4), tracker/knob changes, cam3
full-day re-dump (background), any accuracy improvement — A2's bar is
FIDELITY, not accuracy.

## Risks

- Origin assignment in live runs sees per-frame leg-zone state; if its replay
  ordering diverges, tier 1 catches it immediately (it is suspect #2).
- The dump's tracker is deterministic on identical input (verified today:
  v2 re-dump reproduced v1's box-clip output byte-for-byte), so tier-1 noise
  should be ~zero; the ≤2/cell tolerance is for float/ordering slop only.
