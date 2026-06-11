# Macro Implementation Plan — New-Site Accuracy Architecture

**Date:** 2026-06-11
**Source research:** docs/architecture_research_2026-06-11.md (verdict: architecture sound; bank
bootstrapping, tracker motion model, and conservation QA are the levers; ≤5% fully-automated exceeds
published SOTA — plan for automation + brief human review).
**Goal:** Every NEW intersection — zero Miovision data — lands at ≤5% net error per movement at
15–30 min aggregation after a short, bounded human review pass; processing stays viable on the
i5-1135G7 / Iris Xe / 8GB target machine.

---

## Guiding principles (standing rules, restated as plan constraints)

1. **Measurement-first.** Every candidate change ships behind an A/B measured with
   `scripts/od_accuracy.py` (net@15/30min) on the Sunnyvale corridor before it becomes a default.
   Non-destructive side DBs (the `apply_bank.py` / `overnight_corridor_resweep.py` pattern); nothing
   touches project.db without the measure → review → `--apply` gate.
2. **The corridor is the lab, but the deliverable is the new-site path.** Miovision exists only on
   the corridor; each phase must state how its feature behaves when Miovision is absent.
3. **Root-cause fixes only** — no band-aids (standing feedback).
4. **Recorded-video advantage.** We are not live. Offline/two-pass methods (post-hoc track filtering,
   tracklet stitching, re-pass) are always on the table and usually free.
5. **Hardware ceiling.** No heavy ReID; nothing that doesn't run OpenVINO/CPU. Throughput target:
   an intersection-day must still process overnight on the target laptop.

---

## Phase 0 — Diagnostics & ground truth for the plan itself (≈1–2 days)

Cheap, answers which Phase 1 items matter most. No production changes.

**0.1 Frame-cadence audit.** Resolve the `DEFAULT_FRAME_SKIP = 3` (backend/config.py:14, flows in
from routers) vs `accurate` mode `detection_skip=1` (config.py modes) ambiguity: instrument
`ProcessingPipeline.process_video()` (backend/services/pipeline.py:277–395, skip check at :328) to
log effective detection fps, and confirm what real production runs (v3 orchestrator path AND legacy
router path) actually used. If any production path runs fast-mode skip on 25 fps sources, that alone
explains a class of fast-vehicle misses.
*Deliverable:* one-page finding; if a path silently runs skip=3 in accurate mode, fix is Phase 1.0.

**0.2 Fast-vehicle raw-detection dump.** New `scripts/diagnose_fast_misses.py`: replay a clip window
through `VehicleDetector` only (no tracker), dump all boxes ≥0.05 with scores per frame; overlay on
frames for 5–10 known missed fast vehicles (user supplies timestamps from footage they've seen).
Reuse `backend/services/detection_cache.py` where a cache already exists.
*Decision rule:* boxes exist at 0.08–0.25 across the transit → birth/association failure → Phase 1
is the fix. No boxes at all → detection failure → escalate Phase 5 (detector work) from optional to
required.

**0.3 Truncation/recall census.** Extend `scripts/audit_detection_vs_association.py` to bucket every
ground-truth-relevant miss (vs Miovision per-minute OD) into: never-detected / detected-never-tracked
/ tracked-misattributed / tracked-misclassified. This is the denominator for all Phase 1–2 wins.

**Gate to proceed:** the census tells us the expected ceiling of each later phase; re-rank Phases
1–2 sub-items by bucket sizes before starting.

---

## Phase 1 — Tracker recall & association upgrades (≈1–2 weeks, the measured headroom)

All items run as offline retracks on the detection cache (the `apply_bank.py` retrack pattern), so
YOLO never re-runs during sweeps. Score each vs net@15/30min; ship per-camera or as mode defaults via
the existing precedence chain (per-camera `calibration` DB override > constructor arg > config
default, backend/services/pipeline.py:251–266).

**1.0 Frame-cadence fix** (if 0.1 found a skip path): force every-frame detection for processing
runs; if compute-bound on 8GB targets, drop imgsz before frames (research: association is the
frame-rate-fragile component). Validate per camera — distant approaches may invert the trade.

**1.1 Birth-gate loosening + offline track-quality filter.** Lower activation/birth thresholds
(`TRACKER_ACTIVATION_THRESHOLD`, BoT-SORT `new_track_thresh`) and disable score-fusing in
association where applicable; recover the resulting junk with a NEW post-run filter module
`backend/services/track_filter.py` applied at `_finalize_track()` time: keep tracks by
(length × net displacement × mean detection score) instead of birth-time score. Persist filter
verdict + reason on `vehicle_events` for review-screen visibility.
*Rationale:* ByteTrack never births from low-score boxes; blurred fast vehicles can be detected the
whole transit and produce zero tracks. Offline pipelines don't need strict birth gates.

**1.2 OC-SORT A/B for throughs.** The backend already exists (backend/services/tracker.py:107–197,
boxmot). Sweep it as the throughs tracker in the hybrid (`apply_hybrid.py`) against ByteTrack across
all 5 corridor cameras. Research predicts the motion model (ORU/OCM) helps exactly our non-linear +
fast-displacement cases at zero compute cost. Standing rule applies: PICK THROUGHS TRACKER BY
MEASUREMENT.

**1.3 Buffered-IoU (C-BIoU) association.** Add box-buffering to the association step of whichever
trackers win 1.2 (small patch in our tracker wrappers; both supervision and boxmot expose the IoU
step or can be subclassed). Sweep buffer scale per camera. Direct published fix for fast movers whose
consecutive boxes don't overlap.

**1.4 Kalman process-noise sweep.** Raise velocity process noise Q for vehicle classes vs the
pedestrian-tuned SORT defaults; expose as a `calib_*` per-camera knob like NMS/match_thresh.

**1.5 Offline post-pass: tracklet stitching + gap interpolation.** New
`backend/services/track_postpass.py` (AFLink-style appearance-free fragment linking + Gaussian-
smoothed interpolation, both CPU-trivial), run after tracking and before classification/dedup.
Pairs with 1.1: looser birth creates fragments, the post-pass merges them. This also directly
attacks the turn-side residual map (fragmentation/ID-switch on turns is the known mechanism for the
cam4 EB-left +38 / cam2 SB-right −41 cells).

**Phase 1 exit gate:** corridor net@30min improves on ≥3 of 5 cameras with no camera regressing
>1pp; fast-vehicle census bucket "detected-never-tracked" shrinks materially. Ship winners as
defaults + per-camera overrides; re-derive banks afterward (tracker change invalidates banks).

---

## Phase 2 — Channel-Bank v2: ground-truth-free bank building (≈2–3 weeks, the new-site enabler)

Replaces Miovision in `build_bank.py` with the benchmark-winning recipe: human movement definitions
+ the site's OWN collected trajectories + hand-drawn fallback. Builds on the channel research
(experiments/channel_tool.html, experiments/channel_replay/replay_channels.py).

**2.1 Channel tool → product.** Promote the hand-drawn channel editor from experiments/ into the
leg-calibration UI (per standing feedback: per-intersection tunables live in the calibration UI, not
config.py). Operator draws, per camera: leg entrance/exit lines + optional channel polylines for
movements. Persist in a new `channels` table keyed to camera, versioned alongside legs.

**2.2 Auto-collection of reference trajectories.** New `scripts/build_bank_gtfree.py` (shares
polyline-fitting code with build_bank.py — factor the common core into a module):
- Collect tracks whose endpoints cross an (entrance, exit) line pair → that's the movement's
  candidate set (the AI City winner's recipe; no counts needed).
- Accumulate-and-average per movement into the reference polyline; surface the candidates in a QA
  view where the engineer confirms/picks typical trajectories (1–2 per movement).
- Movements with zero collected tracks fall back to the hand-drawn channel polyline.
- Bootstrap window: first 30–60 min of site video (research: 30 min sufficed in the published
  unsupervised system).
*Validation on the corridor:* build GT-free banks for all 5 cameras pretending Miovision doesn't
exist; compare net@30min vs the Miovision-built banks. Target: within 2pp of the Miovision-built
bank per camera. This number IS the go/no-go for the new-site story.

**2.3 Fragmentation-robust distance function.** A/B the current DTW/partial-Fréchet matcher against
min-of-directed-Hausdorff + heading-angle term + endpoint-proximity term (purpose-built for broken
vision trajectories; 99.8 vs 56.9 on dense oblique views in the literature). Integration point:
`score_path_joint()` in backend/services/trajectory_classifier.py:589 and the channel matcher.
Keep whichever measures better — possibly per-site (research: no single distance wins everywhere),
which argues for making the matcher pluggable + reporting per-site matcher QA (2.4).

**2.4 Per-site matcher QA report.** Since no matcher transfers blindly: auto-generate a per-camera
calibration report after bank building — per-movement support counts, match-cost distributions,
overlap/ambiguity warnings (the snap-magnet signature: a turn polyline collecting >>3× its plausible
share), unmatched-track rate. Surfaced in the UI before processing is unlocked. Fold the existing
magnet gates (`--magnet-min-manual` etc.) into score-based equivalents that don't need manual counts
(e.g., share-of-collected-tracks instead of Miovision manual counts).

**Phase 2 exit gate:** GT-free banks within 2pp of Miovision banks on the corridor; full new-site
setup (legs + lines + channels + bank QA) demonstrated end-to-end in <1 hour of operator time.

---

## Phase 3 — Conservation QA layer (≈1 week, the new-site validator)

Zero-ground-truth automated sanity checks, standard agency practice (Maryland SHA et al.).

**3.1 Reverse-movement balance.** New `backend/services/conservation_qa.py`: over an
intersection-day, compare each movement's volume to its geometric reverse; flag cells outside a
tolerance band (tune the band on the corridor where we know true error). Per-15-min and per-day
views.

**3.2 Corridor consistency.** Across intersection-day cards in a project: volume exiting card N
toward card N+1 ≈ volume entering N+1 from that direction (net of mid-block access — operator can
annotate "driveways present" per link to widen tolerance). Uses the existing cardinal-direction join
from the corridor stack.

**3.3 UI surfacing.** QA panel on the intersection-day card: green/amber/red per check, linking
straight into the review screen pre-filtered to the implicated movement cells (the review screen
already supports leg/movement filters — backend/routers/review.py). This is what makes the human
review pass *brief and targeted* instead of open-ended.

**Phase 3 exit gate:** on the corridor, the QA flags rank-correlate with known per-cell error (the
turn-residual map); flagged-cell review demonstrably catches the worst cells.

---

## Phase 4 — New-site validation protocol & the review-minutes budget (≈1 week)

Turns "≤5% with a brief human pass" into a defined workflow rather than a hope.

**4.1 Spot-count workflow.** Review-screen mode for counting a randomly-chosen N-minute window per
camera from raw video (count-only, faster than per-event review); compare to system counts for the
same window; report implied per-movement error with a binomial/Poisson confidence interval. (The
sample-size statistics were an open question in the research — derive them ourselves; it's
elementary CI math once the workflow exists.)
**4.2 Acceptance gate per intersection-day:** conservation checks green/amber + spot-count CI
consistent with ≤5% → ship Excel; otherwise targeted review of flagged cells, re-check, iterate.
**4.3 Document the operating procedure** (docs/new_site_runbook.md): camera setup → calibration +
channels (<1 hr) → bootstrap bank → process → QA gate → targeted review → export. This runbook *is*
the product story that replaces Miovision.

---

## Phase 5 — Detector A/B (parallel/optional; escalates if Phase 0.2 shows detection failure)

Research explicitly refuted the literature claims here — must be empirical on our footage.
- Candidates within the OpenVINO budget: current yolo26l@1280 vs yolo26m/s at higher effective
  resolution, RT-DETR-class INT8, tiled inference (SAHI) for distant approaches only.
- If (and only if) 0.2 shows true detection misses on fast vehicles: blur-augmented fine-tuning of
  the detector on our own vehicle crops (research: beats deblur preprocessing; CPU-feasible at
  train-once cost on a cloud GPU, runs locally unchanged).
- Measure: recall on the Phase 0.3 "never-detected" bucket + end-to-end net@30min + wall-clock per
  intersection-day on the target laptop.

---

## Sequencing & dependencies

```
Phase 0 (days) ──► Phase 1 (tracker) ──► re-derive banks ──► Phase 2 (GT-free banks)
                         │                                        │
                         └── escalate Phase 5 if detection-bound  ├─► Phase 3 (conservation QA)
                                                                  └─► Phase 4 (protocol + runbook)
```
- Phase 1 before Phase 2: a tracker change invalidates banks; build the GT-free pipeline on top of
  the better tracker once, not twice.
- Phase 3 is independent of 1–2 (works on counts) and can be built in parallel by preference.
- Phase 4 depends on 2+3.
- Pending pre-work to land first: commit the uncommitted `--magnet-min-manual` guard in
  scripts/build_bank.py (its logic gets generalized in 2.4, but it should be in history first), and
  finish PM validation for cam1/3/4.

## Risks

- **Pedestrian→vehicle transfer (Phase 1):** OC-SORT/C-BIoU gains are benchmarked on
  pedestrians/dancers; mitigation is the cheap A/B harness — if it doesn't measure, it doesn't ship.
- **GT-free bank quality (Phase 2):** the 2pp target may not hold on oblique views (published
  GT-free wins were on easier single-approach views). Fallback: more hand-drawn channels per site
  (operator minutes, not ground truth) + heavier reliance on the Phase 3/4 QA loop.
- **Conservation tolerance tuning (Phase 3):** unbalanced real-world flows (one-way pairs, heavy
  driveways) can false-flag; per-link annotations and corridor-tuned bands mitigate.
- **8GB ceiling:** every-frame detection at 1280 may not fit overnight budgets on some machines;
  the imgsz-vs-frames trade is measured per camera in 1.0, and `balanced` mode remains the
  documented fallback.
- **Leg-label hygiene:** the cam1 180°-swap incident shows label errors poison everything
  downstream; Phase 2.4's QA report should include a heading-vs-label sanity check to catch swapped
  legs automatically at new sites.

## Success criteria (whole plan)

1. New site, zero Miovision, <1 hr operator setup → processed intersection-day passes the Phase 4
   acceptance gate at ≤5% net per movement @15min after ≤30 min of targeted review.
2. Corridor (regression suite): no camera worse than today; fast-vehicle census buckets shrunk.
3. Wall-clock: intersection-day still processes overnight on the i5-1135G7/Iris Xe/8GB target.
