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

## Theft back-projection — NEGATIVE (measured 2026-09-10, scripts/theft_backprojection.py)

On the 17 ruled clips: post-launch heading traced backward from the
launch point, first gate hit vs the machine's origin gate.
  clean rights: 16722 same (W); 17526, 4383, 22270 DIFF (back ray hits
    S — a right turn's post-launch heading already points at its exit,
    so the backward ray does not return to W); 18964 no gate.
  thefts: 14634, 281674 DIFF (N — the thief's gate, as predicted);
    332755 DIFF (W); 154504, 302741 SAME (S); the three cam2 thefts
    carry no machine origin at all (their W entry is refused under
    iteration 3 while the two corner-spawn rights keep theirs).
3 of 4 clean rights read as thefts and 2 of 5 thefts read as clean.
NO SEPARATION. Two path-geometry signals (speed, back-projection)
and one tracker-level veto (G-LT-1, twice) have now missed the theft
class. The box's PATH does not carry the theft; what changes at a
theft is WHAT IS IN THE BOX. The next instrument for this class is
appearance identity across the launch (the ReID cache exists:
scripts/build_reid_cache.py), declared as its own gate, not folded
into the crossing law.

One real observation from the table, for the anti-theft file: under
iteration 3 the three cam2 thefts have NO gate origin (exit_only) —
the waiting box's W entry is refused and the S exit belongs to the
thief — so their N->S booking comes from the posterior. The two
genuine corner-spawn rights keep a gate origin. On these five, "S exit
with no gate origin" separates theft from real; not yet a rule.

## G-SM-2 verdict (recorded 2026-09-10): MISS on the letter, all six

Arm sm4, parallel, 131 s wall. Log _replay_scratch/gsm4.log.

  window       live    sm4    cov -> chan     letter
  cam4 0700    75.4   62.2   0.468 ON        FAIL -13.2
  cam4 1100    73.5   72.3   0.577 ON        FAIL -1.2
  cam4 1600    75.8   72.9   0.424 OFF       FAIL -2.9 (channel still off)
  cam5 0700    66.4   72.9   0.387 OFF       movement +6.5; big cell NB_left 270 -> 424 (Mio 335) FAIL crit. 2
  cam5 1100    71.7   71.4   0.452 ON        FAIL -0.3
  cam5 1600    63.1   68.9   0.480 ON        movement +5.8; NB_left 224 -> 379 (Mio 240), SB_thru 2635 -> 3109 (Mio 2819) FAIL crit. 2

cam4 — THE CHANNEL ACTIVATING HURTS. The born-across clause did what
it did on cam1/cam2: coverage 0.304/0.442 -> 0.468/0.577 and the
evidence channel turned ON for the first time on cam4 morning and
midday. The counts then got worse: NB_thru 2779 -> 3026 against Mio
2713 (morning), 1524 -> 1654 against 1546 (midday), and the
pre-existing SB_right phantom class (prod 89/64/274 vs Mio 22/16/39)
GREW to 115/125/329. cam4's gate evidence, once trusted, assigns
more N origins and more S-right destinations than the road carries.
That is a cam4 geometry / gate problem to look at on film, not a
crossing-law problem; the machine only made the channel's opinion
count. Phantom-slack FAIL on 0700/1100 (EB_right 0 -> 1/2, SB_uturn
0 -> 1).

cam5 — TWO REAL HEADLINE GAINS WITH A CAVEAT. cam5 0700 +6.5 came
with the channel switching OFF (0.509 -> 0.387): the machine's
stricter entry starves the channel and the non-evidence path scores
better on this camera, consistent with cam5 failing the fleet flags
on 09-08. cam5 1600 +5.8 with the channel ON: NB_right 0 -> 36 (Mio
35), WB_right 103 -> 14 (Mio 25), EB_thru 13 -> 28 (Mio 29) are
genuine fixes, but NB_left 224 -> 379 (Mio 240) and SB_thru 2635 ->
3109 (Mio 2819) move a big real cell AWAY by 139 and 290. Both cam5
windows fail criterion 2 as declared. Phantom-slack CLEAN on cam5.

NOTHING SHIPPED. Recommendation: cam4 stays on its basis; cam5's two
gains are the operator's call and want a reel (cam5 1600 NB_left,
the 155 added left turns from N) before any go.
