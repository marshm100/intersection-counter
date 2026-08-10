# Plan — GATE ORIENTATION FROM THE TRACKS' OWN AXIS (2026-08-10)

Successor to the FM51 geometry diagnosis (plan_v2_apply_gate_2026-08-07,
final section). That diagnosis found a defect wider than FM51: the entry
gates are oriented from OPERATOR-drawn artifacts, and both available
artifacts are unreliable — including on the corridor, where the shipped
chain uses this evidence every run.

Measured, gate normal vs the direction traffic actually travels
(0 deg = gate correctly ACROSS the road; 90 deg = gate lies ALONG it, so
vehicles slide out of its span instead of crossing):

  camera / leg          channel tangents (shipped)   reference_heading
  FM51 leg 1                     77.9                      4.6
  FM51 leg 2                     85.4                     87.1
  FM51 leg 3                      0.1                      1.5
  corridor cam2 leg 26            2.5                     20.0
  corridor cam2 leg 27            1.6                      0.7
  corridor cam2 leg 28           23.8                     52.4
  corridor cam2 leg 29           55.0                     32.9
  corridor cam4 leg 33           49.4                     58.3
  corridor cam4 leg 34            4.0                     30.5
  corridor cam4 leg 35            4.9                     25.6

Neither source dominates; they fail in different places and at cam4 leg
33 they fail together. The one quantity correct by construction is the
TRACKS' OWN travel axis — it is the yardstick every number above was
measured against. This block derives the gate orientation from it.

> **[SUPERSEDED — read the BLOCK VERDICT first.] The table above is
> WRONG.** It was computed with a naive mean of unit displacement
> vectors, which cancels on bidirectional mouth traffic. Under the
> correct axial estimator the corridor figures largely dissolve (cam2 leg
> 29: 55.0 -> 1.6 deg; cam4 leg 33: 49.4 -> 3.1-6.6 deg; FM51 leg 2: 85.4
> -> 13.2 deg). It is kept here, uncorrected, because it is what the block
> was launched on; the verdict section carries the corrected numbers and
> the premise it refutes.

## Why this is worth a block (the prize, sized honestly)

Gate evidence feeds four shipped consumers: merge expecteds
(census_expecteds), the V2 demotion selector's census + confusion,
conserve_pass chains, and now the apply gate's envelope. It also gates
itself: EVIDENCE_ACTIVATION_COVERAGE = 0.45 decides whether a camera gets
the proven gate+posterior attribution pair at all. Recorded coverage:
cam2 0.487 (ACTIVE), **cam3 0.431**, **cam5 0.402**, cam1 0.265, FM51
0.031. cam3 is denied the evidence gate by 0.019. If better orientation
lifts cam3/cam5 across the bar, that is a real accuracy change in the
shipped chain, not a tidier number. If it does not, the block ledgers a
measured-dead channel and the corridor keeps today's behavior.

NOT a goal: rescuing FM51. Its binding constraint is track length (3.6%
of tracks are long enough to span the intersection); orientation is worth
at most ~0.135 coverage there against a 0.45 bar. FM51 is measured here
only as a negative control.

## Mechanism

For each leg mouth, estimate the ROAD AXIS from the window's own tracks:

1. Collect tracks passing within AXIS_RADIUS_PX of the mouth; take each
   one's displacement across that neighbourhood, drop those shorter than
   AXIS_MIN_DISP_PX (parked/jitter).
2. **Doubled-angle (orientation) averaging.** Traffic through a mouth is
   BIDIRECTIONAL — inbound and outbound vectors are ~antiparallel, so a
   naive mean cancels to noise. Average (cos 2t, sin 2t) instead and
   halve the result: the standard axial-statistics estimator, which is
   direction-sign blind by construction and therefore correct for a gate
   (the gate needs an axis; build_gates already derives the inward SIGN
   separately, from the mouth centroid).
3. **Support floor.** Require >= AXIS_MIN_TRACKS contributing tracks AND
   resultant length >= AXIS_MIN_R (axial concentration — a mouth where
   traffic has no dominant axis must not invent one). Below either, fall
   back to today's channel-tangent mean, byte-identical.
4. The axis is computed ONCE per (camera, dump) BY THE CALLER and passed
   in. It is never derived lazily inside the pipeline.

Constants are window-derived where possible and otherwise declared here
before measurement: AXIS_RADIUS_PX = 90 (the probe radius that produced
the table above), AXIS_MIN_DISP_PX = 8, AXIS_MIN_TRACKS = 30,
AXIS_MIN_R = 0.30. Flag V2_GATE_AXIS, default OFF.

## The stability constraint (why "inject, never derive lazily")

pipeline._ensure_entry_gates carries a hard-won rule: gate geometry must
be STABLE against changes in candidate inputs — one added path's mouth
tangents once moved origin_evidenced 4691 -> 2628. A track-derived axis
is window-dependent by nature, which is exactly the class of instability
that rule protects against. Design consequences, binding on this block:
- The axis enters through an explicit injection point
  (pipe._gate_axes, mirroring the existing pipe._gate_paths precedent),
  set by the pass-2 caller that already holds the complete dump.
- It is a pure function of (mouths, dump rows, constants) — no bank, no
  candidate paths — so injecting or ablating candidate paths cannot
  rotate a gate. G-OR4 tests exactly this.
- SCOPE: this block touches the OFFLINE/pass-2 evidence path only
  (two_pass census functions + the injected replay gates). The LIVE
  first-pass pipeline has no completed track set when it builds gates and
  is left untouched — its behavior is unchanged with the flag on or off.

## Pre-declared gates (all four; nothing ships unless all pass)

- **G-OR1 (evidence, the point of the block).** Across every corridor
  camera-window measured: no camera's strict full-journey count or blind
  coverage DECREASES beyond noise (>2%), and at least ONE camera improves
  materially (>=5% relative). A wash = the channel is inert -> LEDGER it
  and stop; do not ship a neutral change to shipped-chain geometry.
- **G-OR2 (accuracy tripwire).** 5/95 on the three cam2 windows must not
  regress vs their current controls. The census feeds merge expecteds and
  the demotion dose, so this is where damage would surface first.
  Sibling-cell inspection mandatory on any cell that moves (the standing
  rule since the lane-filter confound).
- **G-OR3 (gate integrity).** The apply-gate corridor validation, re-run
  with the new censuses, stays 11/11 binding. The gate's own envelope
  changes under this mechanism; if its adjudication degrades, the
  mechanism costs more than it pays.
- **G-OR4 (stability, the fill-arm rule).** (a) determinism: same camera
  + same dump twice -> byte-identical axes; (b) candidate-independence:
  injecting an extra candidate path must not change any axis.
- Scope guard: flag default OFF, scratch only, production tables and the
  live pipeline path untouched for the whole block.

## Sequencing

1. This plan doc (commit 1).
2. derive_gate_axes + build_gates axis parameter + wiring + unit tests
   (commit 2) — including the bidirectional-cancellation test that
   motivates the doubled-angle estimator.
3. Corridor + FM51 measurement against G-OR1..4, verdict appended here
   (commit 3). Ship or ledger on that evidence.

Rider (independent of the gates above, shipped either way): surface the
per-camera gate-evidence coverage the product already computes, so an
operator can see when a camera cannot produce gate evidence. Today both
the evidence channel and the apply gate stand down silently — the same
"judgment lives in docs, not the product" failure the 07-31 blind test
punished.


## BLOCK VERDICT (2026-08-10) — G-OR1 FAILED. Mechanism LEDGERED, and the
## diagnosis that motivated it is CORRECTED

**G-OR1 FAIL, decisively.** Track-derived orientation vs the shipped
channel tangents, full gate-to-gate journeys per window
(runs/v2_week1/gate_axis_measurement.json):

  cam1 0700 1154->1257 (+8.9%)   cam1 1600 2719->2736 (+0.6%)
  cam2 0700 3474->3439 (-1.0%)   cam2 1100 2428->2456 (+1.2%)
  cam2 1600 3354->3251 (-3.1%)
  **cam3 0600 17035->3132 (-81.6%)**
  cam4 0700/1100/1600 +3.7% / +0.9% / +0.8%
  cam5 0700/1100/1600 -0.5% / +0.0% / +0.1%
  FM51 AM 54->61, PM 0->18 (from a base that is broken either way)

The gate said no camera may lose more than 2% and at least one must gain
5%. cam3 loses 81.6%. LEDGERED: V2_GATE_AXIS stays default OFF, the code
stays for the record (the V2_TIMELOCAL precedent). G-OR4 (determinism +
candidate-independence) passes in unit tests; G-OR2/G-OR3 were never
reached because G-OR1 is the entry gate.

**WHY it fails is the block's real product: "perpendicular to local
travel" is REFUTED as the design target.** At cam3 the derived axis
matches measured travel EXACTLY (0.0 deg by construction, axial
concentration 0.91-0.94 over n=36212 tracks at leg 31) while the shipped
channel tangents sit 12-21 deg off it — and the "wrong" gates produce
17035 full journeys against 3132. The tag redistribution names the
mechanism: entry_only jumps 4140 -> 13055 while full collapses, i.e.
tracks still enter but no longer reach an exit gate. A gate square to
the local motion of nearby traffic is NOT the same object as a gate
across the roadway at the mouth line, and the difference is worth 5.4x
on this camera. Nothing in this block justifies preferring the former.

**CORRECTION to the 2026-08-10 FM51 geometry diagnosis (important).**
The orientation-error table that motivated this block — "channel tangents
23.8-55.0 deg off actual travel on the corridor" — was computed with a
NAIVE MEAN of unit displacement vectors. Mouth traffic is bidirectional,
so that estimator partially cancels and is invalid; this block's own
mechanism section is where the correct (axial) estimator got written
down. Recomputed axially, the corridor gates are nearly right and the
reported errors largely dissolve:

  claim (naive)                 corrected (axial)
  cam2 leg 29  55.0 deg    ->   0.2-1.6 deg
  cam2 leg 28  23.8 deg    ->   13.3-13.5 deg
  cam4 leg 33  49.4 deg    ->   3.1-6.6 deg
  FM51 leg 2   85.4 deg    ->   13.2 deg
  FM51 leg 1   77.9 deg    ->   50.0 deg (still a genuine outlier)

Surviving outliers worth a future look, on the corrected measure only:
FM51 leg 1 (50 deg) and cam1 legs 22/25 (42 / 88 deg). The claim that
"the corridor's gates are misoriented too" does NOT survive; it was an
artifact of my estimator, and the earlier FM51 write-up is amended by
this section rather than rewritten, so the error stays on the record.

**Consequences.**
1. Gate orientation is NOT a live accuracy lever. cam3 was the prize
   (0.431 vs the 0.45 activation bar) and this mechanism moves it the
   wrong way (coverage 0.456 -> 0.349 on the same proxy).
2. Any future attempt must first DEFINE the target orientation properly —
   the roadway's local tangent at the mouth line, from a fitted
   centreline — and must not use "mean local motion" as ground truth. A
   radius sweep (90/60/40/25/15 px) shows the motion axis does not
   converge on the channel tangent and moves in different directions at
   different legs, so it is not a stable target at all.
3. The FM51 conclusion is unchanged and independently supported: its
   binding constraint is track length (3.6% of tracks long enough), not
   orientation.
