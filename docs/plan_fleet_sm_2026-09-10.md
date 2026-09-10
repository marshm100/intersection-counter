# FLEET OFFER OF THE JOURNEY STATE MACHINE (2026-09-10) — G-SM-2 declared

Operator, 2026-09-10, on "how do we improve": "yes plan it out".

## Context

G-SM-1 iteration 3 shipped yesterday to cam1 0700, cam2 0700, cam2
1100 and cam3 0600 (docs/plan_state_machine_2026-09-09.md). The
remaining production windows never saw the flag:
  cam4 0700 / 1100 / 1600   live 75.4 / 73.5 / 75.8
  cam5 0700 / 1100 / 1600   live 66.4 / 71.7 / 63.1
  cam2 1600                 live 70.3 (SM iter 3 scored 71.3; theft-dominated)
  cam1 1600                 live 95.3 (SM iter 3 scored 95.1; not offered)

Why cam4 is the prize: on the G-FLEET-1 run its evidence channel
stayed OFF on all three windows (coverage 0.304 / 0.442 / 0.318
against the 0.45 activation bar, 6,636 vehicles dropped), so the
shipped flag set never reached its counts. The born-across clause is
what carried cam1 0700 (0.391 -> 0.464) and cam2 1100 (0.440 ->
0.495) back over that bar yesterday. If it does the same on cam4 the
channel activates for the first time on that camera.

Why cam5 is not: its channel was ON (0.509 / 0.560 / 0.578) and the
fleet flags still LOST on two windows (cam5 1100 -0.3, cam5 windows
FAIL in the fleet doc). The machine changes the crossing law, not
the reasons cam5 lost; it is offered so the fleet has one basis, with
no expectation.

## Arms

scripts/fleet_flags.py, FLEET_STEM=sm4, FLEET_WORKERS=6, windows
4:study_0700,4:study_1100,4:study_1600,5:study_0700,5:study_1100,
5:study_1600, under the shipped set + JOURNEY_STATE_MACHINE, pass-2
over the existing production dumps, apply=False, scored by
v2_score_dev. cam2 1600 is NOT re-run (its sm3 arm stands).

## G-SM-2 (declared before any scoring; one iteration — the rule is
## already shipped; this is an offer, not a build)

PASS IS PER WINDOW, the G-FLEET-1 letter:
  1. movement pct beats the live standing (cam4 75.4 / 73.5 / 75.8;
     cam5 66.4 / 71.7 / 63.1);
  2. big real cells shrink or hold; no phantom-slack minting
     (sub-10-Mio cells growing on the +-5 slack fail the window);
  3. approach reported, never decisive.
Reported per window: coverage and activation (cam4's ON/OFF is the
headline), cell tables against production (scripts/arm_compare.py
with the production column, since no prior arm on these windows was
kept on disk — the score_ff_* files were overwritten on 09-08).

Ship only the windows that pass, on operator go, via
scripts/ship_gsm1.py's flow (named backup, force_once, isolation
hash, health). Missing windows keep their basis, no penalty.

## What comes after (not this gate)

The theft class. Measure, on the 17 ruled clips, the back-projection
signal: the post-launch path traced backward crosses the THIEF's
gate (N) while the box's origin was W; a genuine right from W traces
back to W. Build nothing until that separates on the ruled clips —
the speed signal did not, and the tracker-level veto missed twice.

## Verdict

(to be recorded)
