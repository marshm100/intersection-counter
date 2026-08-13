# Tier-3 Block — A1+B2: tubelet stabilization with a zero-velocity
# hypothesis, RESCORE-ONLY iteration 1
# (2026-08-13)

Operator-approved at the Tier-1 checkpoint. The only lever aimed at the
tracker BIRTH GATE — the wall every Tier-1 block confirmed from a
different side: ft2 doubled raw detections and they did not convert
(insufficient-track counts ~2x, E4); a different tracker did not convert
them either (H1); the twin channel that would dedup them is dead (B1).
Literature mechanisms (research_synthesis_queued_2026-08-12): F6
BoostTrack-style tracklet-similarity confidence rescoring with adaptive
treatment for coasting tracks; F7 YOLOV pre-NMS temporal aggregation
(low-conf candidates deliberately preserved); F2 move-stop-move: an
explicit stopped state entered only below a speed threshold, with missed
detections treated as evidence FOR the stop, not track death; F5 the
ByteTrack-family birth rule (only unmatched HIGH-conf detections birth
tracks) — the documented design property we are compensating for.

## Scope discipline

ITERATION 1 IS RESCORE-ONLY: the stabilizer changes detection CONFIDENCE
values only. No synthetic boxes, no gap interpolation, no NMS changes.
Row count and every non-conf column byte-preserved (pinned by the
instrument's parity check). Gap interpolation (synthetic coasted boxes)
is the PRE-NAMED iteration 2, taken only if iteration 1's instrument
shows the recovery ceiling is missing FRAMES rather than low conf.

## The target class, measured precisely (2026-08-13 exploration)

The tracker's REAL thresholds (verified in supervision 0.17.1 / boxmot 18
source + live calib): BoT-SORT (cam1/2/3) associates from
track_low_thresh 0.10 (hardcoded), first-round splits at activation
(cam2: 0.25), but BIRTHS only from detections >= new_track_thresh —
cam2's calib leaves it NULL so the wrapper default **0.30** applies
(cam3: 0.18 by calib). ByteTrack (cam4/5) births at activation + 0.1 =
**0.35** (supervision hardcodes det_thresh = track_thresh + 0.1).
So cam2's associate-but-never-birth band is (0.10, 0.30) — **~38.5% of
its cached detections** (33.0% in [0.10, 0.25) + 5.5% in [0.25, 0.30)),
and the diagnosed birth_gate orphan clusters are ANCHORLESS: conf_max
< 0.25 for the whole cluster (diagnose_fast_misses verdict rule).
CONSEQUENCE FOR THE DESIGN: an anchor-required boost rule would be
blind to exactly the failing class. Eligibility must be STRUCTURAL.
Detections below 0.10 do not exist in the cache (detect floor 0.1) and
are invisible to every backend — no rescue below 0.10 is possible.

## Mechanism

1. Per-window SELF-CALIBRATION from the window's own BASE pass-1 dump
   tracklet table (fit_motion_residual: v_stop, zv_radius, alpha/beta) —
   the anti-frozen-constant mechanism, reused at detection level.
2. TUBELET LINKING over the raw detection stream, best-per-frame,
   reusing the retired v2_tubelet matcher shape (predicted-center greedy
   with gate 0.7*diag + 0.6*|v|*dt — proven code, scripts/v2_tubelet.py
   :93-116) plus the B2 ZERO-VELOCITY hypothesis: when the tubelet tail
   speed < v_stop, the association radius is zv_radius and missed frames
   do not terminate the tubelet (coast 1.0 s moving / 3.0 s stationary —
   the fit_motion_residual stopped-run bound). All bounds time-based.
   NOTE the framing correction vs the retired v2_tubelet: that script
   died as a REPLACEMENT tracker ("association too weak — floods
   30-32%; BoT-SORT association quality is load-bearing"). This build
   is cache-in / cache-out: BoT-SORT still does ALL tracking.
3. RESCORE RULE (structural eligibility — the anchorless-class fix):
   a tubelet is boost-eligible iff span >= 1.5 s AND >= 8 members (the
   v2_tubelet N-of-M precedent, time-scaled) AND member density >= 0.5
   per frame over its span AND motion-coherent (net path >= its own
   bbox diagonal OR ZV-stationary: tail speed < v_stop with residual
   inside zv_radius). Every member with conf below the camera's
   EFFECTIVE BIRTH FLOOR (backend-derived at runtime: botsort
   new_track_thresh, bytetrack activation+0.1 — never hardcoded) is
   raised to birth_floor + 0.02. Boost only upward, only within
   eligible tubelets, value capped (no tubelet-relative inflation).
   The false-birth bound is the instrument's DECOY gate, not an anchor
   requirement — the ledger's warning stands ("raises detection volume
   without converting" is the measured failure mode of both ft2 and
   the retired v2_tubelet; the phantom guard + decoy gate police it).
4. OUTPUT: `a1_<window>.parquet` + meta.json (source variant, stabilizer
   constants, calibration, boost census; schema = the 7-column cache
   contract: frame_idx, bbox_x1..y2, confidence float32, class_id) →
   standard pass-1 (variant name is the entire selector; cache_exists
   checks file+sidecar only; modified conf flows to the tracker
   untouched — verified end to end) → pass-2 → score. Zero backend
   changes; the measurement chain is the shipped one. Pre-tracker NMS
   (cam2 0.85) sorts by conf — boosted (≈0.32) never displaces real
   high-conf boxes.

## GATES — declared before any build completes; numbers final

- **G-A1-i (flicker instrument kill gate — BEFORE any pass-1 compute):**
  `scripts/v2_flicker_instrument.py`: donors = confident full tracks
  from the base dump; their cache detections located by frame + IoU
  match; a contiguous flicker window of duration {1, 3, 8 s} per donor
  gets conf suppressed into the sub-activation band; decoys = cache
  detections in the same conf band matched to NO dump track (isolated
  background flicker). Run the stabilizer on the modified cache.
  PASS requires, on cam2 study_0700 AND study_1600:
    - recovery (suppressed detections re-boosted to >= activation)
      >= 0.60 aggregate AND >= 0.40 in every duration bin;
    - decoy false-boost rate <= 0.05;
    - parity: row count identical, non-conf columns byte-identical,
      no boosted detection outside a matched tubelet.
  Anchors: 0.60 must decisively beat do-nothing (0.0) for the flicker
  class the band analysis names; 0.05 mirrors the B1 decoy bar; the
  duration bins stop a trivial only-short-flicker pass. FAIL → block
  stops before a single tracking run (iteration 1 spent), ledger
  "rescore-only stabilization cannot recover the flicker class".
- **G-A1-a (counting gate, cam2 x3 vs committed d1ctrl 53.4/42.9/44.0):**
  5/95 >= control on all 3 AND >= +1.0 on at least one; EB_left err
  strictly reduced on all 3; NB_left reduced on >= 2 of 3; EB_right
  watch cell reported; phantom guard (added non-compliant phantom slots
  <= newly compliant slots, v2_phantom_diag).
- **ACTIVATION GUARD (standing law, activation-coupling-law):** the
  stabilizer changes track composition BY DESIGN → coverage WILL move.
  Record result.evidence_activation per arm; state flip vs control →
  that window VOID under default flags; run flag-off pairs
  (EVIDENCE_ACTIVATION_ENABLED=0 both sides; e4ctrlx controls already
  committed for 1100/1600, a fresh 0700 flag-off control exists as
  e4ctrlx too) and gate on the flag-off pair, reporting both frames.
- **Iteration budget 2 from zero.** Iteration 2 = gap interpolation,
  ONLY per the scope-discipline trigger above.

---

## ITERATION 1 INSTRUMENT RESULT (2026-08-13) — G-A1-i FAILED on decoys

cam2 study_0700: recovery 0.743 aggregate (0.717 / 0.762 / 0.739 by
duration — the PASS half: the linker holds through anchorless flicker),
but decoy false-boost **0.6085 vs the 0.05 bar**, with 651,993 of
2,563,403 detections boosted (25.4% of the stream; 10,645 of 28,962
tubelets eligible). Diagnosis is surgical: the ZV-STATIONARY eligibility
arm admits static debris — a recurring background false positive is
span-long, member-rich, dense, and "stationary-coherent" by
construction. This is the v2_tubelet flood signature (30-32%)
reproduced at detection level and caught BEFORE any tracking compute.
The pre-named iteration-2 trigger (missing frames) does NOT match;
recovery is healthy.

## ITERATION 2 (declared 2026-08-13 BEFORE re-running; 2 of 2)

ONE mechanism change: **the ZV-stationary arm is REMOVED from
eligibility** — eligible tubelets must satisfy the DISPLACEMENT
coherence test (net displacement >= own mean bbox diagonal), full stop.
B2 remains where it belongs: in the LINKING (zv_radius association gate
+ 3 s stationary coast), so a queued vehicle's stop is bridged and its
tubelet — which drives in and eventually out — passes the displacement
test naturally. What is knowingly given up: a stationary-for-its-entire-
observed-span tubelet is never boosted (that population is
overwhelmingly static debris + parked vehicles, both out of counting
scope; a >3 s mid-queue stationary fragment isolated by a linking break
also stays unboosted — same as today, recorded as the known ceiling).
GATE UNCHANGED (G-A1-i verbatim, both windows). If iteration 2 fails
the instrument, the block is DEAD and ledgered with both iterations
spent; gap interpolation is NOT reachable (its trigger never fired).

---

## ITERATION 2 RESULT + VERDICT (2026-08-13) — G-A1-i FAILED; BLOCK STOPS

cam2 study_0700, displacement-only eligibility: recovery 0.695
(0.666/0.692/0.699 by duration — still comfortably over the bar), decoy
false-boost **0.5290** vs 0.05; 570,218 detections boosted (22.2% of
the stream; 9,924 eligible tubelets). The static-debris hypothesis was
insufficient: the boosted decoys MOVE.

**Instrument-soundness finding (diagnostic, 3,000-det sample):** 71.5%
of ALL low-conf detections sit within 0.5 diag of a tracked vehicle's
point at the same frame; the "decoy" pool is the remainder — a
NEAR-TRACK HALO mixture of same-vehicle box offsets (raw-vs-smoothed),
shadows, adjacent UNTRACKED queue neighbors (the target class!), and
genuine debris, distributed 10.1% at [0.5,1) diag, 5.7% [1,1.5), 6.9%
[1.5,3), 5.8% beyond. Unlike B1's SYNTHETIC decoys (constructed
negatives), this negative class is observational and UNLABELABLE blind:
at detection level, "moving + coherent + persistent" IS the signature
of a plausible vehicle — there is no GT-free signal separating
faint-real from vehicle-shaped debris, which is the entire reason
detector confidence exists. The decoy metric therefore measures "boosts
on unlabeled halo detections", not false births. This is a limitation
of the INSTRUMENT CLASS (observational negatives at detection level),
not a fixable decoy generator.

**Verdict per the gate as declared: G-A1-i FAILED at iteration 2 of 2 —
the block is STOPPED with ZERO tracking runs.** What is proven and what
is not:
- PROVEN: the linker recovers anchorless flicker on known vehicles
  through 1-8 s suppression windows at 0.70-0.74 — the recovery half of
  the mechanism works.
- UNRESOLVED (and unresolvable pre-compute by this instrument class):
  the flood risk. The boost volume is the red flag the gate existed to
  catch — +22% of the stream, ≈ +39% additional birth-grade detection
  fuel — squarely matching the v2_tubelet flood precedent (30-32%) and
  the ft2 no-conversion precedent.
- Process note, recorded: the iteration-2 instrument run OVERWROTE
  iteration 1's flicker JSON (same stem — the scorer-stem trap, now bit
  an instrument). Iteration-1 numbers preserved in this doc; future
  instruments get iteration-tagged stems.

## LEDGER + the one sound falsifier (operator decision required)

**A1+B2 rescore-only is STOPPED at its kill gate, both iterations
spent.** Gap interpolation was never reachable. The mechanism is
neither proven dead (the failed metric is unsound as a negative bound)
nor deployable (the flood risk is real, precedented, and unbounded).

NAMED FOR THE OPERATOR — the cheapest SOUND falsifier, requiring
sign-off because this block's own gate said stop: ONE staged tracking
run (the H1 G-H1k pattern): pass-1 + pass-2 on `a1_study_0700` only
(~35 min), pre-declared kill-read BEFORE any further window: track
count within 1.5x of base (8,320), insufficient count within 1.5x of
base (2,442), 5/95 >= control 53.4 with cells_scored growth <= +3, and
the EB_left/NB_left deficit errors reduced. That read measures the
flood DIRECTLY (the tracker's own response) instead of proxying it
through an unlabelable decoy class. PASS there → resume the block's
counting gates on the remaining windows under the original G-A1-a.
FAIL → the rescore-only family is dead on real evidence.

## G-A1-f — the staged falsifier (OPERATOR-APPROVED 2026-08-13
## "keep going"; numbers final BEFORE the run)

One window: `a1_study_0700` (stabilizer output, iteration-2 eligibility)
→ pass-1 (cam2's own calib recipe: botsort nms 0.85 match 0.9) → pass-2
(default flags, the d1ctrl basis) → score, stem `a1_cam2_study_0700`.
Kill-read, ALL required (base figures from the reproduced h1base run):
  (f1) tracks <= 12,480 (1.5 x 8,320)      — the direct flood meter
  (f2) insufficient <= 3,663 (1.5 x 2,442) — the conversion meter
  (f3) 5/95 >= 53.4 AND cells_scored <= 106 (control 103 + 3)
  (f4) EB_left |err| < 14 AND NB_left |err| < 63 (both reduced)
ACTIVATION GUARD standing: the a1 dump's coverage WILL move; record
evidence_activation; state flip vs control (ON, 0.564) → the f3/f4
comparison re-runs on the flag-off pair (e4ctrlx_cam2_study_0700 = the
committed flag-off base control, 48.1 50/104).
PASS all four → the block RESUMES: remaining windows under G-A1-a.
ANY fail → the rescore-only family is DEAD on direct evidence; ledger
closes with the flicker-instrument findings attached.

## Cost and mechanics

Stabilizer run: minutes/window (pure pandas/numpy over the parquet).
Pass-1 botsort cam2: ~15-30 min/window x3 (detached + Monitor); pass-2
~6-8 min x3; instrument minutes. Sequential (memory). Copy NOTHING: the
a1_ parquet is a new file; pass-1 resolves the cache by the a1_ variant
name (the parquet exists → no re-detect). Workdirs
`_replay_scratch/a1_tubelet/<arm>_<win>/`, stems `a1_cam2_<win>` /
flag-off `a1x_cam2_<win>`. WAL-safe copies; delete twopass_ originals
after scoring. All chain scripts + score JSONs committed.
