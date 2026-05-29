# Handoff: Turn-attribution accuracy work — intersection-counter

> Paste-ready handoff for a fresh session. Last updated 2026-05-29, branch
> `claude/accuracy-impl-2026-05-27`, commit `0004461`.

## Goal
Close the per-movement TMC accuracy gap for the Sunnyvale corridor, project
`data/projects/97a7849a`, camera 1 (NBeltLineRd-NorthwestDr). Target = the
Miovision study counts.

## READ FIRST (memory)
- `project_turn_parity_fov_limit` — ⚠ its top says the FOV conclusion is
  INVALIDATED; read the UPDATE / BUILD-PROGRESS sections, they hold the live state.
- `project_detection_birth_gate_truncation`, `feedback_robust_production_fixes`,
  `feedback_diagnostic_style`, `feedback_data_driven_over_rules`,
  `project_put_legs_wipes_events`, `project_gpu_openvino_deferred`,
  `user_hardware_constraints`
- `docs/turn_attribution_plan_2026-05-29.md` — full design (developed with Grok).

## Corrected premise (do NOT relitigate)
The "manual counts" were produced by **Miovision (a CV tool) on the SAME 640×480
video**. So the turns ARE recoverable from this footage — the gap is OUR
detection+tracking+attribution algorithm, NOT the camera/FOV. Do not propose
multi-camera / "route turns to review / refuse to count" — that was a wrong turn
we already corrected. Robust, root-cause fixes only (no band-aids).

## Where we are (validated)
- Root cause of turn loss = ByteTrack (IoU-only) FRAGMENTING turning vehicles.
  OC-SORT recovers ~2× turn trajectories from identical detections.
- OC-SORT wired: `backend/services/tracker.py` `OcSortBackend` (registered
  "ocsort"); pipeline has `tracker_backend=` param. boxmot installed
  (lazy-imported). NB: boxmot downgraded pandas 3.0.1→2.3.3 (tests still green).
- Exit-driven turn-path derivation: `scripts/recalibrate_camera.py`
  `derive_turn_paths` (signed-curvature turn/through split; exit-suffix Ward
  clustering; destination by tail→leg bearing; origin+label by manual TMC
  count-match). Emits real (origin,dest,label) turn rows.
- Strict turn gate in `score_path_joint` (config `JOINT_SCORER_TURN_TAIL_PRIOR_FLOOR`
  =0.85, `JOINT_SCORER_TURN_MIN_COVERAGE`=0.40).
- **RESULT: agg_err 138% → 40.5%** (BELOW the 44% baseline) with NB-left
  recovered (109 vs manual 96). The 40.5% bank = `evaluations/recal_cam1_nbleftonly.json`.

## Current data/cache state
- DEFAULT_VARIANT cache (`balanced_960_skip1.parquet`) = the 30-min balanced
  detection cache (frames 251980–269980, 07:00–07:30). Backups: same dir with
  `.balanced30min_*.bak`. (An accurate yolo26l@1280 3-min cache was built then
  overwritten; rebuild via `reprocess_camera --mode accurate` if needed.)
- Project DB currently holds OC-SORT 30-min retracked events (~1525). DB backups
  in `data/projects/97a7849a/backups/` (`pre_widewindow_*`, `pre_accurate_*`, …).
- `data/`, `*.db`, `screenshots/*` are gitignored.

## Measurement harness (cheap — retracks from cache, no YOLO)
- End-to-end agg_err: `py scripts/test_recal_effect.py --suggestion <bank.json>
  --start-hms 07:00:00 --minutes 30 --activation 0.25 --tracker-backend ocsort`
- Regenerate DB events with a backend: `py scripts/retrack_to_db.py --backend
  ocsort --start-hms 07:00:00 --minutes 30 --yes`
- Build a turn-inclusive bank: `py scripts/recalibrate_camera.py --out <bank.json>`
- Tracker A/B: `scripts/tracker_compare.py`; detection-vs-tracking:
  `scripts/detection_vs_tracking_probe.py`; recall: `scripts/validate_recall.py`

## Remaining roadmap (multi-cycle tuning, by ROI)
1. **OC-SORT OVERCOUNT (biggest lever):** total 1458 vs manual 1211; SB-through
   631 vs 424 (OC-SORT-specific — ByteTrack got 412). Two knobs:
   - (a) turn-specific stricter min-track-length filter (loose
     `TRAJECTORY_MIN_POINTS=5`/`MIN_DISTANCE_PX=50` admits short spurious tracks;
     don't globally raise — would drop legit short throughs);
   - (b) OC-SORT `use_byte=False` / higher `det_thresh` (likely spawning
     duplicate through tracks). NOTE: `min_hits`/`use_byte`/`det_thresh` are
     `OcSortBackend` defaults, NOT yet threaded through `VehicleTracker` — thread
     them to tune.
   - min_hits sweep (30-min, substantial tracks/turns): 2→1162/221, 3→1024/199,
     5→796/169.
2. **CROSS-STREET EB/WB turns:** `derive_turn_paths` mis-derived them (count-match
   force-fit arterial-ish clusters to EB cells; their tails are arterial-aligned
   so they over-attribute — EB-right 245 vs manual 36). Need a GEOMETRIC
   feasibility check (cross-street legs L24/L25 still have stale headings —
   recalibrate them first) instead of pure count-match. SB-right (34) also missed.
3. Then the plan's **validation gates** (self-consistency, manual parity / zero
   phantoms, geometric sanity, volume) + the **MANDATORY engineer visual gate**
   before any production apply.

## Apply (when ready, gated on engineer visual review)
`scripts/apply_recal_updates.py --apply` (atomic, makes a verified VACUUM-INTO
backup first, heading-only legs + full path replace). **NEVER** use
`PUT /calibration/legs` to apply — it deletes `vehicle_events` (see memory
`project_put_legs_wipes_events`).

## How we work here
Diagnostic-first, data-driven, robust fixes. Design/verify with Grok via the CLI:
`"C:\Users\onkar\.grok\bin\grok.exe" --permission-mode plan --no-alt-screen -p "<prompt>"`
(read-only plan mode; do NOT pass `--effort` — grok-build rejects it).

**START BY:** confirming the 40.5% baseline reproduces
(`test_recal_effect.py --suggestion evaluations/recal_cam1_nbleftonly.json
--tracker-backend ocsort --minutes 30`), then tackle roadmap item 1 (OC-SORT
overcount).
