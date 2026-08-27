# Fragment rejoiner — design thoughts (2026-08-26, NOT a plan)

Recorded at the operator's request after the G-ID-1 MISS, before any
build decision. These are candidate ideas plus the constraints the
measured record imposes. Everything below marked [inference] is
untested reasoning, not measurement.

## What the fragments actually are (from the break records)

The arm's ~23.5k tids at 1600 decompose into three classes with
different rejoin verdicts:

1. **Flip-severed pairs** (the monitor's cuts, validated 26/29 on the
   labeled thefts): victim | thief. NEVER rejoin across a recorded
   flip break — the break list (gate_breaks.json, absolute frames) is
   a hard wall. Rejoining these re-creates the theft.
2. **Probation-break pairs** (claims judged wrong post-resume): the
   claim was refuted by motion evidence. Do not rejoin blindly —
   [inference] some are honest vehicles whose resume looked wrong,
   but the probation judgment is the better-informed side.
3. **Refused re-finds** (the mover claim-cone cap: movers re-claimable
   only 3 s / 70 px): the same physical vehicle continuing after a
   long occlusion now gets a FRESH id instead of a lottery join.
   [inference] This is the dominant rejoinable mass — the cone cap
   was the honest replacement for the IoU lottery, and the refused
   joins are where the innocent journey halves live.

## The structural insight worth keeping

Severs happen MID-INTERSECTION (thefts flip at the theft point,
occlusions happen in the queue and the box), while the drawn gates sit
at the mouths. So rejoining an innocent pair usually spans NO gate
line — the A2 straddle rule (a join may not span a gate) stays intact
as the safety boundary, and a correct rejoin restores a journey whose
entry AND exit crossings are both OBSERVED. That is exactly the
paired evidence whose absence killed activation (0.26-0.35 vs the
0.45 bar). [inference] Therefore the rejoiner has a measurable
INTERMEDIATE gate that is cheaper and sharper than a score run:
evidence-activation coverage per window must return above 0.45 on
rejoined dumps. If coverage does not recover, the score cannot — kill
early, no replay spend.

## Join predicate — what the record allows and forbids

- FORBIDDEN: proximity/time-window gluing (CHAIN_GLUE caterpillar,
  measured negative: queue neighbors chain into one vehicle).
  Appearance/ReID (measured dead at this resolution: twin AUC 0.399).
- AVAILABLE, in rough order of strength [inference]:
  - Motion continuity under the physics already encoded in the
    recovery costs: constant-velocity extrapolation of A's end state
    to B's birth, error bounded by pre-loss speed + allowance, gap
    bounded by the lost buffer. The cone cap refused these joins
    LIVE because a wrong live join is unrecoverable; a POST-PASS can
    afford a wider cone because it sees B's whole future — direction
    agreement over B's entire early track, not one detection.
  - The flip test applied to the HYPOTHETICAL joined track: join,
    run displacement_chords over the seam; any >PINCH_ANGLE pair at
    the seam = the join manufactures a theft signature = refuse.
    (The cutter as join-verifier — same validated constant, run in
    reverse.)
  - Class consistency and box-size continuity at the seam (weak,
    tie-breakers only).
- One-to-one discipline: each fragment end joins at most one fragment
  start (Hungarian over the candidate graph, infeasible pairs masked)
  — no chains-of-chains in v1 [inference: chains reintroduce
  caterpillar risk].

## Where it runs

In the dump post-pass beside the existing re-stamp machinery
(two_pass run_pass1 tail) or as a standalone dump transform — NOT
live in the tracker. The live tracker stays honest-severing; the
rejoiner is a separate, testable, flag-gated stage with its own meta
(joins, refusals by reason, seam-flip refusals). The labeled-splice
harness must stay 26/29 on rejoined dumps (thefts must NOT rejoin) —
that is the standing acceptance alongside the coverage gate.

## Cost honesty

[inference] This is the hardest mechanism family yet: the G-TR glue
family closed at two scored MISSes, and this is a smarter cousin with
more constraints. Expect multiple demo-driven iterations before any
score run. The intermediate coverage gate + harness make each
iteration cheap to judge, but the family could still close negative.
The alternative uses of the same effort are the fleet-gate track
(measured-positive mechanism, four cameras untouched) — direction is
the operator's call, recorded in the roadmap.
