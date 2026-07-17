# Recalibration — Technical Implementation Plan (Phase 3)

**Date:** 2026-05-27 · developed with Grok · for branch `claude/accuracy-impl-2026-05-27`
**Why:** Diagnostics proved the accuracy bottleneck is leg/path **calibration**, not the scorer
(see `implementation_plan_accuracy_2026-05-27.md` Phase 3). This plan rebuilds the leg defs +
path bank data-drivenly from the regenerated trajectories, using only the **reliable** signals
(tails for direction; shape + manual counts for labels), since entries are confounded by the
mid-turn-entry problem and the current `reference_headings` are wrong.

## Design principles
- **Never** trust current `reference_heading`s or entry headings for decisions. Use **tails**
  (`_exit_velocity`) for direction.
- Re-derive origins from **start points only** (decouples from the broken end-snapping that
  produced 35 phantom L22→L22 u-turns).
- **Label-free shape clustering** (feature-vector + Ward); DTW reserved for quality/scoring.
- **Manual TMC counts are the weak supervisor** for labels (count-match + tail feasibility), not
  geometry — until the headings are fixed.
- Flow through the existing **suggestion → review → apply** path (reversible, auditable); do not
  write `legs`/`intersection_paths` directly.
- **Engineer visual gate is mandatory** (data signal has residual noise on thin samples).
- Prototype on the cheap 113-event bucket; build the production bank from a larger window.

## Artifacts (new code, reusing existing helpers heavily)
- `scripts/recalibrate_camera.py` — steps 1–3; emits a suggestion JSON (auto_cal schema +
  a new top-level `updated_legs: [{leg_id, origin_point, reference_heading}]`), optionally via
  `save_calibration_suggestion`. Does NOT write legs/paths directly.
- `scripts/recalibrate_viz.py` — the mandatory overlay (see gate 4).
- small extension to `scripts/apply_auto_cal.py` (or `apply_leg_updates.py`) to apply the
  `updated_legs` section via the existing `PUT /calibration/legs` logic; paths via `upsert_path`.

## Step 1 — Re-derive leg origins + headings from tails
- Spatially cluster **start points only** (`auto_calibrate.dbscan_like` single-linkage, eps≈40–60)
  → origin blobs; `origin_point` = median of blob starts.
- Per blob, `reference_heading` = circular median of member **tail** headings (`_exit_velocity`).
- Attach approach NAMES (SB Belt Line, …) to blobs by nearest manual-study anchor position
  (weak prior, same as the 2026-05-22 remap); engineer can override on the viz.
- **Gate:** re-snap events with the new origins → L22→L22 u-turns drop from 35 to <~10; observed
  tails within ~25° of new headings for dominant flows.

## Step 2 — Label-free shape clustering
- Feature per trajectory (clustering only): `[start_xy, end_xy, 4 arclength-resampled mids,
  tail_sin, tail_cos]` (~14-dim; z-scored). `extract_shape_features(traj)`.
- `scipy.cluster.hierarchy.linkage` (Ward) + `fcluster` at K (fixed 10–12; sweep 6–15 +
  silhouette on the prototype).
- Per final cluster: median polyline via `_fit_mean_polyline`, count, median tail heading,
  start/end centroids. Drop clusters with support < 8–10.
- **Gate:** top 3–4 clusters per major origin explain >70–80% of its volume; coherent on viz.

## Step 3 — Per-origin assignment (clusters → movements)
- Per named origin O: clusters `c_k` (count, tail `h_k`) vs manual vector `M_O`
  {thru,left,right,uturn} for the window.
- Feasibility sectors: expected tail direction per movement from the approach's rough geometry
  (intersection center ≈ (330,285) from the fixture), ~60–70° tolerance. A cluster may only take
  a movement whose sector contains `h_k`.
- Solve with `scipy.optimize.linear_sum_assignment`: cost = `-count` if feasible else `+inf`;
  soft-match the per-movement marginals to `M_O`. (Greedy desc-by-count also works on the tiny
  matrix.) Largest cluster → largest manual movement (L22's ~40-cluster → thru=37).
- Output: (origin_leg, movement) → median polyline(s) + summed support + label.
- **Gate:** assigned per-(origin,movement) within ~15–20% of manual for dominant cells; no
  assignment with tail >70° off its sector; agg_err improves vs the derive_movement version.

## Step 4 — Mandatory engineer visual gate (`recalibrate_viz.py`)
Overlay on a real 7:00 frame: current leg origins + heading arrows (flag if off); the K dominant
shape-clusters as thick polylines colored by tail heading, annotated with counts; faded sample
trajectories; side panel with manual counts + assigned labels + (for contrast) old
`derive_movement` labels. **Success:** engineer confirms the dominant polylines follow the visible
vehicle paths and counts match the manual study's relative sizes.

## Step 5 — Emit + apply
Apply `updated_legs` (PUT /legs logic) + upsert the new labeled paths (`source="data-driven"`,
real `supporting_count`); clear old count=0 rows. **Gate:** `per_movement_accuracy.py` +
`replay_attribution_changes.py --joint` on the window — joint now ≥ legacy; L22 dominant flow
labeled thru.

## Step 6 (optional) — Full-peak production bank
Reprocess full AM/PM peaks (cache write-through), rerun steps 1–5, snapshot new B0/B_joint.

## Sequence & effort
- **Day 0 (2–4 h):** implement `recalibrate_camera.py` (steps 1–3) + `recalibrate_viz.py`; run on
  the 113-event bucket; iterate thresholds/K until gates 1–4 pass.
- **Day 1 (4–8 h + one reprocess):** reprocess a larger window; rerun; visual gate; extend
  apply; apply; measure; snapshot.
- **Total ~6–12 engineering hours** + reprocess runs + ~15–30 min engineer review. All heavy
  lifting reuses the median fitter, DTW subsequence, clustering, snapping, and apply code.

## Risks
- Thin samples on rare movements → min-support filter + legacy fallback.
- Origin→approach auto-mapping wrong → caught + overridden at the visual gate.
- Tail-feasibility sector has mild circularity → bootstrap from data / cardinal priors; dominant
  flows are unambiguous so it's robust where it matters.
- This unblocks the joint scorer + OC-SORT, which only pay off on correct geometry.
