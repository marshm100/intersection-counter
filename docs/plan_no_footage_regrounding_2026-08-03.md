# Regrounding — make it not fail on THIS footage (2026-08-03)

OPERATOR DIRECTIVE: there is no footage upgrade. 640×480 is the terrain.
The detect→track→classify chain as shipped is unacceptable; find the way
that does not fail. This SUPERSEDES plan_miovision_replacement_2026-08-03
Phase 2 (procurement) — that phase is DEAD. Phases 0/1 (schema bug,
dispositions, apply gate) survive: wins must persist in the product.

## 1. What the failure ledger actually says (reground, not re-litigate)

Every retired mechanism, one line each, with its lesson:

- ReID blanket (§2c): helped THE fragmentation camera once (cam1
  21.8→7.2), failed as blanket. Lesson: appearance evidence is real but
  online, greedy use of it doesn't transfer.
- Box-clip as counter (Gate B): parity on the dev camera, −15 to −52%
  blind on the rest. Lesson: frozen constants die under camera shift.
- Drawn-channel attribution (4× measured): snap-magnet, catastrophic.
  Lesson: geometry as an ASSIGNMENT TARGET over-claims; standing rule
  stands.
- Origin veto + rescue: FM51-proven, corridor over-fire (d_main
  signature compresses at far-field). Same frozen-constant lesson.
- LEC2 echo collapse: aggregate MAE wins that BREAK BINS (removes real
  vehicles); ship set empty 6/6. Lesson: local dedup can't tell echo
  from vehicle because the decision needs global context.
- cam5 bank-hole fills (3×): approach-level "gains" were phantom
  cancellation. Lesson: adding paths without global consistency just
  moves the error.
- ft2 corridor re-detect: detection density ×2 → attribution errors
  amplified in each camera's own signature. THE LESSON OF THE CAMPAIGN:
  detection recall is not the bottleneck; association is downstream-
  blocking every detection gain.

Common root, stated once: the chain makes IRREVERSIBLE local decisions
(births, associations, event emissions) frame-by-frame with tuned
constants, then tries to repair them after the fact. On low-res
far-field footage the local evidence is simply too weak per-decision.
No amount of per-decision tuning fixes decisions that shouldn't be made
locally at all.

## 2. The untried family: global offline association (Workstream A)

Pass-2 is already offline. Make it actually offline:

A1. Keep pass-1 EXACTLY as is — detections + conservative tracklets.
    Fragments become INPUT, not failure: stop preventing fragmentation,
    start assembling it.
A2. Tracklet graph per window: nodes = high-purity tracklet fragments;
    edges = feasible continuations scored by (a) kinematics through the
    box (curvilinear continuation, gap-time-bounded), (b) ReID
    embeddings (sidecar infra exists), (c) leg-gate topology from
    operator calibration — geometry as FEASIBILITY/prior, never as
    assignment magnet (rule preserved).
A3. Global solve (min-cost flow / ILP) over the whole window with hard
    structure: every tracklet used ≤1 path; every counted path enters
    via one leg gate and exits via one leg gate; solver-level
    exclusivity replaces LEC2-style after-the-fact dedup (an occlusion
    split becomes ONE path because two paths can't both consume the
    shared fragments cheaply). Soft structure: intersection flow
    conservation over the window (GT-free physics), volume priors from
    the corpus bank as COSTS not gates.
A4. Events emitted from solved paths (origin=entry side, dest=exit
    side — truncation-driven classification error shrinks because
    assembled paths are long). Solver marginals become the review
    queue's uncertainty: ambiguous assemblies → cards with the
    alternative shown. The queue gets principled doubt, not heuristics.
A5. Constant-light discipline (the anti-box-clip rule): edge costs from
    per-window data statistics (speed/gap distributions measured from
    the window's own confident tracklets), not hand-frozen thresholds.
    Pre-declared: any constant that must be tuned per-camera is a
    design failure in this workstream.

Dev protocol (discipline unchanged): build against cam2 (occlusion
splits, hardest) + cam1 PM (fragment flood window). GATES, pre-declared:
  G-A1 cam2 EB split-flood: solver ≥ halves EB over-count without
       NB/SB regression (the ft2 wins finally become bankable).
  G-A2 cam1 PM: fragment flood assembled — PM 5/95 ≥ AM's level.
  G-A3 Frozen-solve blind transfer: same code, zero per-camera edits,
       all 5 cams + FM51 held-out — no camera regresses vs its curated
       table. (The box-clip failure mode is the thing this gate kills.)
  G-A4 ft2 re-detect UNDER the solver at cam2/cam3: the 07-24
       disposition is re-tested — if association now holds the density,
       detection gains stack; if not, ft basis stays parked.

## 3. Perception floor on 640×480 (Workstream B — gated behind A)

Only AFTER G-A3 (association can hold new detections):
B1. Far-field tiled inference (SAHI-style zoom slices on the far half)
    — recall where pixels are fewest; offline pass-2 affords compute.
B2. Motion-fused detection (background-subtraction / temporal
    differencing fused with CNN confidences) — small movers at distance
    are classical motion detection's home turf; derisk with
    detector_zone_recall.py before any wiring.
B3. Video super-resolution crop spike (SR far-field crops → detect):
    measure zone recall honestly; hallucination risk named; spike is
    cheap, verdict is measured. This is the software substitute for the
    footage we cannot buy.
Each B item ships ONLY through the A solver + Phase-1 apply gate.

## 4. Residuals the pipeline can never see (Workstream C)

Some walls are vehicles never detected at all (cam5 undercount family).
No solver assembles what was never seen, and review can't fix an event
that doesn't exist. On fixed footage the honest closure is TARGETED
human fill, child-test cheap:
C1. Undercount discovery: spot-count deltas + conservation deficits +
    reverse-balance already localize suspect bins blind. Route them to
    a new card kind: "Watch this 15-min window at this approach — tally
    what the machine missed" (the tally screen exists; scope it to the
    bin). Labor is bounded: only flagged bins, only BIG deltas.
C2. Close the three NAMED recall gaps (cam2 S3-blocked classes, cam4
    SB-right high-confidence phantom, cam5 EB-right formation) so BIG
    failure recall → 100%: post-review 100% requires the queue to SEE
    every big failure.
C3. GATE: 6.3 ceiling re-run — ≥99% post-review EVERY camera on this
    footage, labor measured in minutes/camera-day and reported beside
    the ~10× target.

## 5. What "not fail" means — OPERATOR DEFINITION (2026-08-03, final)

"Not fail" = our finished deliverable REACHES OR EXCEEDS Miovision's
accuracy standard. No footage-class hedging. Operationalized:

- The yardstick is an INDEPENDENT MANUAL REFEREE, never Miovision
  itself (against Miovision-as-truth, perfection is mere equality; a
  referee is what makes "exceed" measurable). Instrument exists:
  triangulate_manual.py + the tally screen's independent counts.
- Miovision's measured quality on THIS corridor's own footage:
  2.8% interval MAE vs manual (cam1 referee check), 5/95 compliant
  essentially bin-for-bin, delivered WITH their human QA layer.
- Therefore the bar, per camera-day deliverable (ours = pipeline +
  worked queue, theirs = their deliverable on the same clips):
    (i)  referee-sampled bins: our per-bin error ≤ theirs;
    (ii) 5/95 hit rate vs referee ≥ theirs;
    (iii) achieved at the measured labor budget (minutes/camera-day).
- Evidence it is reachable on 640×480: cam1 triangulation put the
  stack at −1.5/+2.2% net vs the same hand count that scored Miovision
  2.8% — the stack has ALREADY exceeded them once, on this footage,
  where detection held. The campaign's job (A, B, C) is to make that
  the norm instead of the exception.

Ceiling deficits to close (post-review, today, %-of-bins short of ~100):
cam1 −2.4 · cam2 −0.6 · cam3 0.0 · cam4 −1.2 · cam5 −4.1. Workstreams
A+B raise raw compliance (fewer failures to review), C makes every
remaining failure visible and fixable — the three levers must jointly
zero these deficits, and C3's gate is restated accordingly: NOT the
interim ≥99, but referee-parity per (i)–(iii).

Acceptance (6.5-shape, restated): blind study on clips the system has
never seen, operator-run end to end; Miovision ordered on the SAME
clips; both deliverables scored against the manual referee; PASS =
(i)–(iii) hold on every camera-day in the study.

Sequence: A is the campaign. Start A1–A3 immediately (dev cams), C1/C2
in parallel (independent of solver), B spikes only after G-A3, product
Phase-0/1 items continue (bug fix + dispositions + apply gate) so every
win persists. First checkpoint: G-A1/G-A2 verdicts — if the solver
cannot beat the curated tables on the two dev cameras, this plan
returns to the drawing board and says so plainly.
