# THE DEFAULT (2026-09-10) — G-DEF-1 declared

Operator, 2026-09-10: "cams 1-5 are our test footage, we need to make
the software robust so that when we run it on a blank untested
intersection we still get miovision results." And: "I thought we had
a default ... we need to work on improving the accuracy of the
default."

## What a blank site runs today (measured 2026-09-10)

Every accuracy flag is default OFF and applied per window by hand:
  GATE_GROUND_ANCHOR            off   (shipped by hand to 5 windows)
  STRAIGHT_FRAGMENT_RULE        off   (same 5)
  GATE_EVIDENCE_EITHER_CORNER   off   (same 5)
  JOURNEY_STATE_MACHINE         off   (shipped by hand to 4 windows)
  JOURNEY_FIRST_EXIT            off   (never shipped)
  EMERGENCE_GUARD / CONCEALER   off   (missed twice)
  MOTION_QUALIFIED_EVIDENCE     ON    (the one default-on switch)
A new intersection gets the 2026-08 baseline. The corridor's 12
production windows are a PATCHWORK: cam1 1600 on three flags, cam1
0700 / cam2 0700 / cam2 1100 / cam3 on four, cam2 1600 / cam4 / cam5
on none. No number in the standings describes the software's own
behaviour.

RULING (his, restated): per-window flag ships are not the product.
The unit of shipping is a DEFAULT — one configuration, held constant
across all 12 windows, scored as a fleet. Nobody picks windows.

## G-DEF-1 (declared before any scoring; two iterations)

ARMS, both over the existing production dumps (pass-2 flags only; the
pass-1 detector/tracker basis is a separate default question, noted
below), all 12 windows, apply=False, parallel:
  base  every flag at its shipped default (all OFF) — the blank site.
  d1    GATE_GROUND_ANCHOR + STRAIGHT_FRAGMENT_RULE +
        GATE_EVIDENCE_EITHER_CORNER + JOURNEY_STATE_MACHINE — the set
        shipped by hand this week, offered as ONE default.

SCORE: per window, v2_score_dev movement pct (approach reported,
never decisive). FLEET = the unweighted mean over the 12 windows, and
per-camera means. Cell tables + phantom-slack on every window,
reported, never used to choose windows.

PASS: fleet mean RISES over base; no camera's mean falls more than
1.0; no window falls more than 3.0 (a default that ruins one window
is not robust). The per-window table is published whole.

Known before running (from the sm3/sm4 arms vs live standings):
cam4 0700 will fall ~13 under d1 and cam5 0700 will rise ~6.5 with
its channel off; cam2 1600 rises ~1. The fleet mean is expected UP;
the cam4 floor is the risk. If d1 fails on cam4, iteration 2 is d1
with the evidence channel gated by a REFERENCE-FREE trust test
(study_health signals; cam4 and cam5-0700 are the labelled cases
where trusting the channel hurts) — its own declaration, G-TRUST-1.

SHIP = flip the defaults in backend/config.py so the software does
this unaided, then reprocess all 12 windows under the default and
let the standings be whatever the default scores (cam1 1600 will read
95.1, not 95.3; cam4 may fall). That price is the operator's call and
is the honest number for a blank site.

NOT IN THIS GATE (recorded so it is not forgotten): the pass-1 basis.
cam1 runs on a promoted yolo26l@1280 basis; other cameras on their
own; a blank site gets calib_pass1_backend as auto-calibrated. The
default's detector/tracker choice needs the same treatment after the
pass-2 default exists.

## THE BLANK SITE, MEASURED (base arm, 2026-09-10, _replay_scratch/gdef_base.log)

Every accuracy flag off, all 12 windows, existing dumps, 6 parallel:

  window       live    base   cov    chan
  cam1 0700    83.8    61.0   0.469  ON
  cam1 1600    95.3    86.2   0.588  ON
  cam2 0700    75.2    71.3   0.569  ON
  cam2 1100    76.7    70.4   0.485  ON
  cam2 1600    70.3    69.4   0.489  ON
  cam3 0600    85.7    83.7   0.547  ON
  cam4 0700    75.4    53.8   0.458  ON
  cam4 1100    73.5    57.7   0.540  ON
  cam4 1600    75.8    72.9   0.429  OFF
  cam5 0700    66.4    72.9   0.340  OFF
  cam5 1100    71.7    70.8   0.415  OFF
  cam5 1600    63.1    63.1   0.412  OFF
  FLEET mean   76.08   69.43  (-6.64)
  per camera   cam1 89.6 -> 73.6 | cam2 74.1 -> 70.4 | cam3 85.7 -> 83.7
               cam4 74.9 -> 61.5 | cam5 67.1 -> 68.9

A BLANK SITE SCORES 69.4. The 6.6-point gap to the patchwork is the
size of what is not yet default. cam1, cam2 and cam3 reproduce their
pre-flag standings to within a point (cam1 1600 86.2 exactly, cam3
83.7 exactly) — the environment has not drifted.

cam4 AND cam5 DO NOT REPRODUCE THEIR LIVE NUMBERS: cam4 0700/1100
base at 53.8/57.7 against live 75.4/73.5, with the evidence channel
ON (0.458/0.540) where production recorded it OFF (0.304/0.442);
cam5 0700 base 72.9 against live 66.4.

CAUSE, MEASURED (production pass-2 sidecars vs the present):
  cam4  sidecars dated 07-31; dump_meta IDENTICAL to the dump on disk
        (so NOT a re-detect — an earlier inference here was wrong);
        calib_fingerprint DIFFERENT. cam4's gates/legs/mouths were
        redrawn after 07-31 and production was never re-applied. The
        live 75.4/73.5/75.8 describe the OLD calibration with the
        channel off; under the CURRENT calibration the channel
        activates and the counts fall to 53.8/57.7 (72.9 with it
        still off on 1600).
  cam5  sidecars dated 08-28; dump_meta DIFFERENT (the 09-07 re-detect
        is on disk, production is not) AND calib different. cam5
        morning at 72.9 with the channel off is the new dump's own
        number; yesterday's "+6.5" was the dump, not the machine.
  cam2 1600  sidecar 08-27, calib different too (base 69.4 vs live
        70.3 — within a point, so the redraw there was small).
So every arm since the redraws (fleet, sm4, base) has been scored on
the current calibration against live numbers from an older one. The
honest cam4/cam5 basis is the base arm. A question for the operator,
recorded and not answered here: cam4's current gates make its gate
evidence HARMFUL when trusted (channel on: -20); was the redraw meant
to be applied, and are those gates right?

Consequence for the gate: d1 is judged against BASE (the blank site),
never against live. cam4's pass-1 basis question (the re-detect that
was never promoted) is real and separate.

## SHIPPED — THE DEFAULT (operator go 2026-09-10: "ok yes flip them and reprocess")

backend/config.py: the four rules default ON (commit cc05e86); env vars
are overrides. Three test suites that assumed the old defaults pin
them explicitly; 1200 green. CLAUDE.md carries the default section.

scripts/reprocess_default.py, no env flags set: pre-reprocess backup
backups/project_20260910T115152_pre_default_reprocess.db (461 MB);
force_once per window; all 12 applied through the apply gate. Every
window's event count equals the d1 arm's; re-score: PRODUCTION ==
DEFAULT on 12 of 12 windows, fleet mean 75.70.

  window       was     now    health
  cam1 0700    83.8    83.8   amber
  cam1 1600    95.3    95.1   green
  cam2 0700    75.2    75.2   green
  cam2 1100    76.7    76.7   green
  cam2 1600    70.3    71.3   amber
  cam3 0600    85.7    85.7   amber
  cam4 0700    75.4*   62.2   amber      * old gates, July apply
  cam4 1100    73.5*   72.3   amber
  cam4 1600    75.8*   72.9   red
  cam5 0700    66.4*   72.9   red        * replaced dump
  cam5 1100    71.7*   71.4   amber
  cam5 1600    63.1*   68.9   red
  FLEET        76.08   75.70  (the patchwork -> the default)

For the first time every live number is what the software produces
unaided on its own dumps and current calibration. The corridor
standings are now the default's: cam1 83.8 / 95.1 | cam2 75.2 / 76.7
/ 71.3 | cam3 85.7 | cam4 62.2 / 72.3 / 72.9 | cam5 72.9 / 71.4 / 68.9.

WHERE THE DEFAULT IS WEAKEST (the standing work): cam4 (62-73; its
gate evidence is harmful when trusted and the redraw question is
open), cam5 (69-73; red on two windows), the theft class everywhere
(no path signal separates it; appearance identity is the next
instrument). Every improvement from here: change the default, 12
windows, compare to 75.70, ship on fleet PASS.
