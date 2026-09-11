# THE DETECTION BASIS AS A DEFAULT (2026-09-11) — G-DEF-5 declared

Operator, 2026-09-11: overnight processing per camera-day is
acceptable; the basis is to be declared as the next default candidate.

## What each window runs today (parquet meta)

  cam1 0700 / 1600     yolo26l @ 1280   (l1 basis, promoted 09-07 / 08)
  cam2 0700/1100/1600  yolo26l @ 1280
  cam3 0600 (14 h)     yolo26s_ft2 @ 640  (the July fine-tune rebaseline)
  cam4 0700/1100/1600  yolo26s @ 960     — l1 dumps (yolo26l@1280, own
                                            bytetrack recipe) built 09-07,
                                            ON DISK, never scored under
                                            the default
  cam5 0700/1100/1600  yolo26s @ 960     — same, l1 dumps on disk
The corridor's best camera (cam1, 84/95) is on the large basis; the
two floors found today (thefts, 13-20 px far-field boxes) are pixel
floors. A blank site gets calib_pass1_backend's choice.

## G-DEF-5 (declared before any scoring; one iteration)

Candidate default: yolo26l @ 1280 on every window (each camera keeps
its own tracker recipe), the counting default (five rules + ruled
headings) unchanged.
Arms, both pass-2 under the default over the l1 dumps:
  d8   cam4 + cam5, six windows, existing l1_study_* dumps (no GPU).
  d9   cam3 study_0600 re-detected at yolo26l@1280 (scripts/
       c3_redetect.py, ~6 h GPU), then pass-2.
cam1 and cam2 are already on the basis: their d7 scores stand.
PASS = the G-DEF-1 letter against 77.08 over all 12: fleet rises; no
camera falls > 1.0; no window falls > 3.0; cell tables + phantom-
slack. Ship = promote the l1 dumps to study_* (the cam1 flow:
pre_l1_* rename-aside, backups), reprocess, and make yolo26l@1280 the
detection default for a blank site (config / calibration default).
Cost recorded for the operator: ~50 min GPU per 2-hour window at
1280 on this machine (c45_redetect.log), i.e. a camera-day ~10 h —
inside "overnight".

## d8 (cam4 + cam5 on the l1 dumps, 2026-09-11): MISS on the letter before cam3

  window       current   l1     delta   cells (Mio | current | l1)
  cam4 0700     71.1    75.0   +3.9    NB_thru 2713|3026|2887 (toward), SB_thru 1957|2051|2108 (away)
  cam4 1100     74.5    82.0   +7.5    NB_thru 1546|1654|1544 (to Mio)
  cam4 1600     78.0    70.7   -7.3    SB_thru 2981|3120|3235, NB_thru 2439|2391|2280, EB_left 29|38|69
  cam5 0700     72.0    67.0   -5.0    NB_left 335|417|521, SB_thru 1868|1746|1694
  cam5 1100     71.4    73.1   +1.7    EB_right 162|89|112 (toward), SB_thru 1496|1708|1651
  cam5 1600     68.9    69.2   +0.3    NB_left 240|378|480
  cam4+cam5 mean 72.65 -> 72.83 (+0.18); cam4 +1.4, cam5 -1.0;
  two windows fall > 3.0 (cam4 1600 -7.3, cam5 0700 -5.0) -> the
  letter fails regardless of cam3.

Reading: more pixels find more far-field vehicles, and the counting
default then completes them the same way it completes the small
basis's fragments — cam5's NB_left phantom class GROWS (417 -> 521,
378 -> 480) as the detector reaches further into the S mouth. Where
the extra detections are real throughs (cam4 1100 NB_thru 1654 ->
1544 = Mio 1546) the basis is a clean win. The basis and the
counting rules are not independent; the rules were tuned on the
small basis for cam4/cam5. cam3 (d9) is still worth its answer: a
fine-tuned small model at 640 on the corridor's second-best window.

## G-DEF-5 verdict (recorded 2026-09-11): MISS — the large basis is not a fleet default

d9, cam3 study_0600 at yolo26l@1280 (430 min GPU, 1.63 M rows):
  87.6 -> 82.4 (-5.2); approach 73.2 -> 63.5; coverage 0.547 -> 0.674
  SB_thru 14651 -> 15418 (Mio 14385: further over), NB_thru 13980 ->
  13492 (Mio 13756: now under), EB_left 242 -> 221 (toward 196),
  SB_uturn 25 -> 2 (Mio 0: the phantom class gone).

All 12 on the large basis: FLEET 77.08 -> 76.74 (-0.34); cam3 -5.2,
cam4 +1.4, cam5 -1.0; three windows fall > 3.0. MISS on every clause.

What it says: the detector is not separable from the counting rules.
The corridor's counting default was tuned window by window on each
camera's basis (cam3 on its July fine-tune at 640, cam4/cam5 on the
small model at 960), and the large detector's extra far-field boxes
feed the same completion path that already over-counts (cam5 NB_left
417 -> 521, cam3 SB_thru +767). Where the extra boxes are real
throughs it wins outright (cam4 1100 +7.5, NB_thru to Miovision's
number exactly). A basis default for a blank site has to be chosen
TOGETHER with the counting default, on a fleet arm of both — and the
fine-tuned small model cam3 runs (yolo26s_ft2@640) is itself a
candidate the other cameras have never had under the default. That
is a day of GPU per candidate and is the next basis question, not
taken today. The l1 dumps stay on disk (cam3 l1_study_0600 included)
as scratch for it.

Nothing shipped. The default stands at 77.08.

## G-DEF-6 (declared 2026-09-11, before any scoring): THE FINE-TUNED SMALL MODEL AS THE BASIS

Operator: "sure plan it out". The mirror of G-DEF-5: cam3 runs
yolo26s_ft2 @ 640 (the July corridor fine-tune) and is the second-
best window; the same fine-tune's dumps (OpenVINO ft2 @640, each
camera's own tracker) exist on disk from 2026-07-24 for cam1 0700,
cam2 x3, cam4 x3, cam5 x3 — never scored under the default. cam1 1600
has no ft2 dump and cam3 already is ft2: both keep their current
scores.

Arm d10: pass-2 under the default over ft2_study_* for those ten
windows, no GPU. PASS = the G-DEF-1 letter against 77.08 over all 12:
fleet rises; no camera falls > 1.0; no window falls > 3.0; cells +
phantom-slack. Caveat stated up front: the fine-tune was trained on
corridor footage, so a win says less about a blank site than the
counting defaults did; it would still be the software's unaided
behaviour. Ship = promote ft2 dumps to study_* and make the fine-tune
the detection default.

## G-DEF-6 verdict

(to be recorded)
