# Research synthesis — Pipeline v2 "assemble-then-count" (2026-08-03)

Four external research sweeps (TMC counting SOTA / offline global MOT /
low-res detection / industry practice) fused with the internal failure
ledger. Companion to `plan_no_footage_regrounding_2026-08-03.md` — this
doc is the evidence base and the concrete architecture. Full agent
reports with URLs preserved in the session transcript; key citations
inline.

## 0. The five external facts that change the plan

1. **The fragmentation problem is SOLVED at industrial scale, in traffic,
   on CPU, without appearance or training.** I-24 MOTION (Vanderbilt,
   TR-C 2024): min-cost-circulation stitching of tracklet fragments
   (47.9 fragments/vehicle!), motion-only Gaussian-cone costs, 4 h of
   footage reconciled in 3.5 h CPU. Known blind spot: stopped vehicles
   (switches 0.04→0.52 in congestion) — fixable with an explicit
   zero-velocity link hypothesis they don't have. Our ReID-twin negative
   (AUC 0.399 far-band) is thus NOT a blocker: the best traffic stitcher
   is appearance-free anyway.
2. **The AIC winners' counting margin came from the assignment layer,
   not the detector.** Baidu's ablation: gate/line counting 86.4 → soft
   Hausdorff prototype matching + direction + spatial constraints 93.4
   (+7). Tiny-PIRATE (YOLOv4-tiny!) took 2nd in 2021 (0.9459) — proof
   detector size is not the bar. DiDi set matching thresholds by
   statistics over the window's own distance/angle distributions (the
   anti-frozen-constant pattern, published). Jana et al.: auto-clustered
   prototypes classify 99.6–99.8% of OBTAINED tracks — assignment is
   near-solved once tracks exist; TRACK EXISTENCE is the war (matches
   our wall autopsies exactly: cam2 EB-thru has 20 complete journeys vs
   Mio 749).
3. **Detection stability, not detection recall, is the far-field lever —
   and it's nearly free.** REPP-class offline tubelet linking/rescoring:
   +6.5 mAP, +10.8 on the low-IoU (flicker) split, 2.6 ms/frame CPU.
   Scale-matched 1280 inference on upscaled frames (fine-tune at same
   size): +25% relative on drone benchmarks; interpolation-only upscale
   gave +23% AP in the satellite analog. Motion-mask fusion (DiDi used
   it in a winner system; satellite analogs F1 0.84 vs 0.73) recovers
   movers BELOW the CNN floor. Measured dead, do not revisit: SAHI at
   VGA source, GAN/video SR (≈ interpolation, + flicker), feature-level
   VOD (collapses <16 px: SELSA 0.0 AP on XS-VID).
4. **Miovision's ±5/95 is a service SLA, not a model spec.** Patent
   US8204955B2: prototype-path matching + a PATENTED human-QA stage with
   confidence-ranked exception queues. Unassisted, independently
   measured (MDOT SPR-1741): 15% day / 24% night error. Guarantee
   attaches only to their 1080p hardware at ≥21 ft, 5-star setup, night
   excluded. NO vendor achieves ±5/95 unattended on 640×480 oblique
   footage (GoodVision's own spec requires ≥32 px vehicles at our
   width). Consequence: our pipeline+queue claim shape IS the industry's
   winning shape; the referee bar is delivered-vs-delivered.
5. **Corridor link cross-validation is standard industry QA we already
   have data for.** Miovision validates adjacent intersections agree
   ±5/95 on common links. We have 5 adjacent intersections; we compute
   cross-camera overlap only as dedup today. A link-conservation scorer
   is a free, GT-free failure-finder (feeds the queue).

## 1. Pipeline v2 — assemble-then-count

Stage 0  Detections (existing caches now; Workstream B upgrades later).
Stage 1  TUBELET STABILIZATION (new, cheap): REPP/Seq-Bbox-class offline
         linking of low-threshold detections → tubelet-average
         rescoring, missed-frame interpolation, coordinate smoothing.
         Link scorer: center-distance-weighted (IoU/appearance degrade
         <16 px); trainable from synthetic fragmentation of our own
         confident tracklets — no GT.
Stage 2  High-purity tracklets (existing pass-1 recipes, unchanged).
Stage 3  SPLIT + PRE-MERGE (new): cut mixed-identity tracklets on motion
         discontinuity (embedding-DBSCAN only near-field where ReID is
         valid); structurally pre-merge CONCURRENT near-duplicates
         (time-overlap + IoU-over-time) — disjoint-path solvers cannot
         merge concurrent twins, so this kills that class before the
         solve. Pairwise-signal-free (our 3× dead channels stay dead).
Stage 4  GLOBAL ASSEMBLY (the core): tracklet-graph min-cost flow
         (OR-Tools SimpleMinCostFlow, integerized costs; <1 min/window
         at our scale). Structure: node-split tracklets (use ≤1), unit
         evidence costs (solver can DROP phantoms that can't pay for
         themselves), entry/exit arcs priced by leg-gate/border zones
         (Berclaz precedent) with zones + STOP ZONES derived from the
         window's own long-track endpoints (Huang-Nevatia precedent);
         link costs = min(constant-velocity Gaussian cone, ZERO-VELOCITY
         waiting hypothesis) with α,β self-calibrated per window from
         intra-tracklet prediction residuals (I-24 + our fix); heading/
         approach-compatibility gate against cross-queue swaps.
         T_max ≈ max red phase + margin (~120 s).
Stage 5  MOVEMENT ASSIGNMENT: entry-leg→exit-leg for complete chains
         (the v3 box-side convention, unchanged); residual partials get
         SOFT assignment — per-movement KDE/completeness likelihood
         against prototypes clustered from the window's own complete
         chains (fitted-from-data, never drawn — standing rule intact;
         this is the AIC +7 layer and the honest successor to the
         box-clip's dead full-journey matching). Ambiguity → solver/
         assignment marginals, not forced picks.
Stage 6  CONSERVATION QA (upgraded): per-bin approach-entry vs
         movement-sum reconciliation + NEW corridor link cross-check
         between adjacent intersections. Violations + low-margin
         assemblies → flag queue with principled impact.
Stage 7  Review layer (existing) + C1 targeted human fill for
         perception-invisible residuals.

Compute: everything above detection is CPU-trivial (seconds–minutes per
window). Stage-1 rescoring ~1.01×. Later Stage-0 upgrades (1280
scale-matched, far-ROI crops, motion fusion) are 2–4× detection — still
inside overnight.

## 2. Execution order + pre-declared gates

WEEK 1 — derisks (all on existing caches/dumps, dev cams cam2 + cam1-PM):
  D1. gta-link (MIT) as-is on cached tracklets+OSNet: afternoon
      baseline; measures how much a NAIVE global stitcher already buys.
  D2. Synthetic-fragmentation instrument: cut our own confident
      tracklets, measure re-stitch recall of (a) gta-link, (b) the MCF
      prototype — the no-GT progress metric for assembly.
  D3. MCF assembly prototype (Stage 3+4 minimal): cam2 study_0700.
      GATE G-A1: EB split-flood halved without NB/SB regression.
  D4. Stage-5 soft assignment on assembled chains; cam1 PM.
      GATE G-A2: cam1 PM 5/95 to AM level.
WEEK 2–3 — harden + blind transfer:
  GATE G-A3: frozen solve, zero per-camera edits, all 5 cams + FM51 —
  no camera regresses vs curated tables (the box-clip killer gate).
  Then Stage 1 (REPP-class) under it; re-measure.
  GATE G-A4: ft2 re-detect under the solver at cam2/cam3 — does
  association now hold the density? (07-24 disposition re-test.)
THEN — Workstream B detection upgrades (1280 scale-matched fine-tune,
  far-ROI crops, motion fusion), each through the Phase-1 apply gate;
  Workstream C (link-conservation scorer, named recall gaps, targeted
  human fill) in parallel from week 1 — independent of the solver.

## 3. Honesty ledger

- Published counting numbers (AIC 0.93–0.95 effectiveness) are
  CUMULATIVE nwRMSE — kinder than our per-bin bar. Nobody publishes
  per-bin ±5/95 raw-pipeline compliance. The bar remains referee-parity
  of DELIVERABLES (ours worked-queue vs theirs human-QA'd).
- Global solvers' new failure mode is over-merging (undercount) and
  confidently-wrong permutations in stopped queues — Stage 3 split-first
  ordering, the zero-velocity hypothesis, and G-A3's no-regression
  tripwires are the specific defenses; synthetic-fragmentation recall
  (D2) is the early-warning instrument.
- BEV stays parked for attribution (internal non-circular negative
  stands); ground-plane as a KDE feature MAY be revisited only if
  Stage-5 residuals point at perspective compression, and only through
  the same gates.
- If G-A1/G-A2 fail, the plan returns to the drawing board and says so.
