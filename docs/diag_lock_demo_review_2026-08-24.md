# Operator review of the Stage-4c lock demo (2026-08-24) — three rulings

The three demo scenes were reviewed by the operator. None of the three
reads matched the builder's captions; all three rulings are now law.

## Ruling 1 — a healed re-find is a CLAIM, not a win (image 1, tid 4113)

The re-found vehicle sat in a lane that serves both through and turning
traffic; the path "lingers off, sees a parking car in a parking lot,
then estimates back to the left-turn gate." Verdict: 50/50 whether the
joined journey is a real turning vehicle or a through vehicle's error.
Measured after the read: the re-claim tolerance formula
max(35, 0.6*speed*gap) was designed for 1-2 s latch gaps; over long
occlusions it balloons — 387 of 1,162 long-gap re-finds had a claim
cone wider than two lanes (>80 px). Those are lotteries. And even a
tight claim (4113's jump was 15 px) is unproven in a dense queue.

LAW: an occlusion-bridged identity join must never, by itself, assert a
journey. The bridged interval is UNOBSERVED; a gate crossing that falls
inside it is synthetic evidence — the same physical-crossing law already
shipped in the cutter (rev 6), now stated at the tracker/counting level.

## Ruling 2 — queue identity is provisional until the mouth (image 2)

"We do not know if these are the same vehicle or not due to the dense
clustering of the queue... it should be viewed with skepticism until
the vehicle reaches the mouth and then is in motion in the
intersection."

LAW: the trust boundary is the MOUTH. Identity in the approach queue is
scaffolding; countable identity begins where the vehicle enters the
intersection in motion. This is the original gate architecture restated:
observed, in-motion crossings are the only evidence.

## Ruling 3 — continuous drift-theft, a class the gate cannot see
## (image 3, tid 97)

Operator read: a clear thief — the detection is born in the roadway of
vehicles LEAVING the intersection, then drifts over into oncoming
traffic, then tracks that vehicle to the mouth and logs its left turn.
Builder's honest boundary: this steal is a CONTINUOUS drift (the box
slides between overlapping vehicles without the track ever going lost),
so the re-association gate never fires — no loss event exists. Only a
post-hoc motion test (the pinch/flip family) or the counting-stage
evidence rules can catch this class.

## Design consequences (for the G-LP-1 arm design)

1. Cap the re-claim cone: stationary-scale radius always; never
   gap-scaled growth (kills the 387 lottery claims).
2. A re-found join must never mint gate evidence: crossings whose
   bracketing observations straddle the bridged gap are not evidence
   (physical-crossing test at the evidence reader).
3. The counting anchor stays at the mouth; queue-side identity is
   provisional and must not upgrade a journey on its own.
4. Continuous drift-theft is out of the re-association gate's reach by
   design — ledgered as the residual class for the evidence rules.
