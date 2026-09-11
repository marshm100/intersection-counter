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

## THE CHANNEL'S VALUE, WINDOW BY WINDOW (arm choff, 2026-09-10)

The default with EVIDENCE_ACTIVATION_ENABLED=0 (plain legacy replay:
the gate-evidence channel never activates), all 12 windows. "Value" =
default minus channel-off.

  window       default   channel off   value
  cam1 0700     83.8        75.0        +8.8
  cam1 1600     95.1        80.7       +14.4
  cam2 0700     75.2        40.6       +34.6
  cam2 1100     76.7        34.6       +42.1
  cam2 1600     71.3        32.1       +39.2
  cam3 0600     85.7        59.4       +26.3
  cam4 0700     62.2        64.7        -2.5
  cam4 1100     72.3        68.1        +4.2
  cam4 1600     72.9        72.9         0.0   (already off)
  cam5 0700     72.9        72.9         0.0   (already off)
  cam5 1100     71.4        70.8        +0.6
  cam5 1600     68.9        63.1        +5.8

THE CHANNEL IS THE DEFAULT. Without it the fleet is 61.2, not 75.7:
cam2 loses 35-42 points per window and cam3 26. It hurts on exactly
ONE window (cam4 0700, -2.5) and is a wash elsewhere on cam4/cam5.
The ceiling for any "trust the channel or not" rule is +2.5 on one
window — NOT worth building. The trust question is closed; the
question that remains on cam4 is the GATE DRAWING (the W gate lies
along the main road, see the gates review page), which is the
operator's, and on cam5 it is not the channel at all.

What this reframes: the default's weakness on cam4/cam5 is not that
the channel is trusted wrongly; it is that even WITH the channel
those cameras sit at 62-73 for reasons the channel does not reach —
gate placement on cam4, and on cam5 (red on two windows) something
not yet diagnosed on film.

## OPERATOR RULING ON THE GATES (2026-09-10, gates review page)

His words: "yes all the lines are where they are intended to be but
the mouth should be the lines and the exit should be the lines the
blue dots should not exist."

So: every drawn gate is correct as drawn (cam4's driveway gate along
the main road included). THE LINES ARE THE MOUTHS AND THE EXITS. The
per-leg mouth POINT (legs.origin_zone, the cyan dot, set by the May
recalibration script) is not his and should not exist as a concept:
everything the software derives from "the mouth" must derive from the
line. Scope of that change to be measured before it is declared.

## G-DEF-2 (declared 2026-09-10, before any scoring): THE LINES ARE THE MOUTHS

Build: MOUTH_FROM_GATE (default OFF) — backend/services/entry_gates.py
mouth_from_gate(): for every leg with a drawn gate, origin_zone :=
the line's midpoint and reference_heading := the heading of travel
entering over the line (its inward perpendicular, same centroid sign
test as build_gates). Applied at load in leg_geometry_for_camera,
pass2_replay, both processing-router loaders and the merge-rescue
loader. Pure; the DB is untouched; legs without a line keep their
dot. 6 tests; 1206 green.

What it changes, measured on cam4 before scoring: the derived entry
headings differ from the stored ones by 60-80 deg (N 265 -> 188, W
119 -> 177) because cam4's lines run ALONG the road (his ruling: as
intended), so "perpendicular to the line" is not the direction of
travel there. The classifier's net-heading-change and the origin
claim by nearest mouth both move. This is exactly what the fleet must
judge — no window is chosen.

Arm d2 = the default + MOUTH_FROM_GATE, all 12 windows, parallel.
PASS = the G-DEF-1 letter against the default (75.70): fleet mean
rises; no camera falls > 1.0; no window falls > 3.0. Cell tables +
phantom-slack reported. If it passes, MOUTH_FROM_GATE flips ON and
the dot is retired from the editor (stage B). If it fails, the ruling
still stands and the next candidate derives the heading from the
TRACKS crossing the line rather than from its perpendicular.

## G-DEF-2 verdict (recorded 2026-09-10): MISS — and it locates the heading problem

  window       default   d2      delta          biggest cells (Mio | d1 | d2)
  cam1 0700     83.8    65.9   -17.9   NB_right 3|18|122, EB_left 86|96|143, NB_thru 2141|2045|1907
  cam1 1600     95.1    73.0   -22.1   EB_left 105|114|221, EB_right 497|501|415, NB_right 2|17|61
  cam2 0700     75.2    75.0    -0.2
  cam2 1100     76.7    77.9    +1.2
  cam2 1600     71.3    59.1   -12.2   NB_thru 1726|1731|1678
  cam3 0600     85.7    85.5    -0.2
  cam4 0700     62.2    64.4    +2.2
  cam4 1100     72.3    72.3     0.0
  cam4 1600     72.9    72.1    -0.8
  cam5 0700     72.9    76.9    +4.0   EB_right 188|122|210, SB_thru 1868|1744|1803
  cam5 1100     71.4    76.0    +4.6   EB_right 162|92|187
  cam5 1600     68.9    74.5    +5.6   EB_right 244|102|251
  FLEET        75.70   72.72   -2.98   cam1 -20.0 | cam2 -3.7 | cam3 -0.2 | cam4 +0.5 | cam5 +4.7

TWO CHANGES WERE BUNDLED and they pull opposite ways:
  the mouth POINT from the line (his ruling) — not separable here;
  the entry HEADING from the line's perpendicular (agent assumption).
On cam1 the perpendicular heading is WRONG: throughs are reclassified
as rights and lefts (NB_right 18 -> 122 against Mio 3; EB_left 96 ->
143 against 86) — the classifier's net-heading-change is measured
from an entry direction that is not the direction of travel where a
line is drawn at an angle to the lane. On cam5 the perpendicular
heading is RIGHT and the STORED one was wrong: EB_right recovers to
210/187/251 against Mio 188/162/244 (the default had 122/92/102) —
a big real cell that the May recalibration's heading had been
starving on every cam5 window. Neither source is right everywhere.

His ruling stands (the lines are the mouths; the dots should not
exist). What the arm rejects is my choice of the perpendicular as the
entry direction. Next, in order:
  d3  the mouth POINT from the line, heading as stored — isolates his
      ruling's own effect (MOUTH_FROM_GATE_HEADING=0).
  d4  the heading from the TRACKS that cross each line inward (the
      circular mean of their direction at the crossing, from the
      window's own dump) — a heading that is true by construction on
      every camera, derived from raw video + the operator's lines
      alone, which is the prime directive's allowed basis.

## d3 verdict (2026-09-10): the mouth POINT from the line, heading kept — near-neutral, MISS on the letter

  cam1 83.5 / 95.1 | cam2 76.6 / 74.8 / 66.7 | cam3 85.6 | cam4 64.4 / 72.3 / 73.3 | cam5 72.6 / 71.4 / 68.9
  FLEET 75.70 -> 75.43 (-0.27); cam4 +0.9, cam2 -1.7 (evening -4.6:
  NB_left 404 -> 388 against Mio 420, the waiting-vehicle origins move),
  everything else within 0.3.

His ruling's own effect on the counts is small either way: the point
is used for the origin claim by proximity and the box centroid, and
the line's midpoint sits close to the May dot on most legs. cam2
evening is the one window where it costs. Not a default on its own;
it rides with d4.

## d4 verdict (2026-09-10): heading measured AT the line — MISS

  cam1 74.7 / 84.1 | cam2 71.0 / 73.8 / 65.4 | cam3 87.9 | cam4 64.4 / 72.3 / 70.0 | cam5 71.6 / 69.2 / 68.9
  FLEET 72.77 (-2.93). cam1 -10.0, cam2 -4.3, cam5 -1.2, cam4 -0.2;
  cam3 +2.2 (87.9, its best ever). cam1 coverage 0.569 -> 0.528 on
  the evening window: the heading feeds the origin claim, not only
  the classifier.

Why: the direction was taken over +-0.5 s AROUND the crossing, and a
turning vehicle is already turning at the line (cam1's W leg read 34
deg off its stored value on 247 crossings). The stored headings came
from through-traffic tails UPSTREAM of the mouth, which is the
approach direction the classifier's net-heading-change needs.
d5: the direction over the 1.5 s of approach ENDING at the line
(HEADING_APPROACH_S), upstream of any turn.

## d5 verdict (2026-09-10): heading on the APPROACH — MISS. The heading ladder closes.

  cam1 75.9 / 86.6 | cam2 68.6 / 73.8 / 65.4 | cam3 (see log) | cam4 64.4 / 72.3 / 71.7 | cam5 71.6 / 69.2 / 68.9
  FLEET mean over 12 windows: live 75.70 -> arm 73.02 (-2.68)

THE CAUSE, SPECIFIC: on cam1 the W approach is almost all right-
turners (EB_right 497 vs EB_thru 1). Vehicles are already steering
toward S in the 1.5 s before the line, so a heading measured from
them reads 37 deg off the road axis (313 -> 276); the classifier then
stops calling W -> S a right and EB_right collapses 501 -> 146
against Mio 497. A heading derived from the tracks near the line is
biased by the leg's TURNING MIX — and a blank site's driveways and
T-legs are exactly such legs. The stored headings come from the May
recalibration's road-axis method (two opposite dominant tail modes
define the axis), which does not carry that bias.

CONCLUSION FOR HIS RULING ("the lines are the mouths; the dots
should not exist"):
  - the mouth POINT from the line is implemented (MOUTH_FROM_GATE,
    heading kept = d3) and costs 0.27 fleet points, cam2 evening -4.6,
    cam4 +0.9. Whether that price is worth removing the dot as a
    concept is his call — it is a product simplification, not an
    accuracy gain.
  - the entry HEADING is NOT derivable from the line (perpendicular:
    -3.0 fleet, cam1 -20) nor from the tracks at or before the line
    (-2.9 both ways, cam1 -8 to -10). It stays what the calibration's
    road-axis method produces. If the dot goes, the heading must be
    stored on the leg in its own right.
  - one real lead surfaced and is NOT lost: cam5's EB_right is starved
    by its stored E heading (122/92/102 vs Mio 188/162/244) and the
    perpendicular fixed it (210/187/251). cam5's E leg heading is
    wrong in the calibration and should be re-derived by the road-
    axis method on the current dump — a calibration fix, not a rule.

Flags left as built, all default OFF: MOUTH_FROM_GATE,
MOUTH_FROM_GATE_HEADING, HEADING_FROM_CROSSINGS. The default stands
at 75.70.

## G-DEF-3 (declared 2026-09-11, before any scoring): THE HEADING REVIEW

Two facts fix the method:
  1. scripts/recalibrate_camera.py (the May "road-axis" headings)
     count-matches approaches against the MANUAL study — reference
     data a blank site never has. Not a product path; not a refresh
     method.
  2. The product's heading IS the operator's: in the calibration
     editor each leg carries an arrow, seeded from the node's position
     and dragged to aim it (frontend/js/calibration.js). The stored
     headings are his calibration.

So the refresh is a CALIBRATION REVIEW. scripts/viz_heading_review.py
draws, per leg on each camera's frame: the STORED arrow, the line's
PERPENDICULAR, and the THROUGH-TRAFFIC direction measured without
reference data (tracks whose gate journey enters over the leg and
exits over the leg opposite, direction on the approach). The operator
rules per leg where they disagree (cam5 E, cam1 W, cam3 are the
known disagreements). His ruled headings are written to legs.
reference_heading with a pre-write backup — a calibration edit, the
same as dragging the arrow.

PASS = one fleet arm on the ruled calibration against 75.70, the
G-DEF-1 letter (fleet rises; no camera -1.0; no window -3.0). Ship =
the calibration stays (already written) and the fleet is reprocessed;
MISS = restore the backup.

For a blank site this is the operating rule that comes out of it:
draw the line, then aim the arrow along the lane's direction of
travel; the software seeds the arrow with the line's perpendicular.

## G-DEF-3 verdict

(to be recorded)
