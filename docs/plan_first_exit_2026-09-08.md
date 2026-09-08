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
