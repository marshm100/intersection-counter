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

## G-EX-1 verdict (recorded 2026-09-08): SPLIT

ARM 2 — cam1 study_0700, THE SHIPPED WINDOW: PASS, decisively.
  coverage 0.439 -> 0.474, channel ACTIVATED
  movement  75.0 -> 83.5  (+8.5)
  approach  64.5 -> 90.3  (+25.8)
  SB_thru   1552 -> 1750  vs Mio 1756 (was 204 short; now 6) — the
            activation knife-edge is cured, and this large real cell
            is the whole source of the gain (not slack).
  NB_thru   2013 -> 2046  vs Mio 2141
  DRIVEWAY PHANTOM CHECK HELD EXACTLY: NB_right 18 (unchanged),
  WB_right 1 (unchanged). Relaxing both-corners did NOT resurrect the
  phantom class — ground anchoring alone does that work, as designed.
  Minor: NB_uturn 6 vs Mio 2, SB_uturn 2 vs Mio 0 (tiny cells).

ARM 1 — cam5 l1_study_1100: mechanism goals MET, score criterion
MISSED.
  coverage 0.381 -> 0.493, channel ACTIVATED
  origin_evidenced 2,424 -> 3,137; insufficient_data 2,390 -> 2,027
  the operator's three filmed throughs (113585 / 100086 / 112387) are
  now COUNTED, each as W->E 'through' — exactly his ruling
  movement 73.1 vs production 71.7, but BELOW the best cam5 config
  (76.4), so the declared "must beat the current new-basis score"
  fails. Throughs now overshoot (SB_thru 1654 vs Mio 1496).

READ: the fix does exactly what it was built to do (restore the
witnessed evidence and stop discarding real vehicles) and pays
handsomely where the basis is sound (cam1). cam5's remaining error is
not the corner rule; cam5 stays on HOLD regardless, per the plan.

RECOMMENDATION: ship the cam1-0700 re-run (75.0 -> 83.5) on operator
go; leave the flag default OFF until the fleet question is settled.
