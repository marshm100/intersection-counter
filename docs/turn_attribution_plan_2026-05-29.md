# Turn Attribution — Technical Implementation Plan

**Date:** 2026-05-29 · developed with Grok (read-only design review) · branch `claude/accuracy-impl-2026-05-27`
**Why:** Through attribution is solved (recal cut agg_err 126%→44%). Tracking was a real gap — OC-SORT (now wired) recovers ~2× the turn trajectories ByteTrack fragmented, so turn CURVES are captured. The remaining blocker is **turn ATTRIBUTION**: the recal emits no turn paths, so turns fall to the geometrically-broken `derive_movement` fallback (phantom SB-left 97 vs manual 0; NB-left 2 vs ~96). Capturing more turns made it worse (44%→54%) because more curves hit the broken fallback.

**NB — premise corrected:** the "manual counts" are Miovision (a CV tool) on the SAME 640×480 video. So turns ARE recoverable from this footage; this is an algorithm gap to close, not a camera/FOV limit. See memory `project_turn_parity_fov_limit` (FOV conclusion INVALIDATED).

## Core principle
Make the **joint scorer Tier-0 the source of truth for turns** by emitting complete `(origin_leg, destination_leg, movement_label)` turn-path rows. `score_path_joint` reads origin+dest+label straight off the matched path (origin override at pipeline.py:743) and never calls `derive_movement`. `derive_movement` becomes a **legacy fallback only** (cameras with zero paths). In a fully-calibrated camera, ~0% of attributed events should hit derive.

## Design (Grok-validated)
### 1. Exit-driven turn clustering (NOT origin-first, NOT start_xy)
Entries are truncated/unreliable; **exits/tails are reliable**. Cluster turn trajectories on the observed *suffix*:
- Feature vector (z-scored): `[end_xy (or last-3-pt centroid), tail_sin, tail_cos, 3–4 arclength-resampled points from the LATTER HALF only, observed net-delta / cumulative_curvature]`. Drop/down-weight `start_xy`.
- Start from the existing tail/axis grouping (`recalibrate_camera.py` `detect_axis` + rotation sense) to pre-split left/right/through and avoid the NB-left↔SB-through conflation.
- Cluster with Ward `linkage`+`fcluster` (or `dbscan_like` on exit position then shape). Per cluster: `_fit_mean_polyline` on **observed points only** (do not hallucinate a prefix back to the origin).

### 2. Destination leg — from the reliable tail
`destination_leg_id` = nearest leg origin to the cluster's end centroid, gated by expected exit direction from intersection center (~30° tol). This is the trustworthy signal.

### 3. Origin leg + movement label — manual count-match + rotation-sense feasibility
- Primary: **manual TMC weak supervisor** (same overlap-scaled count logic the through path already uses). Once dest is known, manual gives the origin breakdown for traffic exiting that leg; assign by support (greedy/linear-sum), cost `-count` if feasible else `+inf`.
- Feasibility check (not sole decider): cluster's earliest observed bearing + rotation sign (cross product) must be compatible with leaving the candidate origin toward the known dest (origin `reference_heading` + 60–90° turn sector).
- **Never** use back-projection (tried + reverted — memory `project_bug_a_backward_extrap_failed`) or the truncated entry tangent for the label.

### 4. Emit + apply
Emit real rows `(origin_leg_id, destination_leg_id, movement_label, polyline=observed median, supporting_count, source="data-driven")`. Apply via existing `apply_recal_updates.py` (already atomic + verified-backup; it skips only `dest=None`, so populated dests apply fine).

### 5. OC-SORT overcount control (it produced 1461 vs manual 1211)
- Tune OC-SORT kwargs (`inertia`, `delta_t`, `min_hits`, `max_age` in `tracker.py` OcSortBackend) on a short window until total count is within ~5–8% of baseline/manual — trim over-generation at the source; keep the 2× turn recovery.
- Two cheap post-attribution quality filters: (a) a `left/right` label requires stricter `min_path_distance` (~120px) / min cumulative curvature than `through` (real turns have observable arc); (b) when the best path's label is a turn, require a higher `tail_prior` floor in the joint scorer (bias against labeling a straight stub as a turn).

## Validation gates (before any apply — all use existing harnesses)
1. **Self-consistency:** restrict the bank to each emitted turn path, re-run `score_path_joint`; recover ≥80–85% of its supporting_count at cost <30, coverage >0.35.
2. **Manual parity** (`per_movement_accuracy` + `replay_attribution_changes --joint`): every turn cell `|Δ| ≤ max(3, 0.25×manual)`; **zero phantoms** (manual <1 but ours >3); agg_err must not regress vs the arterial-only baseline.
3. **Geometric sanity:** emitted polyline's final-segment tangent within 25° of cluster median tail; tail within 30° of expected exit dir (center→dest origin).
4. **Volume sanity:** Σ supporting_count / qualifying trajs ≥ ~0.65.
5. **Engineer visual gate** (mandatory): overlay new turn polylines (colored by label) + sample raw trajs per cluster on real frames; engineer confirms the median follows visible tire paths and the claimed origin is plausible.
6. **Apply-time regression** (`test_recal_effect` + reprocess-from-cache): per-cell + agg_err must improve (or ≤ +2pp); any new phantom or >15–20% relative worsening blocks promotion.
7. **Production monitor** (first full day): total within 10% of 7-day median; any turn cell >40% rel error vs historic/sibling forces alert + temporary derive fallback for that camera.

## Honest ceiling
The most truncated movement (NB-left) is still the hardest; camera + detection latency caps it. But this stops attribution from being the *amplifier* — turns whose curves OC-SORT captures will attribute correctly, and the rest are bounded + surfaced, not silently mislabeled.

## Build order
1. Extend `recalibrate_camera.py`: exit-driven turn clustering + dest/origin/label assignment + emit real turn rows (keep through logic).
2. OC-SORT kwargs tuning on the 30-min cache (target total within ~5–8%).
3. Quality filters (config + joint scorer / finalize).
4. Validation gates (extend `recalibrate_viz.py` + `test_recal_effect.py` + a self-consistency check).
5. Measure end-to-end (OC-SORT + turn-inclusive bank) → iterate to parity → engineer visual gate → apply.
