# THE CORNER RULE FIX (2026-09-08) — G-EX-1 declared

Root cause (measured): GATE_GROUND_ANCHOR's both-bottom-corners rule
cut cam5 witnessed entries 3,129 -> 2,424, dropping coverage
0.56 -> 0.381 under the fixed EVIDENCE_ACTIVATION_COVERAGE = 0.45,
which switched the evidence channel OFF for the whole window and
discarded +932 vehicles (including three operator-ruled perfect
throughs).

Measured entry evidence, cam5 midday, 6,149 tracks:
  by box centre (old)   3,100   coverage 0.504   channel ON
  BOTH corners (now)    2,661   coverage 0.433   channel OFF
  EITHER corner         3,503   coverage 0.570   channel ON
Corner conflicts: ZERO (2,661 both-agree, 2,646 neither, 842
exactly-one-corner, 0 naming different legs).

CHANGE: GATE_EVIDENCE_EITHER_CORNER (default OFF) makes gate
EVIDENCE accept a witness from either bottom corner, refusing only
on conflict. Ground anchoring — the anti-illusion half of the
operator's law — is untouched.

## G-EX-1 (declared before any scoring; two iterations)

Arm 1, cam5 l1_study_1100: coverage must rise over 0.45 and the
channel ACTIVATE; insufficient_data must fall materially from 2,390;
movement pct must beat the current new-basis score; and tracks
113585 / 100086 / 112387 (the operator's filmed throughs) must each
acquire an event.

Arm 2, cam1 study_0700 (THE SHIPPED WINDOW, coverage 0.439 today):
movement pct must not fall below the shipped 75.0, AND the driveway
phantom cells must hold (NB_right 18, WB_right 1) — the load-bearing
test of whether both-corners strictness was doing anti-phantom work.

Full cell tables + phantom-slack check both arms. Approach reported,
never decisive. Ship only on PASS + operator go, via the per-window
promotion flow. cam5 stays on HOLD regardless.

## Verdict

(to be recorded)
