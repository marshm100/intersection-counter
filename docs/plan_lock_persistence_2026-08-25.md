# Lock-persistence scored gate (G-LP-1) — gate doc

Declared BEFORE any scored run (house gate discipline). Mechanism: the
bus-law tracker (operator identity law, 2026-08-24: occlusion does not
end identity — incompatible motion does), recipe botsort_locked at the
4c-amendment commit: theft mask + physics recovery + probation with
revocation + gate-break re-stamp + claim-cone cap (frozen stitch
windows) + gate-straddle splits (a join may not span a gate) + mover
expiry. Operator demo-review rulings ledgered in
docs/diag_lock_demo_review_2026-08-24.md; amendment demo (4c-2) acked.
Lineage: 4a hygiene + 4b gate bfc807d; iterations 2-3 + meter a585484;
amendment (this basis). 17 bus-law tests; full suite green.

## What is being tested

ARM = ONE mechanism, two knobs, declared together: (1) the three cam2
study windows re-tracked under botsort_locked with lost buffer 750
(fps-rescaled 625 frames = 25 s; injected via
runs/s4_lock/s4_pass1_runner.py — production calibration untouched);
(2) the replay's finalize grace raised to match via env
TRACK_FINALIZE_GAP_FRAMES=650 (buffer 625 + 1 s) — without it the
counting stage splits 1,629 healed identities back apart and
double-counts them; the tracker's memory and the counter's patience
are one identity mechanism. Geometry, gates, supremacy, paths: all
unchanged (the shipped basis).

CONTROL = shipped production = the gatesup scores (G-GS-1 SHIPPED
2026-08-24). Valid per the code/data-arm precedent; new score JSONs
self-record the production basis.

## G-LP-1 (the ship gate)

- Controls: pooled movement 64.8% (214/330); per-window 67.3 (72/107) /
  62.0 (67/108) / 65.2 (75/115); approach 43.8 / 50.0 / 40.6
  (pooled 44.8, 43/96).
- PASS: arm pooled movement > 64.8%, AND no window more than 2.0 below
  its control (floors 65.3 / 60.0 / 63.2). Approach recorded alongside
  (secondary).
- MISS: zero revert (botsort_locked is opt-in; grace default
  unchanged); negative ledgered here + roadmap.

## Interactions ledgered (pre-registered readouts)

- (a) EVIDENCE-ACTIVATION COUPLING: "the tracker choice controls pair
  activation" (measured three times). Controls 0.566/0.496/0.493 vs the
  0.45 bar; the amended s4_study_1100 measured above-bar before the
  final amendment. Record all three arm coverages; if any window flips
  vs control, run the ft2-precedent flag-off decomposition pair
  (EVIDENCE_ACTIVATION_ENABLED=0 both sides) — else the mechanism
  measurement is void.
- (b) RAISED GRACE compresses index-time across intra-track gaps in
  the pipeline's trajectory model. For queue joins the gap precedes the
  entry crossing, so crossing evidence is largely safe; u-turn counts
  ctrl-vs-arm are the canary readout.
- (c) QD LAW: any added volume in deficit cells triggers a mandatory
  human-review sample sheet before any ship.
- (d) ID-TRANSFER KILL GATE: duplicate-tid census (production 95 tids /
  195 events @1600 — the split-on-reuse class the raised grace should
  collapse), gate_breaks, gate_straddle_splits reported per window.
- (e) KNOWN LIMITATION carried: the born-parked residual class (755
  flip-at-gap tracks at 1100) — count-neutrality argued (the parked
  half carries no crossings; A2 forbids synthetic ones); this gate
  adjudicates it empirically.

## Procedure

1. Copy detection caches study_0700/1600 -> s4_ variants (parquet +
   meta sidecar; cache_exists must be true before launch). 1100's
   amended dump rebuilds under the final amendment in-run guard:
   rebuild it fresh at this commit for basis purity.
2. Pass-1 x3 under the runner (background, ~15 min each, sequential).
3. Armed-verification per meta: backend botsort_locked, lost_buffer
   750, gate_breaks + gate_straddle_splits keys present.
4. Replays x3: fresh workdir _replay_scratch/s4lock_20260825, env
   TRACK_FINALIZE_GAP_FRAMES=650, v2_run_pass2 from the repo root.
5. Copy to stems s4arm_cam2_study_* (sqlite backup API); score all
   three in one v2_score_dev call.
6. Verdict + readouts here + roadmap changelog; commit PASS or MISS.

## Verdict — G-LP-1 MISS on all three windows (2026-08-24)

| window | movement ctrl -> arm | approach ctrl -> arm | coverage |
|---|---|---|---|
| study_0700 | 67.3 -> **56.8** (-10.5) | 43.8 -> 31.2 | 0.566 -> 0.595 |
| study_1100 | 62.0 -> **57.9** (-4.1) | 50.0 -> 15.6 | 0.496 -> 0.600 |
| study_1600 | 65.2 -> **50.8** (-14.4) | 40.6 -> 9.4 | 0.493 -> 0.559 |
| pooled | 64.8 -> **55.1** (190/345) | 44.8 -> 18.8 | activated x3 |

No activation excuse: coverage ROSE on every window (the healed dumps
strengthen the evidence channel). The mechanism scored honestly and
lost on VOLUME:

- Events collapsed: 4,662/3,407/5,514 vs production ~5,500-6,500 per
  window. Every deficit cell deepened (1600: SB_thru 1,768 -> 1,361 vs
  Mio 2,247; NB_thru 1,696 -> 1,310; EB_left 267 -> 213).
- The duplicate class is GONE: dup-tids 0/0/0 (production: 95 tids /
  195 events at 1600). Confirmed prediction — and it is exactly the
  problem: production's volume equilibrium is PARTLY BUILT ON identity
  errors. Fragmented identities count twice; those double counts
  offset genuinely missed (detection-dark) vehicles in the same cells.
  Healing identity removes the compensating inflation without
  recovering the real missing vehicles.
- Canary fired: u-turns 25/28/56 vs Mio ~1/3/12 — index-time
  compression across healed gaps mints same-leg journeys, a secondary
  distortion consistent with (b).

STRUCTURAL READING (the same wall as G-TR, now measured from the other
side): the counting stage's accuracy against Miovision is an
equilibrium calibrated on broken tracks — identity errors inflate
volume toward Miovision's higher truth. ANY repair that makes identity
more honest (cuts, glue, or a better tracker) lowers counted volume
below that equilibrium and scores worse, because the true deficit is
DETECTION (measured: 67% of fast-mover track deaths are detection-dark,
the detector's, not association's). Identity repair is necessary for
correctness but cannot pay for itself on this bar until the missing
volume is recovered by real detection or measured review.

Iteration budget: ONE scored iteration spent; the second is
deliberately RESERVED (not burned on a blind re-tune) until a
volume-recovery companion exists — either R0's measured review
(Phase 2, the un-inflated path to volume) or Stage-5 detector work.
Revival condition, ledgered: re-run G-LP-2 = botsort_locked + grace
WITH one volume-recovery mechanism in the arm.

Assets standing: recipe botsort_locked (opt-in, fully tested, 17
bus-law tests), the finalize-grace env override (default pinned 60),
dup-elimination proof, three armed s4_ dumps + score artifacts.
Production untouched at 64.8.

## SHIPPED — no. MISS; production untouched (scratch-only replays).
