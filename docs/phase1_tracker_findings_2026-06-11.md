# Phase 1 — Tracker Recall & Association Upgrades: Findings (2026-06-11)

Plan: docs/implementation_plan_architecture_2026-06-11.md. Diagnostics: docs/phase0_diagnostics_2026-06-11.md.
All experiments: detection-cache retracks (apply_bank.py) scored with od_accuracy.py net/gross @30min,
07:00–07:30, vs shipped baselines 7.2 / 8.8 / 14.6 / 8.4 / 7.7 (cam1..5).

## Shipped: cam3 14.6% → 2.5% net (PM held-out: 19.2% → 7.1%)

Winning config (persisted as per-camera knobs on `cameras`, applied 2026-06-11, backup
`backups/20260512_pre_cam3_bank.db`):
- `calib_bbox_buffer_scale = 1.3` — buffered-IoU (1.3): boxes inflated 30% around their centers at
  the tracking input. Widens the association basin so 10 fps inter-frame displacement still
  overlaps; centers (= trajectories) unchanged. C-BIoU idea, implemented as input transform.
- `calib_tracker_activation_threshold = 0.15` + `calib_new_track_thresh = 0.18` — loosened birth
  (BoT-SORT high thresh + its separate birth gate).
- `calib_track_quality_filter = 1` — finalize-time gate (backend/services/track_filter.py): tracks
  with mean conf ≥ 0.25 always pass (strict-pipeline superset); low-conf births must travel
  (≥3 points, ≥80 px net displacement).

Verification: AM cells NB-thru 710/699, SB-thru 450/451 (near-exact); gross also fell 18.3→12.5
(not a net-cancellation artifact). PM (17:00–17:30, new pm1700 cache, 34 min iGPU build): shipped
config 19.2/21.4 vs winner 7.1/13.8 — generalizes across regime, unlike the magnet-gate incident.
LIVE corridor: cam1 7.2 / cam2 8.8 / **cam3 2.5** / cam4 8.4 / cam5 7.7.

## Sweep results (net/gross @30min)

cam3 grid (shipped 14.6/18.3): buf13 7.6/13.6 · birth010+tq 8.4/16.2 · ocsort 8.4/15.7 ·
birth015+tq 9.0/15.9 · buf12 8.1/13.3 · buf14 5.7/12.5 · birth010+buf13 11.9/16.8 (double-recovery
overshoot) · **buf13+birth015+tq 2.5/12.5** · ocsort+birth010 67.3 (clutter flood, rejected).

Hybrid A/B cams 1/4/5 (standard bytetrack-throughs + botsort-turns chain, ± buf13 on both):
- cam1: ctl 20.5 → buf 12.3. Big technique delta but the standard chain can't reproduce cam1's
  shipped 7.2 (older ReID-path events; resweep saw the same) → NO SHIP.
- cam4: ctl 12.6 → buf 20.5 — buffer HURTS (overcount camera; wider basins add errors) → NO SHIP.
- cam5: ctl 7.7 (reproduces shipped exactly) → buf 11.3 → NO SHIP.
- cam2: pure-botsort+buf 21.0 vs shipped hybrid 8.8 → NO SHIP (and Phase 0 already routed cam2's
  residual to attribution, not recall).

## Conclusions

1. **Buffered-IoU is a per-camera knob, not a global default.** Transformative where the failure is
   undercount-by-fragmentation/association (cam3); harmful where the failure is overcount (cam4/5).
   Matches the Phase 0 census exactly — use it where orphan clusters are high.
2. **Birth loosening and buffering recover overlapping populations** — combining at full strength
   double-counts (11.9); buffer first, then mild birth loosening (0.15/0.18), not 0.10.
3. cam3's residual (gross 12.5) is now per-minute timing noise comparable to the corridor's best.
4. Inline ID-stitching (`calib_track_stitch`, pipeline._stitch_remap) measured NET-HARMFUL on cam4
   pure-botsort (29.3 vs 25.3) — code kept, default off, revisit with stricter gates if needed.
5. OC-SORT (1.2): competitive standalone on cam3 (8.4) but dominated by buf13; with loose birth it
   floods (67.3). Throughs-tracker swap for cam1/4/5 hybrids not pursued — their chains are
   already at/near optimum and cam1's shipped state predates the chain.
6. Kalman-Q sweep (1.4): DEFERRED — boxmot/supervision don't expose Q; buffered-IoU addresses the
   same displacement failure mode and measured better than expected.

## New permanent machinery (all per-camera, default-off, UI-PATCHable)

- `cameras.calib_bbox_buffer_scale / calib_track_quality_filter / calib_new_track_thresh` —
  migrations, getter, setter, PATCH validation, resolve-defaults (database.py, intersections.py).
- `backend/services/track_filter.py` + pipeline hook (`n_quality_filtered` counter).
- Pipeline `_stitch_remap` (calib `track_stitch`, no DB column yet — experimental only).
- apply_bank.py sweep flags: `--activation --new-track-thresh --bbox-buffer --tq-filter --stitch`.
- diagnose_fast_misses.py `--db` to audit any retrack DB against the cache.
- evaluations/shipped_bank_cam{1..5}.json — shipped banks reconstructed from intersection_paths
  (the resweep scratch was gone; these make every shipped recipe re-runnable).
- cam3 pm1700 detection cache (held-out window, reusable for future cam3 validation).

## Notes for Phase 2

- apply_hybrid.py volume-gates turns with Miovision manual counts (`_bot_turn_keep_ids`) — ANOTHER
  ground-truth dependency the GT-free path must replace (alongside build_bank).
- cam3 orphan clusters 74 → 63: most of the win came from fragmentation repair, not orphan
  recovery; 11 birth-gate + 52 assoc clusters remain as cam3 recall headroom.
- Per Phase 0, cam2's −64 (attribution) and cam4's +87 (phantoms) are Phase 2 matcher / dedup work.
