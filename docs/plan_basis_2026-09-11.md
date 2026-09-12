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

## G-DEF-6 verdict (recorded 2026-09-11): MISS, decisively

  window       current   ft2     delta   coverage / dropped
  cam1 0700     84.0    48.6   -35.4   0.244 OFF, 6956 of 12882 dropped
  cam2 0700     75.2    39.3   -35.9   0.377 OFF
  cam2 1100     75.7    34.5   -41.2   0.321 OFF
  cam2 1600     71.3    29.7   -41.6   0.328 OFF
  cam4 0700     71.1    54.0   -17.1   0.370 OFF
  cam4 1100     74.5    48.9   -25.6   0.413 OFF, approach 0.0
  cam4 1600     78.0    60.7   -17.3   0.363 OFF
  cam5 0700     72.0    57.8   -14.2   0.323 OFF
  cam5 1100     71.4    72.9    +1.5   0.360 OFF, approach 34.4 -> 15.6
  cam5 1600     68.9    63.0    -5.9   0.378 OFF
  FLEET current 77.08 -> fine-tune everywhere 57.69

The dump format is identical (format 2, same columns, same tracker
recipe). The fine-tune finds FAR MORE and SMALLER vehicles (cam4 1100:
6,809 tracks vs 4,970, median box 16 px vs 20), the evidence channel
falls under the activation bar on every window, and the counting
default drops more tracks than it keeps. cam3 is the exception that
proves it: its ft2 basis is the one the counting rules were shaped on
(the 14-hour window carried every cam3 gate this summer).

CLOSING THE BASIS QUESTION FOR NOW: two bases tried, both miss for the
same reason from opposite sides — the counting default is coupled to
the detection population it was tuned on. A basis change for a blank
site is a joint change (detector + rules re-derived on that detector),
a day of GPU per candidate plus the rules loop; not a single arm. The
corridor's mixed bases stay. Nothing shipped; the default stands at
77.08.

## G-DEF-8 (declared 2026-09-11, before any scoring): THE BASIS UNDER TODAY'S DEFAULT

Operator: item 1 — the detection basis chosen together with the rules.
G-DEF-5 (large everywhere, 76.74) and G-DEF-6 (fine-tune everywhere,
57.7) were scored under the old activation bar (0.45). The bar is now
0.20 (G-BAR-1), and it was the corridor constant most tied to the
detection population: on the large basis cam4 1600 (0.43) and cam5
0700 (0.42) sat under 0.45 and now activate. Step 1 of the joint
question is therefore free: re-score the large basis on all 12
windows under today's default (five rules, ruled headings, bar 0.20)
against the current fleet 76.97. FM51's large-basis numbers under the
same bar exist already (b6: 79.6 / 80.0).

Arm d14: cam3 l1_study_0600, cam4 l1_x3, cam5 l1_x3 (cam1 and cam2
are already on the large basis; their d7 scores stand). PASS = the
G-DEF-1 letter against 76.97 over all 12; FM51 reported alongside.
Ship = the corridor project's processing mode becomes "accurate" (the
new-project default) and the l1 dumps are promoted; the counting
default is unchanged.
If it misses, step 2 is a per-constant sweep on the large basis of
the few population-sensitive constants (activation bar, straight-
fragment bounds, corner pair / truncation windows), each a fleet arm,
declared one at a time.

## G-DEF-8 verdict (recorded 2026-09-11): MISS on the letter, and the picture is now sharp

  window       current   large   delta
  cam3 0600     87.6     82.4    -5.2   (its fine-tune beats the large model; unchanged from G-DEF-5)
  cam4 0700     71.1     75.0    +3.9
  cam4 1100     74.5     82.0    +7.5
  cam4 1600     75.4     78.6    +3.2   (was -7.3 under the old bar: the channel now on)
  cam5 0700     73.3     69.2    -4.1   (channel newly on with the large basis)
  cam5 1100     71.4     73.1    +1.7
  cam5 1600     68.9     69.2    +0.3
  cam1 / cam2   unchanged (already the large basis)
  FLEET 76.97 -> 77.58 (+0.61); cam4 +4.9, cam5 -1.0, cam3 -5.2.
  Two windows fall > 3.0 (cam3, cam5 0700). MISS on the letter; PASS
  on the fleet mean for the first time.

What the joint view shows: the bar was indeed the coupling — cam4
1600 swings from -7.3 to +3.2 once its channel activates — and with
it the large basis is now a fleet-positive default that loses on
exactly two windows: cam3, whose corridor fine-tune is a better
detector for cam3 (a per-camera fact, not a rule), and cam5 0700,
where the newly-on channel hurts (+4.1 loss; the same window lost 5
under the fine-tune too). cam4 gains 4.9 — the camera the pixel floor
hurt most.

Step 2 (the sweep) is now a narrow question, not a day per candidate:
on the large basis, which of the population-sensitive constants moves
cam5 0700 and cam3 without moving cam4 back? Candidates, one fleet
arm each on the existing l1 dumps: STRAIGHT_FRAGMENT bounds (cam5's
far-field fragments), the u-turn admission constants (cam3 SB_thru
+767 came with SB_uturn 25 -> 2), the corner-pair window. Declared
one at a time; the dumps are on disk; ~20 min per arm.

## G-DEF-8 step 2, arm d15 (declared before scoring): the distance floor on the large basis

The constants that decide whether a short track is counted at all:
TRAJECTORY_MIN_POINTS = 5 and TRAJECTORY_MIN_DISTANCE_PX = 50 (a track
below either is dropped as insufficient_data). The large detector
hands the counter more far-field fragments near those floors, and
the two losing windows (cam3 SB_thru +767, cam5 0700 NB_left 417 ->
521) are posterior completions of such fragments. d15 = the large
basis everywhere (cam1/cam2 study_*, cam3/4/5 l1_*) with
TRAJECTORY_MIN_DISTANCE_PX 50 -> 100, all other defaults as shipped.
PASS = the G-DEF-1 letter against 76.97 over 12 windows. If cam4's
gain survives and cam3/cam5 recover, the joint default is
(large basis, floor 100); if cam4 gives its gain back, the floor is
not the coupling and the next constant is the straight-fragment
bounds.

## d15 verdict (recorded 2026-09-11): MISS, and the floor is camera-dependent

  window       current   d15     delta
  cam1 0700     84.0     75.7    -8.3
  cam1 1600     95.3     86.9    -8.4   (NB_thru 2119 -> 2036, SB_thru 2547 -> 2480, EB_right 497 -> 448: real short tracks removed)
  cam2 0700     75.2     67.6    -7.6
  cam2 1100     75.7     74.5    -1.2
  cam2 1600     71.3     59.8   -11.5
  cam3 0600     87.6     88.7    +1.1   (recovers its G-DEF-8 loss of 5.2 and passes the current default)
  cam4 0700     71.1     71.1    +0.0
  cam4 1100     74.5     74.5    +0.0   (cam4's G-DEF-8 gain of +4.9 is gone: the floor removes what the large basis added)
  cam4 1600     75.4     75.9    +0.5
  cam5 0700     73.3     81.2    +7.9
  cam5 1100     71.4     82.7   +11.3
  cam5 1600     68.9     81.4   +12.5   (SB_thru 3110 -> 2862, NB_thru 2372 -> 2203: far-field phantom fragments removed)
  FLEET 76.97 -> 76.67 (-0.30). MISS: two cameras fall past -1.0 and
  four windows past -3.0.

Reading: a pixel floor is not one rule, it is five. On cam5 (high,
far camera) a 100 px floor cuts only the far-field fragments that the
large detector phantoms into NB/SB throughs, and the camera gains
8-12 per window; on cam1 and cam2 (low, near cameras) the same 100 px
is a real vehicle's short but complete journey, and the cameras lose
8-12. cam4 gives back its whole G-DEF-8 gain, so per the declared
text the floor is NOT the coupling. The distance floor stays at 50.

What d15 does establish for item 1: the two losing windows of G-DEF-8
were both fragment populations (cam3 recovers +6.3 against the large
basis, cam5 0700 +12.0), so the large basis plus a fragment rule that
does not use pixels is still the live candidate. Next constant,
declared when armed: the straight-fragment bounds, or a floor in a
camera-invariant unit (gate widths, or seconds of travel), one arm.

## After d15: the time floor is dead before arming; the removed population, measured (2026-09-11)

Census (scripts/census_short_tracks.py): the 50-100 px tracks live the
same length on every camera (median 3.3 s on cam1 and cam5; 24% under
2 s on both). A floor in seconds separates nothing. Not armed.

What the 100 px floor removed (scripts/census_d15_removed.py,
census_twin_stats.py, census_sequential_partner.py), cam1 1600 vs cam5
1600 large basis:
  - cam1: 207 events (144 through, 57 right); cam5: 520 (329 through,
    149 left). Same physical population on both: 75 px of path, mid-
    frame queue positions, far-field boxes (cam5 11-21 px).
  - NOT coexisting twins: median IoU with any overlapping survivor is
    0.00 on both cameras; the twin dedup was right to leave them.
  - Every one has a SEQUENTIAL survivor born or dying at the same spot
    within 50 s (median 8-10 px, 0.25 box lengths) - a queue position.
    In box units the closest cam5 through pairs sit at gap < 1 s and
    dist/box < 1 (a track break and re-birth); the cam1 right pairs
    sit at dist/box 1.5-2.4 (a queue neighbour). That is the only
    measurable difference found, and it needs eyes before it is a rule.
  - cam1's loss under the floor was EB_right 497 -> 448 (Mio 497) and
    NB_left 230 -> 206 (Mio 229): real turns whose only record was a
    short track; plus WB_thru 9 -> 36 (Mio 3), a reclassification not
    yet explained.

Reels for the operator's ruling (scripts/viz_fragment_pair_reel.py,
full frame): cam5 five removed throughs each with its sequential
counted partner (frag5_a/b); cam1 five removed rights the same way
(frag1_a/b/c). Question per clip: one vehicle fractured, or two
vehicles. The next constant is declared after the ruling.

### cam5 fragment-pair reel, operator rulings (2026-09-11)

  clip 1 (orange 139644 removed / cyan 139655 counted, both booked
  S->N through): "clip 1 is a clean right turn C and exited through
  vehicle traffic O." TWO vehicles. The counted cyan track is a RIGHT
  turn booked as a through; the removed orange track is a real
  through that exited. The floor removed a real vehicle here.
  clip 2 (orange 137465 removed / cyan 137490 counted, both booked
  S->N through): "2 is a right hand turn O and second right hand turn
  C." TWO vehicles, BOTH right turns, both booked as throughs. The
  floor removed one real vehicle; neither count was in the right cell.
