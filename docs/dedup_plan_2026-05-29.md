# cam1 Over-Tracking Fix — Plan (Grok-validated, 2026-05-29)

**Context:** After the 180° leg-label fix, cam1 sits at 26.8% net / **35.7% per-minute gross** vs Miovision per-minute OD. The dominant residual is OC-SORT **over-tracking** (we adopted OC-SORT for 2× turn recovery; its cost is duplicate/fragmented track-IDs that each become a counted event — there's no per-vehicle dedup between tracking and counting). Errors:
- SB-through (eastbound) 530 vs 425 (+105) — over-tracking
- NB-left 149 vs 96 (+53) — duplicate turn tracks
- NB-right 52 vs 1 (+51) — NB-through **fragments** ending mid-arterial, mis-attributed to a cross-street turn

**Key established fact (frame-aligned, cache-replay):** only **simultaneous-overlap** duplicates (two IDs co-located ≤35px for ≥5 shared frames) are an unambiguous, safe merge — and they're only ~30% of the over-count. **Sequential merging cannot be done safely**: `dedup_ceiling.py` shows a monotonic slide (overlap 533 → seq-tight 501 → seq-loose 443 → aggressive 334) with no knee — any threshold aggressive enough to reach manual eats real close-followers (undercount). No ReID/appearance (OC-SORT is appearance-free), and kinematic signals don't separate a fragmented continuation from a 1-2s-headway follower on a dense 640×480 arterial. **So: don't stitch sequentially. Prevent fragments at the source + reject bad attributions geometrically + collapse only the physically-impossible overlaps.**

## Ranked implementation order
1. **OC-SORT knob sweep (reduce fragment production at the source).** Extend `ocsort_knob_sweep.py` to sweep `use_byte / det_thresh / inertia / delta_t / min_hits / max_age`, measuring per-minute GROSS + the WATCH cells + NB-right phantom + total-count sanity, AND requiring NB-left (turn recovery) preserved. Highest leverage on SB-thru +105 / NB-left +53. (NB: an earlier det_thresh sweep on *mislabeled* cells looked like a band-aid; re-evaluate honestly on corrected labels + gross.)
2. **Strengthen the turn gate (fixes NB-right +51 cheaply, robustly, geometric — not identity).** In `score_path_joint`: raise `JOINT_SCORER_TURN_MIN_COVERAGE` 0.40→0.50-0.55 for turn paths; add a min-turn-arc / lateral-deviation term (matched sub-curve must show real perpendicular deviation from the arterial axis). In `pipeline._finalize_vehicle` after the joint match: if movement∈{left,right,uturn} but the trajectory's net-heading / cumulative-curvature is below the turn threshold, re-score restricted to through paths (or reject as fragment). Kills the short-westbound-stub-claims-a-turn case at the root.
3. **Overlap-only ID remapper** inside `VehicleTracker`/`OcSortBackend` (only if 1+2 leave residual). Per-frame: union-find merge track-IDs co-located ≤35px for ≥5 shared frames → remap younger→canonical, persistent table in get/load_state. Thin, stateful, unambiguous (physics). Collapses the ~30% simultaneous duplicates. Pipeline contract unchanged.
4. **Hybrid dual-tracker** (ByteTrack throughs + OC-SORT turns) — ESCALATION ONLY if 1-3 can't close it. Run both on the cached detections; throughs from ByteTrack (already ≈manual), turns from OC-SORT; narrow cross-backend overlap-dedup at the boundary (movement classes disjoint → low false-merge risk). Adds dual-state/checkpoint complexity.
5. **Never ship** loose sequential tracklet stitching (scene-specific band-aid; violates robust-fix requirement).

## Validation (per-minute GROSS, not net)
- Target: gross ≤ 12-15% (from 35.7%) on the 07:00 30-min window **and one disjoint later window**; NB-right phantom ≤3-5 absolute; SB-thru within ~5-8%; NB-left within ~10% (preserve 2× recovery).
- Loop (all cache-retrack, minutes): knob sweep → `od_accuracy.py --show-od` per config; gate changes → retrack → od_accuracy; overlap-dedup → `dedup_ceiling.py`/`measure_dedup.py` as ceiling oracles then real end-to-end.
- Regression: every config also run `backend=bytetrack`; ByteTrack numbers must not move.
- Path-quality audit: log chosen path coverage/cost/tail_prior per event; flag turn events with coverage <0.38.
- Mandatory engineer visual gate on the exact failure frames (SB queue duplicates; NB-right phantom tracks) before any production apply.

## Honest ceiling
Overlap dedup + gates + knob-tuning are root-cause and robust, but they will NOT fully reach manual on the throughs (the residual over-count is sequential fragments we refuse to merge unsafely). The remaining gap is bounded + surfaced, not papered over. If parity is required, the hybrid (item 4) is the escalation; the cross-street missing turns (EB-left/right) are detection-bound (separate recall/GPU lever).
