# THE FIRST-EXIT RULE (2026-09-08) — G-FX-1 declared

Operator: "it crosses the n and then crosses the s... it may kind of
jitter over the s a bit, but it never goes all the way back to n.
And it shouldn't matter because it went from n to s, period."

Root cause, one line in entry_gates.classify(): origin = entries[0]
(FIRST) but dest = exits[-1] (LAST), so a stolen box rewrites a
finished journey. Verified on tid 238765: N-in -> S-out in 4.3 s,
then parked 120 s in the far-field queue before a different vehicle
(box 31x14 -> 75x48) carried the id across N three minutes later.

Measured first-vs-last exit:
  cam3 0600: 406 changes — N->N becomes N->S x322, S->S becomes S->N
             x55 (the phantoms), only 12 counter-moves
  cam2 1600: 366 changes — N->N becomes N->S x129 BUT W->S becomes
             W->W x69 (a same-leg GRAZE that would mint u-turns)

RULE: a journey ends at its first LEGITIMATE exit. A different-leg
exit is legitimate at once; a SAME-leg exit only if it passes the
u-turn tests classify() already applies (dwell + excursion + lane
shift). A failing same-leg exit is jitter — skipped, keep looking.
Flag JOURNEY_FIRST_EXIT, default OFF.

## G-FX-1 (declared before any scoring; two iterations)

1. cam3 0600: SB u-turns collapse toward Mio 0; movement beats the
   fleet-arm 85.4.
2. cam2 x3: u-turn cells collapse toward Mio (1/0/1) and EB_right
   does not worsen; movement beats 70.5 / 73.9 / 72.3.
3. cam1 0700 + 1600 (SHIPPED): regression check only — neither may
   fall below 83.5 / 95.3.
Cell tables + phantom-slack check every arm; growing sub-10-Mio cells
are failures. Approach never decisive.

## Verdict

(to be recorded)

## G-FX-1 verdict (recorded 2026-09-08): PARTIAL — MISS on the gate

Arms run with the shipped flag set + JOURNEY_FIRST_EXIT. Comparison
is against the FLEET ARM (same flags, rule off), which is the honest
measure of the rule's own effect.

  cam3 0600   85.4 -> 86.2  (+0.8)   SB_uturn 88 -> 38, NB_uturn 33 -> 28
  cam2 0700   70.5 -> 68.2  (-2.3)
  cam2 1100   73.9 -> 75.2  (+1.3)
  cam2 1600   72.3 -> 69.9  (-2.4)   EB_uturn 23 -> 17
  cam1 0700   83.5 -> 83.3  (-0.2)   SHIPPED window, marginal slip
  cam1 1600   95.3 -> 95.3  (0.0)    SHIPPED window, held

THE RULE DOES WHAT IT WAS BUILT TO DO: the u-turn phantom class it
targets is roughly HALVED on the specimen (cam3 SB 88 -> 38) and cam3
gains +0.8. But it does not clear the declared gate: cam2 regresses
on two of three windows, and cam1-0700 slips 0.2 below its shipped
83.5. MISS.

WHY THE SURVIVORS SURVIVE (provenance of cam3's remaining 44
u-turn events):
    N->N  src=None       23
    S->S  src=gate_full  21
    N->N  src=gate_full  15
    S->S  src=None        7
    W->W  src=None        6
36 of 72 carry 'gate_full' — the gate evidence itself still calls
them u-turns, meaning their FIRST legitimate exit really is the same
leg and it PASSES the dwell/excursion/lane tests. So the remainder is
not the theft-after-journey shape this rule addresses; it is either
genuinely u-turn-shaped motion in the far-field queue, or the u-turn
admission tests themselves being too permissive at that distance.
That is a separate diagnosis, not a tuning knob on this rule.

Flag stays default OFF. Nothing shipped. One iteration of the
declared budget remains, unspent pending operator direction.

## OPERATOR RULINGS ON THE SURVIVORS (2026-09-08)

Clip 1 (tid 123908): a PROPER u-turn. Real. He also noted a genuine
  visual signature: on a u-turn the two bottom corners CRISSCROSS.
Clip 2 (tid 308574): a THEFT. It is a LEFT TURN; the box loses the
  dark vehicle mid-intersection, LINGERS there, and a much faster
  through vehicle takes it. "One is moving slow, that's making the
  turn... the second thief is moving way, way faster."
Clip 3 (tid 296206): PROGRESSIVE THEFT — a NEW mechanism. A white
  truck waits to turn; through traffic repeatedly crosses in front of
  it, and with each crossing the bounding box CREEPS further into the
  intersection until it is fully taken. Not a single hand-off:
  incremental drift under repeated occlusion.

## DISCRIMINATOR TEST (his two candidate signals, measured)

                              speed ratio    corners cross
  REAL u-turn   (123908)          1.2            yes
  THEFT         (308574)          6.4            yes
  THEFT         (296206)          2.6            no

SPEED CONSISTENCY SEPARATES THE REAL ONE; the crisscross does not
(it is a true property of u-turns, but a theft also reverses
direction, so both show it). A real u-turn holds a steady slow speed
throughout; a theft shows a large speed discontinuity where the box
changes vehicles.

CANDIDATE RULE (not built): add speed consistency to the u-turn
admission tests, which already check dwell + excursion + lane shift.
A "u-turn" whose median speed changes by >= 3x between its first and
second half is a theft, not a turn. Caveat: only 7 gate_full u-turns
on cam3 carry enough data to measure, 3 of them >= 3x — a small
sample, and the threshold needs a real sweep before it is trusted.

The wider principle worth banking: a large speed discontinuity WITHIN
one journey means the box changed vehicles. That is not specific to
u-turns.

## CORRECTION (operator, 2026-09-08): clip 3 DOES crisscross

He: "clip three does actually have a crisscross in box corners... It
doesn't make it correct. The errors I described are still there, but
that's what happened."

He is right; my test was wrong. It sampled every SECOND segment for
speed and missed the single intersection point. Exhaustive re-test of
the corner-path intersections:
  clip 1 REAL   journey 1  (full track 4)
  clip 2 THEFT  journey 1  (full track 1)
  clip 3 THEFT  journey 1  (full track 1)
ALL THREE crisscross exactly once across the journey.

CONSEQUENCE — this STRENGTHENS the earlier conclusion rather than
changing it: the crisscross is a universal property of any
reversal-shaped track (real turn or stolen box alike), so it can
never discriminate. SPEED CONSISTENCY remains the only signal that
separated the real u-turn (1.2x) from the thefts (6.4x, 2.6x).

INSTRUMENT LESSON (second false reading caught by the operator
today): a sampled geometric test reports a false NEGATIVE on a
single-point property. Corner-path intersection must be exhaustive.
