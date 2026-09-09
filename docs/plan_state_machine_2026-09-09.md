# THE JOURNEY STATE MACHINE (2026-09-09) — G-SM-1 declared

Operator rules (his ruling of cam2 track 17526, end to end):
  R1 a crossing counts only when BOTH bottom corners cross the line
  R2 EXITED IS TERMINAL — once a vehicle has left, its id can never
     re-enter
  plus his approved split: accept a single-corner crossing when the
  TRACK ENDS there (truncated by tracking loss, not by the vehicle
  staying put).

Measured basis — solo (one-corner) crossings by what follows:
                  corner gap        ends <1s      continues >100f
  cam1 (10fps)  med 2f p99 21f        50%              9%
  cam2 (25fps)  med 9f p99 64f         6%             79%
The cameras are mirror images: cam1's solos are departures (which is
why either-corner earned it +8.5/+9.1), cam2's are wobble. The
truncation split is the single rule correct on both.
Straddle signature (corners disagree on direction over one line): 28
on cam1, 96 on cam2 — impossible for a genuine crossing.

Constants: CORNER_PAIR_WINDOW_S = 2.5 (p99 of the observed gap on
both cameras), CROSSING_TRUNCATION_S = 1.0 (where the two populations
separate 50% vs 6%).

SUPERSESSION: this flag subsumes GATE_GROUND_ANCHOR,
GATE_EVIDENCE_EITHER_CORNER and JOURNEY_FIRST_EXIT. It is validated
against the SHIPPED combination, never against bare defaults.

## G-SM-1 (declared before any scoring; two iterations)

1. cam1 0700 + 1600 — SHIPPED. HARD CONSTRAINT: neither may fall
   below 83.5 / 95.3.
2. cam2 x3 — EB_right excess (+169/+93/+310 vs Mio) must shrink and
   u-turn cells must not grow.
3. cam3 0600 — SB u-turns (38 vs Mio 0) must shrink; movement must
   beat the fleet arm's 85.4.
Cell tables + phantom-slack check mandatory on every arm. Coverage
and activation reported per window (cam1-0700 sits at 0.474 vs the
0.45 bar). Named checks: track 17526 must yield NO W crossings and a
single S exit; 16722 must stay OCCUPYING(W) -> EXITED(S).

## Verdict

(to be recorded)
