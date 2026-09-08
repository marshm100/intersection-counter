# FLEET FLAG ADOPTION (2026-09-08) — G-FLEET-1 declared

cam1-0700 shipped today at 83.5 (from 75.0) running the three
operator-derived rules together. The other 11 production windows
still run with all three OFF. This offers each the same flag set and
ships only what wins.

Live activation state (from the pass-2 sidecars):
  cam1 1600 0.588 ON | cam2 0.569/0.485/0.489 ON | cam3 0.547 ON
  cam4 0.304/0.442/0.318 ALL OFF  <-- the prize (6,636 dropped)
  cam5 0.509/0.560/0.578 ON

## G-FLEET-1 (declared before any scoring; two iterations)

PASS IS PER WINDOW: movement pct beats the live standing (cam1 1600
86.2; cam2 70.4/71.3/70.3; cam3 83.7; cam4 75.4/73.5/75.8; cam5
66.4/71.7/63.1); big real cells shrink or hold; NO phantom-slack
minting (sub-10-Mio cells passing on the +-5 slack are not wins;
NB_right-style growth fails the window); approach reported, never
decisive. Missing windows keep their basis, no penalty. cam5 windows
additionally require their phantom cells to hold (the standing HOLD).

## Verdicts

(to be recorded per window)

## G-FLEET-1 verdicts (recorded 2026-09-08)

Headline movement, live -> flags:
  cam1 1600  86.2 -> 95.3  (+9.1)
  cam2 0700  70.4 -> 70.5  (+0.1)   cam2 1100 71.3 -> 73.9 (+2.6)
  cam2 1600  70.3 -> 72.3  (+2.0)
  cam3 0600  83.7 -> 85.4  (+1.7)
  cam4 0700  75.4 -> 64.7  (-10.7)  cam4 1100 73.5 -> 79.2 (+5.7)
  cam4 1600  75.8 -> 72.9  (-2.9)
  cam5 0700  66.4 -> 72.9  (+6.5)   cam5 1100 71.7 -> 71.4 (-0.3)
  cam5 1600  63.1 -> 70.1  (+7.0)

After the mandatory phantom check, ONE window passes:

PASS — cam1 study_1600: 86.2 -> 95.3, approach 78.1 -> 86.7.
  The driveway phantom class COLLAPSED: NB_right 102 -> 15 (Mio 2),
  WB_right 26 -> 1 (Mio 2), EB_thru 15 -> 0 (Mio 1). Big cells
  improved: NB_thru 1993 -> 2128 (Mio 2078), EB_right 492 -> 496
  (Mio 497). SB_thru held at 2541 (Mio 2498). Scored cells FELL
  94 -> 85 while compliant held at 81 — fewer phantom cells to
  score, the opposite of slack-gaming. Only blemish: NB_uturn 3 -> 9
  (Mio 1).

FAIL — cam4 study_1100 (+5.7 headline): SB_right 64 -> 125 against
  Mio 16, and the worst bins are SB_right minting 20/0, 17/1, 16/1.
  A phantom class growing, so the window fails the 2026-09-07 law
  despite the headline.
  MY AUTOMATED FLAGGER MISSED THIS — it only checked cells with
  Mio < 10 or Mio >= 100, leaving a blind band. Caught by reading
  the full table, which is why the cell table is mandatory.
FAIL — cam2 x3: EB_right already blown and worsens (316/477/991 vs
  Mio 167/351/699) plus u-turn phantoms growing (EB_uturn to 14/10/23
  vs Mio 2/0/1; NB_uturn 2 -> 10).
FAIL — cam3 0600: EB_left improves (494 -> 361 vs Mio 196) but
  SB_uturn explodes 27 -> 88 against Mio 0, NB_uturn 15 -> 33 (Mio 8).
FAIL — cam5 0700/1600 (+6.5/+7.0): NB_left blows further, 270 -> 424
  (Mio 335) and 224 -> 381 (Mio 240) — the curved-fragment phantom
  class the standing HOLD exists for.
FAIL — cam4 0700 (-10.7), cam4 1600 (-2.9), cam5 1100 (-0.3):
  headline regressions; channels stayed OFF on both cam4 windows
  (0.366, 0.352), so the corner fix did not reach them.

SHIP CANDIDATE: cam1 study_1600 only.

## SHIPPED — cam1 study_1600 (operator go, 2026-09-08)

Backup: backups/project_20260908T141254_pre_ship_c1eve.db.
Applied via force_once (the reference-free gate stands down; the
Miovision-scored evidence + operator go outrank it). events 5,855,
coverage 0.584, channel ACTIVATED.

Production cells (was -> now):
  NB_thru   1993 -> 2128   (Mio 2078)
  SB_thru   2542 -> 2541   (Mio 2498)
  EB_right   492 ->  496   (Mio  497)
  EB_left    100 ->  115   (Mio  105)
  22->25 right (driveway) 102 -> 15   (Mio 2)
  25->23 right             26 ->  1   (Mio 2)
  total counted 5,671 -> 5,702
Scored basis: movement 86.2 -> 95.3, approach 78.1 -> 86.7.

Isolation byte-verified: cam1 morning 4,687 unchanged; cameras 2-5
byte-identical to the backup. Health rewritten: cam1-1600 GREEN
(first green window in the corridor), cam1-0700 amber. Worklist
rebuilt 78 -> 71 open.

OPERATING NOTE: both cam1 windows now require
GATE_GROUND_ANCHOR=1 STRAIGHT_FRAGMENT_RULE=1
GATE_EVIDENCE_EITHER_CORNER=1 to reprocess.

CORRIDOR STANDINGS: cam1 83.5 / 95.3 | cam2 70.4 / 71.3 / 70.3 |
cam3 83.7 | cam4 75.4 / 73.5 / 75.8 | cam5 66.4 / 71.7 / 63.1.

## U-TURN PHANTOM CLASS — filmed for operator ruling (2026-09-08)

The binding blocker across four windows (cam2 x3 + cam3). cam3
study_0600 is the clearest specimen: N->N 88, S->S 33, W->W 6, against
Miovision ZERO southbound u-turns.

Forensics on the largest N->N events: net heading change -170 to
-175 deg (a FULL REVERSAL), path distances 900-1,600 px, 340-1,616
tracked points. One (tid 238765) carries posterior_source
'gate_full' — the gate evidence itself confirmed it, so the machine
is confident about a journey that may never have happened.

A -174 deg reversal is the identity-swap signature (the flip
monitor's PINCH_ANGLE is 120 deg) — but the flip monitor only runs
under the botsort_locked recipe, and cam3 does not use it. So on
cam3 a theft turns into an apparent u-turn with nothing to sever it.

Filmed centred on the reversal frame (scripts/viz_c3_uturns.py):
tids 238765, 11247, 242488. Awaiting the operator's ruling on whether
these are one vehicle turning around or the box jumping to an
oncoming vehicle.

## OPERATOR RULING ON THE U-TURNS (2026-09-08) — all three are THROUGHS

His words: "it crossed the mouth, and it crossed the southern gate of
the intersection. So it should be a through. It should not be a
U-turn." And on the mechanism: traffic queues back from the NEXT
intersection past the exit gate, so the far-field queue is a row of
parked cars the detector confuses at distance — plenty of theft, but
none of it pertinent to a journey that already finished.

VERIFIED — the crossing sequences say exactly that:
  tid 238765  N-in @590493 -> S-OUT @590536 -> S-in @592257 -> N-OUT @592279
  tid 242488  N-in @593199 -> S-OUT @593253 -> S-in @593715 -> N-OUT @593736
Each vehicle ENTERED over N and EXITED over S within 4-5 seconds — a
complete through journey. Then 172 s (238765) and 46 s (242488)
LATER the same track id re-enters over S and exits over N: the box
being re-used by the far-field queue, long after its vehicle was
gone.

ROOT CAUSE, one line: entry_gates.classify():
    origin = entries[0] if entries else None
    dest   = exits[-1]  if exits   else None
The origin takes the FIRST entry but the destination takes the LAST
exit. So any post-journey theft rewrites the destination and, when it
re-crosses the entry leg, manufactures a U-TURN out of a finished
through.

THE RULE THIS IMPLIES (the operator's pertinence law, stated for
time): a journey ends at its FIRST exit after its entry. Crossings
after that belong to another vehicle and must not rewrite it —
dest = the first exit with dest[0] > origin[0].

Third clip (tid 11247) is a different bug worth noting: its sequence
is N-in -> S-OUT -> S-in, and classify ALREADY returns N->S 'full'
(a through) — yet the event was booked u_turn. There the gate
evidence was correct and something downstream overrode it, the same
shape as the invented-origin class on cam5.

Not implemented; this is the next candidate build.

## CORRECTION (operator, 2026-09-08): the VEHICLE never returns

I wrote that the track "re-enters over S and exits over N". Wrong
wording — the operator: "it crosses the n and then crosses the s. And
then it may kind of jitter over the s a bit, but it never goes all
the way back to n. That never happens."

He is right, and the dump proves it for tid 238765:
  f590493  (120,309)  box 208x108   crosses N inward
  f590536  (390,170)  box  35x24    crosses S outward  <- journey done
  f590788..f591988    (~397,155)    PARKED for 120 s  <- his queue
  f592257  (277,154)  box  31x14
  f592279  ( 33,221)  box  75x48    crosses N outward
The box goes 31x14 -> 75x48 at that last crossing: a DIFFERENT
VEHICLE. The original went N to S in 4.3 s and never came back; the
track id was picked up by something else in the far-field queue and
carried across the N line 3 minutes later.

(My clip also mis-served him: it centred on frame 591677 +-7 s, so
the crossing at 592279 was ~60 s past the end of what he watched. He
ruled on what the film showed, correctly.)

THE RULE, in his words: "it went from n to s, period. End of story."
= a journey ends at its FIRST exit after its entry; nothing after
that can rewrite it. Same one-line site: entry_gates.classify(),
dest = exits[-1] -> the first exit with dest[0] > origin[0].
