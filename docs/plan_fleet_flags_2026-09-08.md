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
