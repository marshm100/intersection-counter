# Plan — Workstream A: productize the two-pass flow (2026-07-09)

MASTER_PLAN §4 item 5 / §3-A. Goal: an operator runs a study start-to-finish in
the app — no CLI, no Claude. Pass 1 (heavy, semantics-free) runs unattended at
ingest; pass 2 (all semantics) is a minutes-long re-runnable step behind
"Confirm & process". Every mechanism named here already exists and is
validated; this workstream is WIRING, not research.

## A0 — the counter decision (post-Gate-B, recorded up front)

Pass 2's counter is the EXISTING production classification chain — provisional
origin → `classify_trajectory` → `score_path_joint` → fallbacks — replayed over
pass-1 raw tracks. `scripts/replay_fullchain.py` already drives exactly this
chain offline with no YOLO/tracker loaded; pass 2 productizes that approach fed
from the raw-track dump instead of stored events. Box-clip is NOT the counter
(Gate B) and appears nowhere in the counting path; its role stays QA-only.
The turn-merge volume gate uses bank `supporting_count` (the blind gate,
validated 2026-07-08: cam1 10.0% vs 6.7% GT-gated — the accepted honest cost).
Miovision appears nowhere.

## A1 — pass 1 at ingest (calibration-independent)

- **Trigger:** per trim segment, as soon as a card's trims + videos are known —
  before calibration exists (pass 1 needs none). Each trim edge-padded ~90 s
  (time-based; cams run 10–25 fps) so boundary vehicles aren't truncated.
- **Work per segment:** detection → the existing cache writer (already live),
  then tracking → the raw-track dump (`dump_raw_tracks` logic, live-parity
  ByteTrack + the camera's persisted calib knobs).
- **Dump schema v2 (the one real gap):** today's dump stores (track_id, frame,
  cx, cy) — enough to count, NOT enough to classify vehicle class or run the
  articulated size post-pass. Extend rows to (track_id, frame, cx, cy, bw, bh,
  conf, class_id), bump the format tag, keep the memmap-stream pattern.
  Existing corridor dumps are v1: re-dump is tracking-only cost (detection
  caches are retained), run as a background job when needed.
- **Job model:** the overnight pattern — background task with progress into
  `v3_run_state`, resumable/idempotent per (content_hash, variant, window);
  skip when the dump already covers the window.

## A2 — pass 2 behind "Confirm & process" (minutes, re-runnable)

1. Bank build pooled over the FULL corpus (`build_bank_gtfree` logic over all
   trims' dumps — rare cells finally have data; drawn-direct channels included,
   which also closes S4-class holes at the source).
2. Replay every dumped track through the production finalize/classify chain →
   `vehicle_events` (crossing-timestamped — the existing pipeline convention),
   vehicle class from dump bbox/class fields + the articulated size post-pass.
3. Turn-merge with bank expecteds (the production combine), then write events +
   `intersection_paths` atomically per camera with a project.db backup — the
   established apply pattern.
- Operator relabels a cardinal / redraws a channel → re-run pass 2 ONLY
  (tracking is never repaid). Surface as a "Re-run counting" action.

## A3 — QA hooks in the flow

Post-pass-2, automatically: `rebuild_flags` (S1/S2/S4 feeders), the S5
borderline emitter (`hybrid_ocbot.borderline_merge_cells` — computed at the
combine, now writable to `review_flags` since pass 2 IS the combine layer), and
the export gate (already wired) reads the result. This closes the S5 deferral
from the flag-queue plan.

## A4 — UI

Card-level ingest status (pass-1 queued/running/done per trim), "Confirm &
process" runs pass 2 with progress, "Re-run counting" after calibration edits.
No new screens — states on the existing card + processing views.

## The gate (before the product flow switches over)

**Parity regression:** pass-2 replay over pass-1 dumps must reproduce each
corridor camera's LIVE per-cell table (the bank-session evidence pattern —
cam2's arm A matched live exactly). Tolerance: per-cell |Δ| ≤ 2 vehicles per
2 h window, no verdict flips on the acceptance metric. Any camera failing
parity blocks the switchover — investigate, don't tune.
**First real exercise:** the cam2 full-day reprocess through the new flow
(also restores cam2's full-day events and lets S1 re-verify T1 honestly).

## Stages (shippable order)

1. Dump schema v2 + re-dump job (A1 payload) — script-level, testable alone.
2. Pass-2 replay service + parity gate on the corridor (the core).
3. Ingest wiring (A1 trigger + job model) + A4 states.
4. A3 QA hooks + S5 emitter + cam2 full-day run.

## Out of scope

Tracker/knob changes (§2b's GT-tuned-knob concern is recorded, not addressed
here); box-clip anything; ReID; the fine-tune; flood-control stages (separate
plan, can land before or in parallel).

## Risks

- **Replay fidelity:** the finalize chain has per-track state (buffers, NMS);
  replay_fullchain proves drivability, the parity gate proves fidelity — if
  parity fails, the discrepancy is itself a finding (live-vs-replay divergence
  = hidden statefulness).
- **Ingest compute:** full-trim tracking is hours on CPU per camera-day — but
  unattended, once, and detection caches make re-runs tracking-only.
- **Dump storage:** v2 rows are ~2× v1; still MBs per camera-window (vs the
  ReID sidecar's hundreds of MB) — no constraint.
