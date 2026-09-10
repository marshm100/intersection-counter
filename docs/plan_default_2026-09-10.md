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

## Verdict

(to be recorded)
