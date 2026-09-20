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

(Corrected by the operator mid-reel: his first three answers were
given against clips 4, 5 and 5, not 1, 2 and 3. Recorded here under
the clips he actually watched.)

  clip 4 (orange 132442 removed / cyan 132596 counted 23 s later,
  both booked S->N through): "a clean right turn C and exited through
  vehicle traffic O." TWO vehicles. The counted cyan track is a RIGHT
  turn booked as a through; the removed orange track is a real
  through that exited. The floor removed a real vehicle here.
  clip 5 (orange 130639 removed / cyan 130461 counted 46 s earlier,
  both booked through): "a right hand turn O and second right hand
  turn C" and "it is a different vehicle." TWO vehicles, BOTH right
  turns, both booked as throughs. The floor removed one real vehicle;
  neither count was in the right cell.
  clip 1 (orange 139644 removed / cyan 139655 counted 0.1 s later,
  both booked S->N through): "two different vehicles making right
  turns." TWO vehicles, both rights booked as throughs.
  clip 2 (orange 137465 removed / cyan 137490 counted 0.7 s later,
  both booked S->N through): "C is a right hand turn, O is a S to W
  queued vehicle that gets stolen from N to S through traffic." TWO
  vehicles. Cyan: a right booked as a through. Orange: a queued S->W
  vehicle whose track is stolen by N->S through traffic (theft class,
  docs/plan_theft_2026-09-11.md) and booked S->N through.
  clip 3 (orange 131179 removed / cyan 131119 counted 9 s earlier,
  near field, both booked S->N through): "O is a S to W queued
  vehicle that gets stolen from N to S through traffic. C is a right
  hand turn." TWO vehicles. Same anatomy as clip 2.

  Tally, five clips: 0/5 fractures. Every counted (cyan) track is a
  RIGHT turn booked as a through (5/5). The removed (orange) tracks:
  two rights (1, 5), one real through (4), two queued S->W vehicles
  stolen by N->S through traffic (2, 3). The 100 px floor raised
  cam5's score by deleting real vehicles that were sitting in the
  wrong cell - a lucky error, not a fix. cam5's large-basis through
  overcount is MISCLASSIFIED RIGHTS plus theft, not fragmentation.

How the five ruled rights were booked (d14 DB + crossing ledger):
four of five are GATE-FULL S->N journeys - both corners IN over the S
line, then OUT over the N line's upper end near (21,234) - with net
heading change +16 to +17 deg and straightness 1.00; the fifth
(131119) crossed nothing and went posterior to S->N. Their paths run
from about (445,180) left along the top of the frame to the left
edge, passing BELOW the E gate segment ((127,211)-(247,188)) without
touching it, then out over N. The classifier saw 16 deg of turn (its
through band is 25); the gate channel saw S in, N out; the label
S->N is 'through' by cardinal geometry. Still for the operator:
screenshots/cam5_rights_as_through.png.

Operator on the still of the five cyan paths (2026-09-11): "These
all look like through traffic." The still (track paths) and the reel
(the vehicle in the ring, ruled a right) disagree for the same five
tracks. Unresolved until he says which vehicle in the reel was the
right-turner; a track path that reads through while the ringed
vehicle turned right would mean the box changed vehicles (theft), the
class already ruled on clips 2 and 3.

  clip 1, RE-RULED on second viewing (2026-09-11, supersedes the
  earlier clip 1 line): "it is a detection drop and recapture of the
  same vehicle C and O is the same vehicle." ONE vehicle, a through
  on the far road (his reading of the still), fractured into two
  tracks 0.1 s apart at the same spot, BOTH counted S->N through.
  A duplicate count. The earlier clip 1-5 rulings were given during a
  clip-numbering mix-up and are to be re-confirmed one clip at a
  time before anything is built on them.
  clip 2, RE-RULED (supersedes): "two different vehicles through
  movements." TWO vehicles, both throughs. The floor removed a real
  through.
  clip 2, corrected by the operator immediately after: "go back to
  clip two, I over reacted it is one vehicle through traffic." ONE
  vehicle, a through, fractured into two tracks 0.7 s apart, both
  counted S->N through. A duplicate count (same anatomy as clip 1).
  clip 3, RE-RULED (supersedes): "clip 3 is two vehcles through
  traffic." TWO vehicles, both throughs; the floor removed a real one.
  clip 4, RE-RULED (supersedes): "clip 4 is 2 vehicles through
  traffic." TWO vehicles, both throughs; the floor removed a real one.
  clip 5, RE-RULED (supersedes): "two vehicles." TWO vehicles.

  FINAL TALLY (re-confirmed one clip at a time): clips 1 and 2, the
  pairs 0.1 s and 0.7 s apart at the same spot, are ONE vehicle each -
  a detection drop and recapture on the far road, both halves counted
  S->N through (a duplicate). Clips 3, 4, 5, the pairs 9, 23 and 46 s
  apart, are TWO vehicles each, all throughs, and the floor deleted a
  real vehicle in each. All ten tracks are through traffic on the far
  road; the earlier 'right turn' readings were the numbering mix-up.
  The discriminator is the GAP: a re-birth within about a second at
  the death point is the same vehicle; a re-birth many seconds later
  at the same queue position is the next vehicle.

## G-DEF-9, arm d16 (declared before scoring): THE FRACTURE RULE on the large basis

Why nothing in pass 2 caught clips 1-2: the chain rule refuses a pair
whose later half already owns a full journey (the recapture does: IN S,
OUT N), by design after ungated chaining merged followers; and the
conservation pass has never run under the default and only rejects
posterior-sourced events anyway. The pixel floor caught them by
accident and deleted three real vehicles for every two duplicates.

The rule (config.FRACTURE_DEDUP, turn_merge.fracture_track_dedup, run
in pass 2 after the twin dedup): reject the shorter event of every
pair where track A dies and track B is born within FRACTURE_GAP_S =
1.0 s at a point within FRACTURE_DIST_BOXES = 1.0 box lengths of A's
death, B outlives A, A lacks its exit crossing, and the endpoint
bearings agree within CHAIN_DIR_TOL_DEG. Constants from his two ruled
pairs (0.1 / 0.7 s; 0.64 / 0.91 box) and his three ruled non-pairs
(9 / 23 / 46 s). Box lengths, not pixels: a blank site's far field and
near field get the same test. Census forecast on the l1 dumps: cam5
1600 about 93 events fewer (75 throughs), cam1 1600 about 16 fewer.

d16 = the large basis everywhere (cam1/cam2 study_*, cam3/4/5 l1_*)
+ FRACTURE_DEDUP=1, all 12 windows, every other default as shipped.
PASS = the G-DEF-1 letter against 76.97 over 12 windows (fleet rises;
no camera -1.0; no window -3.0). FM51 (b-series, both windows) judged
alongside as the blank-site witness. If it passes, the joint default
(large basis + fracture rule) ships; if cam3's -5.2 under the large
basis does not close, the rule is judged on the CURRENT basis next
(d17) before anything ships.

### cam4 fracture-pair reel (d16 diagnosis), operator rulings (2026-09-11)

d16 on cam4 1600: the rule merged 423 pairs (371 S->N through), and
NB_thru went 2480 (+41 vs Mio) -> 2109 (-330). Either the pairs are two
vehicles (rule wrong on cam4) or one vehicle each and ~330 real NB
vehicles are missing elsewhere behind the duplicates. Reel of five
S->N pairs (frac4): orange enters over S and dies within a second,
cyan born 0.2 s later within 0.2-0.6 box lengths and exits over N.
  clip 1 (52836 / 52841, gap 0.2 s, 0.19 box): "same vehicle."
  clip 2 (48736 / 48741, gap 0.2 s, 0.25 box): "same vehicle."

## d16 verdict (recorded 2026-09-11): MISS on the letter, fleet-positive

  window       current   d16     delta      (d14 = large basis alone)
  cam1 0700     84.0     85.1    +1.1       (84.0)
  cam1 1600     95.3     95.3    +0.0       (95.3)
  cam2 0700     75.2     75.2    +0.0       (75.2)
  cam2 1100     75.7     76.7    +1.0       (75.7)
  cam2 1600     71.3     68.5    -2.8       (71.3)
  cam3 0600     87.6     82.6    -5.0       (82.4)  the large-basis loss, rule +0.2
  cam4 0700     71.1     79.2    +8.1       (75.0)  rule +4.2
  cam4 1100     74.5     74.0    -0.5       (82.0)  rule -8.0: NB_thru 1544 -> 1416 (Mio 1546)
  cam4 1600     75.4     69.6    -5.8       (78.6)  rule -9.0: NB_thru 2480 -> 2109 (Mio 2439)
  cam5 0700     73.3     73.1    -0.2       (69.2)  rule +3.9
  cam5 1100     71.4     76.9    +5.5       (73.1)  rule +3.8
  cam5 1600     68.9     73.1    +4.2       (69.2)  rule +3.9
  FLEET 76.97 -> 77.44 (+0.47); vs the large basis alone 77.58 (-0.14).
  cam3 -5.0 and cam4 1600 -5.8 fail the letter. MISS.

The rule does what it was built for on cam5 (+3.8 to +3.9 on all
three windows over the large basis) and on cam4 0700 (+4.2), and it
costs cam4 1100/1600 8-9 points by removing 130-370 NB throughs per
window from cells that stood within 41 of Miovision. The operator is
ruling the cam4 pairs now (clips 1-2 so far: same vehicle). If the
cam4 pairs are one vehicle each, the pre-rule NB_thru agreement was
duplicates cancelling an equal number of missed vehicles, and the
rule is right while the score says wrong; the missing vehicles become
the next question. If they are two vehicles, the constants are wrong
for cam4's near field and the box unit is not the invariant.
  clip 3 (48040 / 48042, gap 0.2 s, 0.30 box): "same vehicle."
  clip 4 (64097 / 64105, gap 0.2 s, 0.40 box): "same vehicle."
  clip 5 (60035 / 60043, gap 0.4 s, 0.63 box, neither crossed a line):
  "same vehicle."

  TALLY: 5/5 same vehicle. THE FRACTURE RULE IS RIGHT ON cam4. Its
  pre-rule NB_thru agreement (1544 vs 1546; 2480 vs 2439) was
  duplicates cancelling an equal number of MISSED northbound vehicles;
  the rule removes the duplicates and exposes the deficit (-130 and
  -330). The deficit is now the question: where are cam4's missing
  NB vehicles?

cam4 1600 NB deficit census (scripts/census_cam4_nb_deficit.py and an
NB-bearing census, 2026-09-12): the dump holds 2,718 northbound-
bearing tracks with >= 5 rows and >= 30 px of travel: 2,102 counted
S->N, 373 rejected (the fracture pairs), 243 with no event - and of
those 243 only 66 travelled >= 50 px (median 45 px, 21 px boxes,
dying at the far edge). Miovision: 2,439 NB throughs. The ~330
missing vehicles are NOT in the dump as droppable tracks; they were
never tracked as their own NB track (the far-field detection / theft
floor already closed, plan_theft_2026-09-11.md). Only 1,554 tracks
ever crossed the S line; the rest of the NB count is posterior.
The rule stands correct (10/10 rulings across cam4 and cam5); its
cam4 1100/1600 score cost is the instrument's deficit becoming
visible.

## Arm d17 (declared before scoring): THE FRACTURE RULE on the CURRENT basis

d16's fleet number carries cam3's -5.0 from the large basis, not from
the rule. d17 isolates the rule: current production basis on every
camera (cam1/cam2 study_*, cam3/4/5 fine-tune study_*), FRACTURE_DEDUP
=1, all 12 windows, every other default as shipped. PASS = the G-DEF-1
letter against 76.97. FM51 b7 = the rule on the blank site's two
windows alongside (b6 79.6 / 80.0 is the comparison). Whatever d17
scores, the ship decision on a rule that is correct by ruling but
costs cam4 1100/1600 by exposing a detection deficit is the
operator's, and is put to him with both numbers.

## d17 verdict (recorded 2026-09-12): the rule alone is fleet +0.99; one window fails the letter

  window       current   d17     delta
  cam1 0700     84.0     85.1    +1.1
  cam1 1600     95.3     95.3    +0.0
  cam2 0700     75.2     75.2    +0.0
  cam2 1100     75.7     76.7    +1.0
  cam2 1600     71.3     68.5    -2.8
  cam3 0600     87.6     88.5    +0.9   (NB_thru +224 -> +161, SB_thru +266 -> +105)
  cam4 0700     71.1     73.3    +2.2
  cam4 1100     74.5     78.7    +4.2   (NB_thru +108 -> -105)
  cam4 1600     75.4     70.2    -5.2   (NB_thru -48 -> -414: the exposed deficit)
  cam5 0700     73.3     79.0    +5.7
  cam5 1100     71.4     73.3    +1.9
  cam5 1600     68.9     71.8    +2.9
  FLEET 76.97 -> 77.97 (+0.99). Cameras: cam1 +0.55, cam2 -0.60,
  cam3 +0.90, cam4 +0.40, cam5 +3.50. Letter: fleet rises, no camera
  past -1.0, ONE window past -3.0 (cam4 1600). MISS by that window.
  FM51 b7: +2.0 / 0. Rulings: 10/10 pairs one vehicle.

The ship decision is the operator's: the rule is correct by his own
rulings and lifts nine windows, holds two, and costs one (cam4 1600)
by removing duplicates that had been masking a far-field detection
deficit already closed as instrument-limited. Put to him 2026-09-12.

## SHIPPED — THE FRACTURE RULE (operator go 2026-09-12: "update the default with the fracture rule")

The operator's ruling on the open decision: SHIP, accepting cam4 1600
at 70.2 because its old 75.4 was two errors cancelling (~366
duplicate NB throughs against an equal far-field detection deficit
that is not in the dump; instrument-limited, no counting rule
recovers it). Future cam4 1600 movement is read against 70.2.

backend/config.py FRACTURE_DEDUP default "1" (commit bb78362);
test_default_off -> test_default_on; 1226 green, no env flags set.
scripts/reprocess_default.py guards the six rules and compares
against the d17 arm (total/kept, since replay.events counts the
write-then-rejected rows too). Backup
backups/project_20260912T010419_pre_default_reprocess_fracture.db
(467 MB). All 12 windows reprocessed under the default (force_once,
apply through the gate; ~55 min serial, cam3 27 of them). Production
event rows IDENTICAL to the d17 arm on 12 of 12 (row-for-row hash);
re-score PRODUCTION == ARM on 12 of 12 (runs/v2_week1/
score_d17_*.json, rescore_fracture_20260912.log).

  window       was     now    delta   health
  cam1 0700    84.0    85.1   +1.1    amber
  cam1 1600    95.3    95.3    0.0    green
  cam2 0700    75.2    75.2    0.0    green
  cam2 1100    75.7    76.7   +1.0    green
  cam2 1600    71.3    68.5   -2.8    green
  cam3 0600    87.6    88.5   +0.9    amber
  cam4 0700    71.1    73.3   +2.2    amber
  cam4 1100    74.5    78.7   +4.2    green
  cam4 1600    75.4    70.2   -5.2    amber   accepted by ruling
  cam5 0700    73.3    79.0   +5.7    amber
  cam5 1100    71.4    73.3   +1.9    green
  cam5 1600    68.9    71.8   +2.9    red
  FLEET        76.97   77.97  +0.99

FM51 stays the held-out witness (b7 81.6 / 80.0; +2.0 / 0 over b6);
its counts are not shipped. The default is now six rules:
GATE_GROUND_ANCHOR, STRAIGHT_FRAGMENT_RULE, GATE_EVIDENCE_EITHER_CORNER,
JOURNEY_STATE_MACHINE, STRAIGHT_FRAGMENT_INCLUDE_PATH_FITS,
FRACTURE_DEDUP; bar 0.20. CLAUDE.md, scripts/fleet_flags.py `_ALL`
and memory carry 77.97. Next candidate: whatever closes cam4 1600's
NB far-field deficit is a DETECTION question (the vehicles were never
tracked), not a counting one; declared before scoring, one arm at a time.

## cam4 NB deficit — the census (2026-09-12, after the fracture rule shipped)

Operator: "yes sure" to opening cam4 1600's NB question as the next arm.
The ledger had called it a DETECTION question (the vehicles "never
tracked"). Measured tracker-independently, it is not: the detector sees
every northbound vehicle; the TRACKER births the nearest lane late and
in pieces.

Instrument (scripts/probe_cam4_nb_crosssection.py): deduped raw
detections (class-agnostic NMS 0.6, conf >= 0.25) greedy-linked into
chains; distinct chains and distinct pass-1 tracks crossing vertical
cross-sections rightward (NB = S->N travels left to right, near field
to the vanishing point at the right). Per window:

  window     Mio NB_thru   chains x=200   chains x=550   tracks x=300   counted S->N
  cam4 0700     2713          2317           2708           2098           2462
  cam4 1100     1546          1333           1564           1287           1441
  cam4 1600     2439          1966           2412           1712           2025

The detector's chains match Miovision within 1% at the FAR end on all
three windows; at the NEAR end they run 14-20% short, the tracker 17-30%.

Where the far-only chains begin (scripts/probe_cam4_nb_emergence.py,
1600): of 2486 chains crossing x=550, 469 begin past x=350 — median
first box 215 px wide, median first y 478 = the BOTTOM EDGE of the
480-px frame, median conf 0.36. The nearest NB lane enters the picture
over the bottom edge at x 350-520 (frame strips screenshots/
cam4_study_1600_emergence_{1..4}.png), never over the S line at x~150.
0700: 454 such entrances. Per 15-min bin they track the deficit (1600:
[60,61,64,49,77,54,59,45] entrances vs [43,52,43,42,78,56,51,49] short).

What the tracker does with them (coverage, 1600): 64 never covered by
any track; 405 covered — first at the chain's 3rd hit (median), i.e.
x 500-600 with the box already down to 130 px; 328 by a track born
there, 77 by an OLDER track (id hand-off; 20 of those carry a counted
N->S: a southbound id continuing on the northbound car).

Why they leave no event (scripts/census_cam4_edge_births_pass2.py,
pass-2 replayed apply=False with finalize instrumented): the covering
tracks are 5 points / 46 px of travel at the median (p25: 2 pts / 21
px). 139 get origin S and die at insufficient_data (destination), 105
get no origin, 39 have <2 points, 14 take origin N. 56 of 469 end in a
counted S->N. Corridor-wide in that window: 554 NB-bearing tracks with
no event, 415 of them origin-S insufficient_data, 192 born at the
bottom edge with a 200-px box.

Mechanism: at 10 fps a vehicle in the nearest lane, receding toward the
vanishing point, shrinks 220 -> 50 px within a second or two; sv
ByteTrack's IoU association loses it repeatedly (the far-field
fragments born at x 500-550, 53 px, 660 of them, are its pieces), so no
piece carries origin and destination, and the short near piece drops.
The blank site FM 51 runs the same default recipe (bytetrack, buffer
1.0, activation 0.25, match 0.8); cam3 alone runs a buffered IoU (1.3).
Logs: runs/v2_week1/probe_cam4_nb_xs_study_*.log,
probe_cam4_nb_emergence_*.log, census_cam4_edge_births_pass2_1600.log.
Note for any pass-1 candidate: run_pass1 writes the INFLATED boxes to
the dump when bbox_buffer != 1, so a buffer moves pass-2 geometry
(bottom-centre, box-length unit) as well as the association.

### Where the near-lane vehicle is lost, step by step (2026-09-12, instruments on cam4 1600)

Death points (scripts/probe_cam4_nb_death_point.py, frames in
screenshots/cam4_1600_death_points.png, cam4_nf1600_death_points.png):
the near piece's tracker box at death is a huge, wrong box (Kalman state
poisoned by the birth from a frame-edge-clipped strip: wide and short,
then suddenly tall); the next frame's tight detection (conf 0.6-0.9)
overlaps it at 0.16-0.25, and supervision ByteTrack refuses it — 180 of
241 mid-frame deaths fall to its score fusion (IoU x conf < 0.2), the
rest to geometry. With fusion off (TRACKER_FUSE_SCORE=0, built today,
default ON, 1229 tests green; scratch dump nf_study_1600): 460 of 469
entrances covered, first at the chain's 2nd hit, but the pieces stay
short and 82 (not 56) end in a counted S->N. Buffered IoU 1.5
(bb15_study_1600): 103. Neither closes it alone.

The chains show the vehicle's whole life: enters over the bottom edge
at x~440 (215 px), recedes along the road and ENDS at x~628, y~297 in a
14-px box — at the vanishing point, ABOVE the drawn N line (only 6%
end below it). So every bottom-edge vehicle does pass the N line; it
passes it UNTRACKED, in the gap between the near piece's death (x 520-
600, box 100+) and a far piece's birth (15-50 px, y~300, already above
the line). The far pieces then crawl to the vanishing point: 333 NB-
bearing tracks with no counted event die at x>=600, y~301, box 15 px;
pass 2 (census_cam4_edge_births_pass2.py, instrumented) drops 483 such
origin-S tracks at the DESTINATION stage — score_destination_leg
refuses because the tail moved < EXIT_DISPLACEMENT_MIN_PX (20 px):
death x median 626, 463 of 483 at x>=600, 17 points, 73 px of travel.
That is the pixel-motion floor of the far field, not a counting error.

Reading: the N line sits at the far mouth where the boxes die — the
placement the blank-site ruling of 09-11 forbids ("where vehicles are
reliably TRACKED, inside the mouth, never at the far mouth"). The near
pieces (100-px boxes, fast, tracked) die at x 520-600; a line drawn
there would be crossed by them while tracked, giving S(heading) -> N
(gate) full journeys. Instrument next: candidate N lines on the
production dumps, pass-2 tags only, before anything is drawn.

### Why the tracker breaks — the research (operator ask 2026-09-12: "research why the tracker is breaking")

Ground truth for one vehicle = its detection chain (469 bottom-edge NB
vehicles, 1600; runs/v2_week1/vehicles_study_1600.json; scripts/
research_tracker_break.py timeline; log research_tracker_break_1600.log).
Production dump: track ids per vehicle 0:66 1:182 2:169 3:41 4+:11;
first track 2 detections after entry (p75 5); 636 breaks, 554 of them
into an untracked gap (median 2 frames), 82 straight to another id.
WHERE: 562 of 636 breaks at x >= 550, 374 at x >= 600 — the far field,
real box 29 px wide, where the vehicle spends its last ~20 frames
crawling to the vanishing point; only ~50 breaks below x=550. The
bottom-edge birth is a 2-frame delay and a minority of the breaks (the
Kalman "giant box" cases are 27% of breaks and mostly NOT at the edge).
WHY, at the break, the next real box of the same vehicle is refused:
  305  conf >= 0.25 but IoU x conf < 0.2   (supervision's stage-1 fusion)
  133  conf < 0.25 and IoU < 0.5           (stage 2 demands IoU 0.5; and
                                            a box under 0.25 cannot start a track)
  109  conf >= 0.25, fused >= 0.2          (should match; taken by another id)
   89  conf < 0.25, IoU >= 0.5             (stage 2 should match)
Next-box conf median 0.29 at the breaks (35% under 0.25): the breaks
fall on the far field's weak frames. Consecutive REAL boxes of the same
29-px vehicle overlap only 0.50 (median) at 10 fps; the tracker's
Kalman-predicted box overlaps the next real box LESS (0.41) — the
motion model hurts in this regime. Detector confidence on these same
vehicles at x 600-640: yolo26s@960 (production) median 0.45, 75% >= 0.25;
yolo26l@1280 0.63, 90%; yolo26s_ft2@640 0.84, 91%. The l1 dump's
timeline: 593 breaks, ids per vehicle 0:29 1:188 2:202 — better
detection alone does not hold the vehicle; the association does not.
Fusion off (nf): 823 breaks, 284 hand-offs — worse, low boxes grabbed by
wrong ids. Buffer 1.5: 668 breaks, tracker box 1.65x the real one.
DEMONSTRATION that the vehicles ARE trackable: the census's own greedy
linker (velocity-predicted centre, gate 0.9 x box width, any conf >=
0.10, 5-frame patience) holds each of them as ONE chain of 24 hits
(median) from the bottom edge to the vanishing point. Distance-in-box-
units association holds what IoU-with-fusion drops.

## G-DEF-10, arm d18 (declared 2026-09-12 before scoring): POSITION RECOVERY in the default tracker

Operator: "research why the tracker is breaking" -> "sure plan it out"
(plan approved). Built: config.TRACKER_POSITION_RECOVERY (default OFF),
TRACKER_RECOVERY_REACH 0.9 box widths, TRACKER_RECOVERY_SIZE_RATIO 0.3;
backend/services/tracker.py _RecoveringByteTrack — supervision 0.17.1
ByteTrack with stage 2.5: after stage 1 (IoU x conf) and stage 2 (low
dets, IoU 0.5), the tracks still unmatched (tracked leftovers AND lost)
meet the detections still unmatched (high AND low, conf >= 0.10) on
centre distance in box units against the Kalman-predicted box, greedy
nearest-first, one-to-one; a recovered detection never births. Births,
fusion, everything else verbatim (REACH 0 is byte-identical to the
library; the fork is pinned to sv 0.17.1). Recorded in the dump meta
(position_recovery) and the resume guard. backend/tests/
test_tracker_recovery.py, 14 tests; suite 1243 green.

Tracker-level instrument (cam4 1600, pr_study_1600 vs study_1600, the
469 bottom-edge vehicles' chains as truth):
  ids per vehicle           0:66 1:182 2:169 3:41 4+:11  ->  0:52 1:224 2:147 3:37 4+:9
  breaks                    636 (554 gaps, 82 hand-offs)  ->  437 (99 gaps, 338 hand-offs)
  hand-offs, who took it    (base) twin 18, tracked 28, lost 16, new 20
                            (pr)   twin 168, tracked 62, lost 2-5 f 57, lost >5 f 36, new 15
  distinct tracks crossing  x=300 1712 -> 1909;  x=550 1694 -> 2339  (chains 2412, Mio 2439)
  bottom-edge vehicles ending in a counted S->N (pass-2 replay, apply=False): 56 -> 103
The gaps are closed: the vehicle is covered to the vanishing point. Half
the new hand-offs are TWIN boxes of the same vehicle (the detector's
car+truck double box, dealt with by the twin dedup); genuine steals rose
~44 -> ~155, 36 of them by ids lost > 5 frames (the linker had 5 frames
of patience; the tracker keeps lost ids 50). That is the arm's risk.

What still drops them is PASS 2: on the pr dump 537 long NB tracks
(>= 15 points, reaching x >= 550) have no counted event; 95% cross the
drawn N segment; the gate machinery tags 316 of them "-->N exit_only"
(exit observed at a median 26 px/frame, not creep) — and the finalize
path has NO branch that binds an observed EXIT-ONLY crossing: origin by
heading, softmax destination refused (tail < 20 px at the vanishing
point) -> insufficient_data. The "box sides ARE the gates" ruling covers
this case and the code does not. That is a counting default candidate
of its own (G-EX-2, declared after d18's verdict), not part of d18.

d18 = TRACKER_POSITION_RECOVERY=1 in pass 1 for every window on the
default recipe: cam4 x3, cam5 x3 re-tracked from their caches into
pr_study_* (cams 1-3 run BoT-SORT recipes: unchanged, scores stand);
pass 2 under the shipped default, no env flags. FM51 cam2
l1_study_0700/1600 re-tracked into pr_l1_study_* as the witness (b7
81.6 / 80.0). PASS = the G-DEF-1 letter against 77.97. The number to
watch for harm: follower merges (NB_thru / NB_left under Mio where they
were at or over it), the 2026-05-29 failure.

## d18 verdict (recorded 2026-09-12): MISS — the stage over-merges

  window        live    d18    delta   NB_thru (Mio | live | d18)     SB_thru (Mio | live | d18)
  cam4 0700     73.3    81.8   +8.5    2713 | 2462 | 2145              1957 | 2040 | 1927
  cam4 1100     78.7    80.0   +1.3    1546 | 1441 | 1231              1640 | 1751 | 1637
  cam4 1600     70.2    66.7   -3.5    2439 | 2025 | 1665              2981 | 3055 | 2720
  cam5 0700     79.0    64.3  -14.7    2379 | 2374 | 1873              1868 | 1973 | 1446
  cam5 1100     73.3    71.8   -1.5    1362 | 1435 | 1184              1496 | 1654 | 1340
  cam5 1600     71.8    66.1   -5.7    2185 | 2290 | 1840              2819 | 3023 | 2432
  six-window mean 74.38 -> 71.78 (-2.60); fleet of 12 would be ~76.7 vs 77.97.
  FM51 witness: 81.6 / 80.0 (b7) -> 65.2 / 68.5; NB_thru 856 -> 699 (Mio 853),
  SB_thru 462 -> 362 (Mio 614).  MISS on the letter on four corridor
  windows and on the witness.

Reading: every through cell FALLS under the stage, on every window,
while the tracks demonstrably reach further (cam4 1600: 2339 distinct
tracks cross x=550 vs 1694). Two mechanisms, both measured:
(1) STEALS — on FM51 0700 the stage fires 8,934 times in two hours and
    the track count drops from 2,292 to 1,485: a live track that misses
    its IoU match takes the nearest box within 0.9 widths, often a
    neighbour's (scripts/research_recovery_steals.py labels them against
    the library's tracks; see the log for the cost / age / direction
    split). The 2026-05-29 follower-merge failure, inside association.
(2) PASS 2 REFUSES THE COMPLETED JOURNEY — the fragments the shipped
    default used to complete by posterior are now long tracks with an
    observed EXIT-ONLY N crossing and a softmax destination refused for
    tail motion (< 20 px at the vanishing point); finalize has no branch
    binding an exit-only crossing, so the long track drops where its
    fragments used to count (cam4 1600: 537 such tracks, 316 tagged
    -->N exit_only).
cam4 0700's +8.5 is what the stage does where the steals are cheap and
the exits are observed while moving; the same stage on cam5 0700 costs
14.7. TRACKER_POSITION_RECOVERY stays OFF; the code stays as the
built-not-shipped candidate. Next: split the steal population by the
logged cost / age / direction to see whether a principled gate (motion-
consistent jump, short patience) separates same-vehicle recoveries from
steals; and G-EX-2 (bind an observed exit-only crossing) as its own
counting arm, since without it a longer track cannot score.

### d18 diagnosis: where the steals live (2026-09-12, scripts/research_recovery_steals.py)

Every recovery logged (tracker run in-process over the cache), labelled
against the library's own tracks: a recovery is a STEAL when the box
belongs to a different library track that was alive at the same time as
the one the recovering track had been following (two vehicles).
  FM51 0700: 8,934 recoveries (tracks 2,292 -> 1,485); labelled: same
  vehicle 1,847, steal 391, unlabelled 6,696 (the library had no track
  on that box).  cam4 1600: 32,528 recoveries (8,986 -> 5,762); same
  7,312, steal 1,937, unlabelled 23,279.
  Neither lost age, nor cost in box widths, nor jump direction separates
  them. OVERLAP does:
    IoU(predicted box, recovered box)    FM51 steal share   cam4 steal share   share of the same-vehicle recoveries kept
      0 (no overlap)                          10%                20%
      (0, 0.1]                                11%                19%
      (0.1, 0.2]                               7%                11%
      > 0.2                                    3%                 3%          92% (FM51) / 88% (cam4)
  A recovery to a box that still overlaps the prediction by > 0.2 is the
  fusion / stage-2 refusal the stage was built for; a jump to a box that
  does not overlap is a neighbour three to seven times as often.
FM51's counts fell to steals, not to pass 2: the pass-2 replay on FM51
0700 shows 167 (base) vs 195 (pr) long tracks with no event — the
exit-only gap is cam4's geometry, not FM51's.
Built: TRACKER_RECOVERY_MIN_IOU = 0.2 (the recovered box must overlap the
predicted box by the same geometric bar stage 1 uses; 0 = d18), recorded
in the dump meta (recovery_min_iou) and the resume guard; test added.

## G-DEF-10, arm d18b (declared 2026-09-12 before scoring): the recovery stage WITH the overlap gate

d18b = d18 with TRACKER_RECOVERY_MIN_IOU 0.2: a leftover track continues
onto a box only if the box still overlaps its predicted box by >= 0.2,
whatever the box's confidence (no fusion, no 0.5 bar for weak boxes);
no jumps. Everything else as d18 (reach 0.9, size ratio 0.3, births
unchanged). Tracker level, cam4 1600 (pr2_study_1600 vs base / d18):
  ids per vehicle   base 0:66 1:182 2:169 3:41 4+:11 | d18 0:52 1:224 2:147 3:37 4+:9 | d18b 0:70 1:263 2:119 3:12 4+:5
  breaks            636 (554 gaps, 82 hand-offs) | 437 (99, 338) | 267 (165 gaps, 102 hand-offs: 28 twins, 29 live neighbours, 28 lost ids, 17 births)
  tracks crossing   x=300 1712 | 1909 | 1887;  x=550 1694 | 2339 | 2124  (chains 2412)
  FM51 0700 recoveries 8,934 -> 4,927; tracks 2,292 (library) -> 1,485 (d18) -> 1,802 (d18b);
  labelled steals 391 -> 189 (same-vehicle 1,847 -> 782).
Windows: cam4 x3, cam5 x3 into pr2_study_*, FM51 cam2 into pr2_l1_study_*;
pass 2 the shipped default. PASS = the G-DEF-1 letter against 77.97; FM51
against b7 81.6 / 80.0. Known limit carried in: pass 2 still drops a long
track with an exit-only crossing (G-EX-2 not built), so cam4's gain is
capped by counting, not by tracking.

## d18b verdict (recorded 2026-09-12): PASS on the letter, +2.39 fleet

  window        live    d18b   delta   NB_thru (Mio | live | d18b)   SB_thru (Mio | live | d18b)   notes
  cam4 0700     73.3    80.9   +7.6    2713 | 2462 | 2412            1957 | 2040 | 2033            SB_right 46 -> 31 (Mio 22)
  cam4 1100     78.7    80.9   +2.2    1546 | 1441 | 1344            1640 | 1751 | 1708
  cam4 1600     70.2    71.7   +1.5    2439 | 2025 | 1980            2981 | 3055 | 2976            SB_right 125 -> 96 (Mio 39)
  cam5 0700     79.0    79.8   +0.8    2379 | 2374 | 2354            1868 | 1973 | 1927            NB_left 418 -> 402 (Mio 335)
  cam5 1100     73.3    79.0   +5.7    1362 | 1435 | 1416            1496 | 1654 | 1550            NB_left 352 -> 312 (Mio 185)
  cam5 1600     71.8    82.7  +10.9    2185 | 2290 | 2227            2819 | 3023 | 2923            NB_left 367 -> 338 (Mio 240)
  cams 1-3 unchanged (BoT-SORT recipes): 85.1 95.3 75.2 76.7 68.5 88.5
  six-window mean 74.38 -> 79.17 (+4.78); FLEET of 12: 77.97 -> 80.36 (+2.39)
  letter: fleet rises; cam4 +3.8, cam5 +5.8 (no camera -1.0); every window up (no window -3.0). PASS.
  FM51 witness (b7 -> d18b): 0700 81.6 -> 80.4 (approach 54.2 -> 62.5), 1600 80.0 -> 80.4
  (approach 50.0 -> 66.7); NB_thru 848 (Mio 853), 786 (811); SB_thru 478 -> (Mio 614), 884 (1086).
  Scores: runs/v2_week1/score_d18b_*.json, fleet_d18b.log, fm51_d18b.log.

Reading, honestly: the gain is the OVERCOUNTS coming down — SB_thru and
the SB_right / NB_left phantoms shrink toward Miovision on every window,
because the vehicle is now one track instead of two or three fragments
each completed by posterior. The northbound SHORTFALL that opened this
work is NOT recovered: cam4 NB_thru 2412 / 1344 / 1980 against 2713 /
1546 / 2439, marginally lower than live. The tracks now reach the N
line (x=550 crossings 1694 -> 2124) but pass 2 refuses the journey whose
exit crossing was observed and whose softmax destination fails on tail
motion (the exit-only gap, G-EX-2, not built) — and the fragments the
straight-fragment rule used to complete no longer exist. Watch cells:
cam5 EB_right 91/89/101 -> 76/64/87 (Mio 188/162/244), already the
camera's worst cell, a little worse; cam4 NB_left 20 -> 13 (Mio 23).
Follower merges did not appear as NB_thru/NB_left collapse anywhere.

Ship = TRACKER_POSITION_RECOVERY default "1" (the recipe for every
default-backend camera: cam4, cam5, any blank site), promote the pr2
dumps to study_* (rename-aside the current dumps, the l1 precedent),
reprocess cam4 x3 / cam5 x3 through the apply gate with the pre-ship
backup, re-score production == arm, standings to _ALL, CLAUDE.md. The
decision is the operator's.

## TRACKER ENGINEERING LOG (operator 2026-09-12: "improving the engineering of the tracker;
## how we get there is undetermined" — scoring set aside, the chains are the yardstick)

The recovery stage with the overlap gate is now the default backend's behaviour
(TRACKER_POSITION_RECOVERY default "1"; env X=0 is the experiment override). Production
dumps and standings untouched until the operator says so.

Yardstick: cam4 1600's 469 near-lane vehicles (chains), scripts/research_tracker_break.py
timeline. Columns: ids per vehicle (0 = never tracked / 1 = one track / 2 / 3+), breaks
(gaps / hand-offs), hand-off kinds.

  dump                         0 / 1 / 2 / 3+       breaks (gaps / hand-offs)   twins  steals  births
  library (study_1600)         66 / 182 / 169 / 52   636 (554 / 82)               18     44     20
  recovery, no gate (pr)       52 / 224 / 147 / 46   437 (99 / 338)              168    155     15
  recovery, IoU>=0.2 (pr2)     70 / 263 / 119 / 17   267 (165 / 102)              28     57     17
  pr2 + pre-track NMS 0.6 (nm) 69 / 271 / 114 / 15   224 (161 / 63)                2     50     11
  pr2 + confirm-by-position    4 / 140 / 215 / 110   739 (286 / 453)             244     87    122
    (cp; no NMS)

Never-tracked vehicles (70 on pr2): 207-px boxes at the bottom edge, max conf 0.57, 86%
with two or more consecutive confident boxes — killed at CONFIRMATION (the library
demands IoU x conf >= 0.3 on the very next frame and never offers a weak box; the edge
strip becomes a full box). Confirmation by position (an unconfirmed track unmatched by
the library pass takes a remaining box that overlaps it and keeps its width) removes the
class (70 -> 4) but, without pre-track NMS, confirms the detector's DUPLICATE boxes too:
twins 28 -> 244, births 17 -> 122. NMS is the prerequisite for confirmation; next run:
NMS 0.6 + recovery + confirmation (cn), 1600 and 0700.

### Tracker engineering, state at end of 2026-09-12 (all components now the default backend's behaviour)

The recovery tracker = supervision 0.17.1 ByteTrack fork (backend/services/tracker.py
_RecoveringByteTrack), used by every camera on the default recipe (cam4, cam5, any blank
site; cams 1-3 run BoT-SORT recipes and are untouched). Components, each measured:
  1. POSITION RECOVERY (stage 2.5): leftover tracks (tracked + lost <= 0.5 s) x leftover
     boxes (any conf >= 0.10): centre distance < 0.9 box widths, widths within 0.3, box must
     overlap the predicted OR last-observed box >= 0.2; greedy nearest-first.
  2. CONFIRMATION BY POSITION: a newborn the library's IoU x conf pass drops is confirmed
     by an overlapping, width-consistent box (edge strips becoming full boxes).
  3. MOTION-STATE RESET: confirmations and any match whose width jumps > 1.5x restart the
     Kalman state from the observed box (the "giant box" poisoning).
  4. EDGE EXIT: a track that drives out of the frame (last box on the edge, moving toward
     it) is retired, not parked 5 s as a lost id (FM51 stale-id steals 529 -> 64).
     Frame size from the videos row (pass 1 and the live pipeline).
  5. DOUBLE-BOX DEDUP at input: pairs > 0.8 IoU, any class (measured one vehicle 99-100%;
     0.6-0.8 is two vehicles 2-14%: left to the tracker). scripts/research_dup_boxes.py.
  6. STACKED-BOX GUARD: a box stacked > 0.6 on a vehicle already held this frame neither
     confirms a newborn nor births a track (86-98% of those are double boxes).
Recorded in the pass-1 dump meta + resume guard; backend/tests/test_tracker_recovery.py
(24 tests); suite 1253 green. Env X=0 turns any component off for experiments.

Yardstick (scripts/research_tracker_break.py timeline / timeline_all; chains = one vehicle):
  window (vehicles)                    one track: library -> now     breaks: library -> now
  cam4 1600 near-lane NB (469)              182 -> 362                   636 -> 274
  FM51 0700 all moving (1524)               570 -> 1094                 2928 -> 855
  cam5 1600 all moving (5742)              1964 -> 3332                16682 -> 5007
Remaining on cam5 (dense): hand-offs to a live neighbour's track 1194, fresh births on
the vehicle 949, stacked twins 520, other vehicles' ids lost 0.2-0.5 s 406 and > 0.5 s
180, gaps 1498. The yardstick is itself a greedy linker: in dense queues some of its
"hand-offs" may be its own swaps; treat cam5's residual classes as indicative.
Measured and rejected along the way: fusion off (hand-offs up), 1.5 box buffer (tracker
box 1.65x the real one), ungated recovery (steals; d18), pre-track class-agnostic NMS 0.6
(merges real occluded pairs; the chain yardstick cannot see that because it is built on
0.6-deduped boxes), lost-id patience alone (did not touch stale steals: they came from
the library's stage-1 re-find of ids parked at the frame edge).
Production dumps and standings are unchanged (built by the library tracker). Any pass-1
run from now on (re-track, new study, live processing) uses the recovery tracker. The
counting default was tuned on fragmented tracks; the observed-exit binding (G-EX-2) is
the counting work these longer tracks need.

### Hand-off reel, cam5 study_1600 (2026-09-12) — operator rulings

Why: after the tracker work the chain yardstick still reported 748 neighbour takeovers and
683 fresh births on cam5 1600; the yardstick is itself a greedy linker, so the residual
classes were put on film before engineering against them. scripts/viz_handoff_reel.py on
dump tk3_study_1600 (recovery tracker defaults): six clips, even spread over each kind, a
minute clear of the window ends, full frame, 2.5 s either side. Reel page (frame-stepping
player): https://claude.ai/code/artifact/5ab8a5ed-3f02-4853-86c7-220275798de3

OPERATOR RULINGS (his words):
  1  takeover 49 -> 64, 16:01:15.2   "No there is a handoff from O to C."
     Reading (frames 20-31 checked): orange = a white car, cyan = the dark vehicle stacked
     directly behind it behind the white van's roof; both tracked on their own before and
     after; the RING jumps from orange's car to cyan's at the hand-off. YARDSTICK ERROR -
     the tracker kept both ids right.
  2  takeover 5119 -> 5122, 17:04:35.0   "clip to O and W are tracking a trailer, the handoff
     to C is the handoff from tailer to towing vehicle, same vehicle technically"
     Reading: orange (tracker) and the ring (yardstick) are both on a flatbed trailer; cyan
     is the dark pickup towing it. TWO TRACKER IDS ON ONE RIG - the towed trailer is
     tracked as a vehicle of its own (a double-count risk for the counting side), a new
     class, not a swap between cars. The yardstick's hand-off is trailer -> tow vehicle.
  3  takeover 9341 -> 9340, 17:58:32.5   "Clip three is correctly tracking two vehicles but
     as they disappear into the horizon C and O collapses together"
     Reading: two vehicles, two tracker ids, both right; as they recede into the horizon
     their boxes collapse together and the ring's hand-off falls at the collapse.
     YARDSTICK ERROR. (Cyan 9340 is the id born on the van in clip 6, 3.7 s earlier.)
  4  birth 38 -> 57, 16:01:09.0   "Clip 4 already begins with a theaft from O, C comes into
     view as traffic begines to move from the Queue and W tracks C the whole time"
     Reading: the ring (yardstick) is on one vehicle the whole clip - YARDSTICK RIGHT. Orange
     is a stolen id before the clip starts (its path runs in from the lower left and hooks
     into the queue); cyan is the car's own id, born as it comes into view when the queue
     moves. TRACKER ERROR = THE EARLIER THEFT (the theft class), not the birth.
  5  birth 4548 -> 4559, 16:57:24.3   "5 W tracks C the whole time for two vehicles waiting
     in the queue"
     Reading: the ring stays on one car (cyan's) the whole clip - YARDSTICK RIGHT. Two
     vehicles in the queue; the second (cyan's) car had no tracker id of its own until the
     hand-off although it was visible ~1 s earlier. TRACKER ERROR = LATE BIRTH of a car
     pulling out from behind another.
     Cause, measured: the car's boxes in the 1.5 s before its birth had conf 0.10-0.33 and
     overlapped orange's box only 0.13-0.28 (NOT the 0.6 stacked-box guard). A new track
     needs one box >= det_thresh 0.35 (activation 0.25 + 0.1); its first came at the
     hand-off. Class: a partly hidden car's weak boxes cannot start a track.
  6  birth 9338 -> 9340, 17:58:28.8   "6 C and O are two different vehicles. O is blocking a
     vehicle, onces the vehicle comes into view, O handsoff to the new vehicle and C tracks
     the existing vehicle. W starts on O and then stays with the Vehicle as O becomes C."
     Reading: YARDSTICK RIGHT. The van (entering over the left edge) carried orange; when
     the SUV it was hiding came into view, orange went to the SUV and the van was re-born
     as cyan. TRACKER ERROR = THEFT AT DISOCCLUSION.
     Cause, measured: van box 44 -> 99 -> 154 px wide in two frames while moving ~50 px/f;
     the 1.5x width jump tripped the MOTION-STATE RESET, which restarted the Kalman state
     with ZERO velocity, so orange's prediction stayed at the edge, the SUV appeared there,
     orange matched it, and the van's real box went unmatched and was born. A defect in
     component 3 (my reset), not the stacked guard (IoU with orange 1.00/0.68 = the van).

  TALLY (6 clips): yardstick errors 2 (clips 1, 3: the ring jumps between stacked / merging
  boxes, the tracker right). Tracker errors 4: trailer tracked as its own vehicle (2),
  theft (4 earlier, 6 at disocclusion - caused by the zero-velocity reset), late birth of a
  partly hidden car's weak boxes (5, birth bar 0.35). The yardstick overstates the dense-
  traffic residual by about a third; the tracker classes are real.

  FIX from clip 6 (component 3, the motion-state reset): the reset now keeps the vehicle's
  motion - centre velocity restarts from the observed displacement since the last observed
  box - and drops only the shape state. Test added (an entering vehicle keeps its id while a
  second enters behind it); suite 1254 green. Yardstick, tk3 -> tk4:
    cam4 1600 near-lane NB (469)   one track 362 -> 381   breaks 274 -> 255
    FM51 0700 (1524)               one track 1094 -> 1165 breaks 855 -> 779
    cam5 1600 (5742)               one track 3332 -> 3405 breaks 5007 -> 4755
  (library tracker for reference: 182 / 570 / 1964 one-track; 636 / 2928 / 16682 breaks)
  Remaining tracker classes named by the reel: late birth of a partly hidden car's weak
  boxes (birth bar 0.35), a towed trailer tracked as its own vehicle, theft at occlusion.

### Sizing the remaining classes (2026-09-12, tk4 dumps, scripts/research_tracker_classes.py,
### scripts/research_late_births.py)

LATE BIRTH (first 0.5 s+ of a chain covered by no track): cam5 1600 704 of 5742 (12%),
FM51 0700 417 of 1524 (27%), cam4 1600 near lane 17 of 469 (4%). Frame traces (TRACE_N on
cam5): the cars are at the horizon with 10-17 px boxes, detected for 5-10 frames at conf
0.11-0.28; the first box >= det_thresh 0.35 starts a track and it holds from the next frame.
(The first split's "confident box present" majority was an artifact: the birth frame itself
fell inside the uncovered span.) Scoring on the matched boxes instead of the Kalman output
changed nothing (704 -> 703): not an output-lag effect. Mechanism = the birth bar: weak
boxes of a distant or partly hidden car cannot start a track (clip 5 is the mid-scene case).
RIGID PAIRS (trailer candidates): the side-by-side-steady-offset instrument flags 273 / 404 /
23 pairs on cam4 / cam5 / FM51 - dominated by cars following in one lane; not a usable size.
A trailer instrument needs attachment (no gap) held through speed changes.

### Phase A — weak-box births, built and measured (2026-09-12; plan approved: "Ok plan it out")

Built: `_RecoveringByteTrack` keeps leftover weak boxes (below the 0.35 birth bar) as
TENTATIVE histories linked by the tracker's position rule. INHERITANCE: the track born from
the car's first confident box takes the history; PROMOTION (TRACKER_WEAK_BIRTH_PROMOTE):
a tentative held 0.5 s and moved 0.5 box widths becomes a track. A coverage guard (share of
the weak box inside a held vehicle's box < 0.6) stops a car's double/part boxes from
becoming or feeding a twin — 0.3 first, raised to 0.6 because two equal boxes at IoU 0.2
(the ruled clip-5 queue car beside its neighbour) already cover 0.33. Pass 1 collects the
histories as BACK-FILL rows at their true frames in a sidecar (backfill.npy, saved before
every count.txt write), merges them before the stop-fracture collapse, rewrites the dump in
frame order; resume clamps to the main rows, keeps back-fill promoted before the resume
frame, floors the id counter (removing a pre-existing id-reuse hazard), and a complete dump
is no longer re-stepped on resume. Tests: test_tracker_weak_birth.py (12),
test_pass1_backfill.py (8); suite 1274 green.

Measured on re-tracks from cache (yardstick: scripts/research_tracker_break.py timeline /
timeline_all and research_tracker_classes.py), tk4 = the tracker before this phase:
  site                  late births tk4 / inherit / +promote   one track            breaks
  cam4 1600 near lane   4% / 1% / 1%                           381 / 389 / 387      255 / 248 / 253
  FM51 0700             27% / 5% / 4%                          1165 / 1152 / 1149   779 / 825 / 837
  cam5 1600             12% / 4% / 3%                          3405 / 3620 / 3590   4755 / 4417 / 4497
Back-fill rows: 18.9k / 5.4k / 22.3k; (id, frame) collisions dropped: 0.
Reading: INHERITANCE is a clear gain in late births everywhere and on cam5 one-track (+215).
On FM51 most of the break rise is bookkeeping (43 gap-then-birth breaks now show as a
hand-off to the back-filled id); the real addition is ~30 twin/neighbour hand-offs.
PROMOTION trims late births ~1 point more but costs one-track (-2 / -3 / -30) and breaks
(+5 / +12 / +80) on every site: a car promoted from weak boxes tends to lose that id when its
confident box arrives. DEFAULT: inheritance on; promotion OFF until that continuity is fixed.
Back-fill reel (Phase A film step; promotion being off, the film checks INHERITED starts):
scripts/viz_backfill_reel.py on wi2 dumps, 3 FM51 0700 + 3 cam5 1600, even spread over
tracks with >= 8 back-filled frames; page https://claude.ai/code/artifact/fb28b061-39f0-4bf2-abf6-7755558e660d
(yellow = back-filled start, cyan = the same track after its birth, grey = tracks nearby).
Pre-look: five read as the same car; FM51 clip 3 (track 2440) shows cyan on a white SUV at
the right edge a second after the birth — for the operator's ruling.

OPERATOR RULINGS (his words), "Is the yellow start the same car as the cyan track?":
  1  FM51 0700, track 11, 13 back-filled frames, born 7:01:14.1 (f252711)
     "yes it is the same"   Reading: SAME CAR - the inherited start is right.
  2  FM51 0700, track 1162, 11 back-filled frames, born 7:51:07.6 (f282646)
     "its the same vehicle"   Reading: SAME VEHICLE - a white semi coming toward the camera,
     first seen as a 12-px speck at the far end (conf 0.10-0.33); box grows smoothly 12 -> 81 px
     over 3 s with no jump. The inherited start is right.
  3  FM51 0700, track 2440, 11 back-filled frames, born 8:56:21.9 (f321789) - the pre-look's suspect
     "same vehicle"   Reading: SAME VEHICLE - the white SUV itself, first seen as a 12-px speck
     (conf 0.11-0.23); box 12 -> 25 px at the birth -> 171 px one second later, sliding steadily
     down-right, no skip; the track ends by edge exit at the right edge. The pre-look's "jump"
     was the SUV's own fast approach. The inherited start is right.
  4  cam5 1600, track 69, 14 back-filled frames, born 16:01:16.6 (f576746)
     "It is the same vehicle"   Reading: SAME VEHICLE - a far-field car in a cluster of white
     vehicles moving left beyond the white van; its back-fill = 2 full boxes (24x16), ~1 s of a
     6-8 px tall strip (the car partly hidden) beside a grey neighbour track, then 17x13 at the
     birth. Asked specifically about the strip: it is the same car. The inherited start is right.
  5  cam5 1600, track 4629, 8 back-filled frames, born 16:59:12.2 (f611502)
     "it is a theaft I think, clossly passing vehicles but it is hard to tell"
     Reading: SUSPECTED THEFT, not certain - two vehicles passing close in the far field by the
     signal pole; the id may move between them. (Dump: box 15 -> 22 px, smooth leftward drift,
     no jump; a grey track just left of it at the birth.) Evidence to settle it follows.
     Dump + raw detections (study_1600 cache): a platoon leaving the far signal along the far
     side, right to left. 4627 (white car) leaves the spot x536 y180 at f611479; 4629's weak
     boxes sit on that same spot 611494-611505 (a second car pulled up, then leaving), one raw
     chain, no crossing, grey = 4627 ahead. After the reel clip ends (+2 s): 4633 born ahead of
     cyan at +1.8 s (x440, far lane), 4634 behind; cyan catches and passes 4633 at +3.0-3.6 s,
     boxes touching, and ends on a silver car in the nearer lane (y 183 -> 200, box 22 -> 86 px).
     Clip 5b on the page (f611474-611562, every nearby id labelled in its own colour,
     screenshots/bfcam5_sprite_2long.jpg) put to the operator.
  5b "Its the same car but there is a theaft with the o car near the end of the film where it
     theafs from one car to another"
     Reading: CLIP 5 SETTLED - cyan 4629 is one car from the yellow start to the end; the
     inherited start is right. The suspected theft is ORANGE's (4627), not the back-fill's.
     Measured (dump): orange rides a DARK car along the far side; a silver car (track 4630) is
     just ahead of it. At f611531-534 (+2.9 to +3.2 s) the dark car overtakes the silver car on
     the near side and hides it; orange goes unmatched two frames (611532-533); 4630 takes the
     dark car's box (w 53 -> 67 -> 71, y 195 -> 207); orange comes back at 611534 on the silver car
     as it re-emerges (w 55 -> 43, then 43 -> 74 to the left edge). THE TWO IDS SWAP CARS at an
     overtaking occlusion - a theft-class sample for Phase B (the first filmed one since hand-off
     clips 4 and 6), the mechanism being the occluded car's id taking the occluder's merged box
     while the occluder's id is briefly unmatched, then recovered onto the re-emerging car.
  6  cam5 1600, track 9265, 20 back-filled frames, born 17:58:52.2 (f647302)
     "it looks like the same vehicle"   Reading: SAME VEHICLE - a far car moving left along the
     far side, a 6-9 px tall strip for its whole back-fill (x 518 -> 474, conf 0.12-0.35), a
     black pickup passing in front at the birth. The inherited start is right.

  TALLY (6 clips, rulings 2026-09-12/13): the inherited start is the same vehicle 6 of 6
  (clip 5 settled on the longer clip 5b; the pre-look's suspect, FM51 clip 3, was the SUV's own
  fast approach). No back-fill came from the wrong vehicle. INHERITANCE STANDS AS BUILT
  (default on). The film surfaced one theft of the kind Phase B targets: an id swap between
  two cars at an overtaking occlusion (clip 5b, tracks 4627 / 4630, cam5 16:59:15).

### Phase B — thefts, instrument built and measured (2026-09-13; plan step "instrument and film first")

Built: `_RecoveringByteTrack.match_log` (diagnostics only, None = off; one record per
association: absolute frame, id, stage s1 / s2 / s25 / unconf / confirm_pos / birth, was_lost,
frames since seen, predicted box, det box, det score); test
test_match_log_records_stages_and_changes_nothing (output identical with the log on; suite 1275
green). scripts/research_thefts.py: every dump row labelled with its yardstick chain (IoU >=
0.3); a SWITCH = one id on chain A >= 5 frames then on chain B >= 5 frames, sorted by what the
two vehicles do: THEFT (A detected >= 3 times in the 2 s after the switch AND B >= 3 times in the
2 s before: two vehicles in view), EMERGENCE (A goes on, B only appears), A ENDS (B was there, A
stops), CHAIN SEAM (neither: the yardstick split one car). The A/B overlap at the switch is
REPORTED, not excluded (the ruled clip-5b swap had overlap 0.31; hand-off clips 1 and 3 were
yardstick errors under overlap). Swap = an id that was on B before is on A after. Stage from an
in-process re-run of the dump's tracker with the match log (reproduced the dump's box for
70/71, 384/386, 713/715 switches). Logs runs/v2_week1/research_thefts_{fm51_0700,cam4_1600,
cam5_1600}.log; events thefts_<proj>_<cam>_<variant>.json. Dumps: wi2_* (the tracker as it stands).

  site (vehicles)        THEFT  EMERGENCE  A ENDS  SEAM   THEFT: overlap <=0.2/0.2-0.5/>0.5  swaps  stage onto B
  cam4 1600 (5516)        107      107        65    107          37 / 53 / 17               51    s25 66 (46 tracked, 20 lost), s1 38, s2 1
  cam5 1600 (5742)        221      155       210    129          93 / 98 / 30              113    s25 137 (71 tracked, 66 lost), s1 68, s2 14
  FM51 0700 (1524)         23       21        14     13           9 /  6 /  8                6    s25 14, s1 7, s2 2
  THEFT lost age when taken (lost ids): median 2-4 frames, almost all <= 5 f (cam5 75 of 77);
  IoU(predicted box, B's box) median 0.34-0.38; B conf median 0.28-0.36. Where: cam5 x >= 384
  (the far field, 169 of 221), cam4 spread over the frame, FM51 x 256-512 (the road).
  VALIDATION: the ruled clip-5b swap is found at the right frames - 4630 (the silver car's id)
  takes the dark car's merged box at f611532 by STAGE 1 (tracked, IoU(pred, det) 0.50, conf
  0.87) as the dark car overtakes and hides it; 4627 (the dark car's id) is lost two frames and
  comes back at f611534 by POSITION RECOVERY (lost age 3, IoU 0.25, conf 0.42) on the silver car.
Reading before the film: position recovery makes ~60% of the THEFT-class matches (s25), mostly
onto weak boxes of neighbours in the far field; about half the thefts are two-id swaps. Not yet
known how many are real: the film decides (plan: the fix is declared from the rulings and the
stage breakdown, not in advance - the emergence-guard vetoes missed twice).
THEFT REEL: scripts/viz_theft_reel.py (orange = the id, white ring = car A, cyan ring = car B,
grey = other ids labelled; 2.5 s either side; per site one clip overlap <= 0.5 and one > 0.5,
even spread, >= 1 min from the ends, B >= 15 px). Page
https://claude.ai/code/artifact/3e6ae678-9fc1-4b8f-ba4e-b494a0c406ae (clips 1-2 cam4, 3-4 cam5,
5-6 FM51). Pre-look: FM51 clip 5 is a white pickup towing a load (the yardstick sees the rig as
two vehicles - a trailer case in the theft class); FM51 clip 6 has both rings on nearly the same
shape (a split chain?); cam5 clip 4's car B ring jumps from a near box to a far one (a chain
error?).

OPERATOR RULINGS (his words), "Does the orange id stay on one vehicle, or does it move from
one vehicle to another?":
  1  cam4 1600, id 3247, switch 16:42:04.5 (f601225), overlap 0.51, stage 1, swap with 3256
     "one vehicle"   Reading: YARDSTICK ERROR - the id stays on one car in the bunched far
     field; the chains swapped, not the tracker ids.
  2  cam4 1600, id 4594, switch 17:02:08.0 (f613260), overlap 0.44, position recovery onto a
     0.15 box
     "clip teo is a series of thefts between the main vehicle and a neighboring vehicle"
     Reading: TRACKER THEFT, repeated - two cars moving left close together (4594 on the farther,
     4599 on the nearer). Dump: 4594 ~42 px at y 311; at the switch recovery puts it on a weak
     box of the nearer car (y 328), its box balloons 82 -> 136 px over both cars for 0.5 s, then
     settles at ~70 px between them; the id goes back and forth between the two cars.
  3  cam5 1600, id 4846, switch 17:01:55.8 (f613138), overlap 0.44, recovery from lost 2 f,
     swap with 4864
     "No only did it leave with the passing car, but orange comes off of a theft that happened
     before the clip began"
     Reading: TRACKER THEFT, twice on one id. (a) In the clip: 4846 sits on a car STANDING on
     the far side (x 443, 38 px, conf 0.7-0.8); car 4864 passes it moving left; 4846 drops to weak
     boxes 3 frames, then leaves with the passing car (recovery, lost 2 f) while 4864 stays on the
     standing car - the ids swap at the pass. (b) Before the clip: 4846 is born 16:59:41.8 on a
     car coming in from the lower left (74 px), which slows as it drives away to the far side
     (box 74 -> 47 px); at f613013-015 its box jumps onto the car already standing at x 446 y 192
     (35 px). So one id was on three cars in 14 s.
     INSTRUMENT BLIND SPOT found by this ruling: the yardstick holds only MOVING vehicles (chains
     >= 120 px of travel), so a standing car in a queue has no chain; the jump in (b) was filed
     CHAIN SEAM (47 unlabelled frames between the two chains). Thefts onto or off a standing car
     are under-counted - on cam5's queues that matters.
  4  cam5 1600, id 6345, switch 17:21:00.6 (f624586), overlap 0.52, stage 2 (weak box, IoU with
     the prediction 0.73), swap with 6355
     "It says on the correct vehicle the whole time"
     Reading: YARDSTICK ERROR - orange moves smoothly left along the far side (~6 px/frame,
     14 -> 40 px, no jump). Chain B (3821) had linked a near-field car driving away into the
     far-side traffic and landed on orange's car; chain A jumped to the car beside it (6355).
  5  FM51 0700, id 1195, switch 7:52:03.7 (f283207), overlap 0.22, recovery onto a 0.14 box
     (asked: one rig, a pickup towing its load, or two vehicles?)
     "I think it switches from the from the forward vehicle to the following vehicle"
     Reading: TRACKER THEFT (his reading, "I think") - orange moves from the forward vehicle to
     the one following it as they recede toward the horizon. Dump: 1195 enters at the lower
     right (70 -> 119 px) and recedes; 1197 is born behind it a second later; at the switch, boxes
     merging at ~25 px, 1195 widens 24 -> 33 px onto the follower (recovery, conf 0.14); 1198 is
     born at the far end. He described two vehicles (forward / following), not a towed load.
  6  FM51 0700, id 1986, switch 8:31:48.6 (f307056), overlap 0.59, stage 1 (tracked, IoU with
     the prediction 0.48, conf 0.48) - the pre-look's "both rings on nearly the same shape"
     "Its one vehicle towing a white box trailer"   (ruled 2026-09-15)
     Reading: YARDSTICK ERROR, TRAILER CASE - one rig; the yardstick split the tow vehicle and
     its box trailer into two chains and the id simply stayed on the rig. Not a theft; the
     first ruled trailer sample for Phase C (with hand-off clip 2).

  TALLY (6 clips, rulings 2026-09-13/15), by the stage that made the match:
     REAL THEFT   3 of 6: clips 2, 3, 5 - ALL THREE by POSITION RECOVERY (s25) onto a weak box
                  (conf 0.14-0.15 in clips 2 and 5; recovery from lost 2 f in clip 3) of a
                  NEIGHBOUR moving close beside or past the id's own car.
     YARDSTICK    3 of 6: clips 1, 4, 6 - all by the ordinary stages (s1, s2, s1); the id stayed
                  on one vehicle each time (clip 6 a rig the yardstick split in two).
  The stage breakdown and the film agree: the ordinary matches were right every time they were
  filmed; the position-recovery matches were thefts every time they were filmed. On the census
  s25 makes 66 / 137 / 14 of the THEFT-class matches (cam4 / cam5 / FM51), about 60%, and those
  are the ones to fix. The fix is declared below from this.

### Phase B — the recovery-guard census (2026-09-15, scripts/research_recovery_guard.py, wi2 dumps)

Every stage-2.5 match of an in-process run, sorted by the chains: SAME (the box is on the id's
own chain), OTHER (another chain that goes on being detected = theft), SEAM/EMERGE, NONE
(unlabelled: standing cars and far specks have no chain). Per match: overlap with boxes other
ids took this frame (held boxes), overlap with the neighbours' boxes of the previous frame,
the jump from the last observed box (widths) and its angle against the predicted motion, the
taken box's conf. Logs runs/v2_week1/recovery_guard_{cam4_1600,cam5_1600,fm51_0700}_b.log,
cross-tabs scripts/research_recovery_guard_tab.py.

  site        recoveries   SAME    OTHER   NONE    OTHER: angle>60  (SAME)     held IoU>=0.6: OTHER/SAME/NONE refused
  cam4 1600     20468     15340     417    4486    151 of 267  (1585 of 11247)      86 / 154 / 188
  cam5 1600     25257     13736     862   10008    309 of 511  (2889 of 8828)      168 / 445 / 661
  FM51 0700      6427      5289      86     996     40 of  52  ( 397 of 4447)       18 / 105 /  43
  Thefts are 1.3-3.4% of recoveries. The taken box is weak in both classes (conf median 0.22 vs
  0.26-0.36). The theft jump goes AGAINST the vehicle's motion (angle median 148 / 100 / 78 deg
  on FM51 / cam5 / cam4 vs 8 / 23 / 12 for good recoveries) but a third to a half of the thefts
  are on standing tracks with no direction to judge, and every rule tried refuses 2-7 good
  recoveries per theft on the census (angle>90 & jump>=0.3 widths: 19/71, 98/436, 38/248
  OTHER/SAME on FM51/cam5/cam4; held-box IoU>=0.6: 18/105, 168/445, 86/154). NO PER-FRAME GATE
  SEPARATES THEM CLEANLY. A refused good recovery is not a break, though - the id coasts lost one
  frame and stage 1 re-finds it on the next confident box - so the cost is measured by
  re-tracking, not by counting refusals.

### Arms rg1 / rg2 / rg3 (declared 2026-09-15 before scoring): the guards, re-tracked, on the chains

Built as knobs (backend/config.py TRACKER_RECOVERY_HELD_IOU, _REVERSE_DEG, _REVERSE_JUMP; 0 =
off, the default; tracker.py stage 2.5, `_reverse_jump_mask`; recipe key `recovery_guard` in
the dump meta + PASS1_RESUME_KEYS; 3 tests). Re-tracks from cache (scripts/arm_retrack_alias.py,
~83 s a window): rg1 = held-box guard IoU 0.6; rg2 = reverse-jump guard 90 deg / 0.15 widths;
rg3 = both. Judged against wi2 (the tracker as it stands) by research_tracker_break timeline_all
(one-track-per-vehicle, breaks, hand-off kinds) and research_thefts (THEFT / swaps). The bar: a
guard earns its place only if THEFT + swaps fall and one-track-per-vehicle does not (breaks
may not rise more than the thefts fall).
  wi2 baseline: one-track 389/469 (cam4 near lane) / 3620 of 5742 (cam5) / 1152 of 1524 (FM51);
  breaks 248 / 4417 / 825; THEFT 107 / 221 / 23; swaps 51 / 113 / 6.
  (cam4's wi2 one-track / breaks above were the NEAR-LANE yardstick; the all-vehicle figures,
  wb_wi2all_cam4.log, are 4188 of 5516 / 3046 and are what the table below compares.)

### rg1 / rg2 / rg3 verdict (recorded 2026-09-15): the held-box guard wins on every measure, every site

  all-vehicle yardstick (research_tracker_break timeline_all) and thefts (research_thefts):
  site   arm                  one-track   breaks   twin hand-offs   lost 2-5 f -> ANOTHER   THEFT   swaps
  cam4   wi2 (as it stood)     4188       3046        202                 159                107     51
  cam4   rg1 held 0.6          4241       2918        121                 142                 83     29
  cam4   rg2 reverse 90        4163       3281        205                 153                 87     37
  cam4   rg3 both              4196       3161        127                 145                 72     24
  cam5   wi2                   3620       4417        557                 432                221    113
  cam5   rg1                   3738       4057        329                 408                196     99
  cam5   rg2                   3522       4959        465                 430                202     94
  cam5   rg3                   3623       4577        279                 394                177     83
  FM51   wi2                   1152        825        139                  36                 23      6
  FM51   rg1                   1168        766         97                  37                 18      5
  FM51   rg2                   1143        874        124                  38                 20      8
  FM51   rg3                   1149        820         86                  35                 19      7
  Logs runs/v2_week1/wb_rg{1,2,3}_{cam4,cam5,fm51}.log, research_thefts_rg*_*.log.

  READING. rg1 (refuse a recovery onto a box that overlaps, IoU >= 0.6, a box another id took
  this frame) is better on every column on all three sites: thefts -24 / -25 / -5, swaps -22 /
  -14 / -1, one-track +53 / +118 / +16, breaks -128 / -360 / -59, and the TWIN hand-offs fall by
  40% - the guard also stops a recovering id from climbing onto a neighbour's double box and
  riding it as a twin, which the census had filed under SAME (the same-chain refusals it
  predicted were mostly twins, and refusing a twin's recovery is a gain, not a break). rg2 (the
  reverse-jump guard) removes a few more thefts but breaks far more tracks (+235 / +542 / +49):
  the backward jumps it refuses are mostly a slow vehicle's own box jitter, as the census's SAME
  rows at 150-180 deg already suggested. rg3 inherits rg2's breaks.
  DECISION (the tracker-engineering rule: fix the mechanism, keep the win, keep going): the
  held-box guard IS the tracker's behaviour - TRACKER_RECOVERY_HELD_IOU default 0.6. The
  reverse-jump guard stays a knob, default off, with the verdict in backend/config.py. Suite
  1278 green. Production dumps and standings untouched (the re-tracks are scratch variants rg1_*).
  WHAT IS LEFT (rg1 thefts by the stage that made the match onto B): cam4 83 = s25 43 (30 tracked,
  13 lost) + s1 37 + s2 1 + back-fill 2; cam5 196 = s25 109 (54 / 55) + s1 67 + s2 18 + 2;
  FM51 18 = s25 9 + s1 7 + s2 2. Position recovery still makes about half; the rest are
  ordinary IoU matches (the clip-3 kind: an occluder's prediction lands on the occluded car's
  box - the classic swap, which no recovery-side rule can reach). Next: a filmed sample of what
  the guard REFUSED on rg1 (the operator's ruling that the refusals are right), then the s25
  residual - its lost-age / conf / neighbour picture on rg1 - before any further rule.

### Refusal reel (2026-09-19, scripts/viz_refusal_reel.py on the rg1 dumps; tracker.py refusal_log diagnostics)

Refusals by the held-box guard (greedy pairs it would have taken without the guard, box stacked
IoU >= 0.6 on a box another id took this frame): cam4 1600 376 (215 of lost ids; the id seen
again within 1 s after 191), cam5 1600 1254 (794; 684), FM51 0700 127 (76; 66); refused-box conf
median 0.18-0.20. So after about half the refusals the id ENDS: the id had been a second id on
a vehicle another id holds (or had wandered onto it), and the refusal is where it dies.
Page https://claude.ai/artifact/HzMHofMeNUEtdu3KVHGW2y (clips 1-2 cam4, 3-4 cam5, 5-6 FM51;
ORANGE = the refused id, CYAN ring = the refused box, WHITE ring / white label = the id holding
it). The question: "Was the orange id on the vehicle under the cyan ring, or on a different
vehicle?" - a different vehicle = a theft stopped; the same vehicle = the guard let the white
id keep it and the orange id ended (a twin resolved, the survivor being whichever id had the
box by the ordinary stages).
Pre-look (close crops screenshots/rf*_look_*.jpg): 5 (FM51, 1033) is a far car 1029 lost for
two frames, 1033 born on it, 1029 re-finds it, 1033 refused and ends - the same car, the older
id survives. 6 (FM51, 1940) is a truck 1942 holds throughout; 1940 came from the lower left,
sat on the truck two frames, refused, ends. 3 (cam5, 3906) is a queue neighbour's box; 3906 is
back on its own car the next frame - no cost. 2 (cam4, 4292) looks like the same car leaving
at the left edge under a newer id 4298 (the older id refused its own car's edge strip). 1
(cam4, 2139) and 4 (cam5, 6956) need his eyes: a wandering id along the far-side row, and a
lost id under a passing SUV.

OPERATOR RULINGS (his words), "Was the orange id on the vehicle under the cyan ring, or on a
different vehicle?":
  1  cam4 1600, id 2139, refusal 16:29:56.6 (f593946), box held by 2124 (IoU 0.69), tracked
     "1 same"   Reading: SAME VEHICLE - 2139 was a second id on the standing flatbed pickup
     that 2124 holds; the guard let 2124 keep it and 2139 ended. A twin resolved, no theft.
  2  cam4 1600, id 4292, refusal 16:57:26.4 (f610444), box held by 4298 (IoU 0.76), lost 4 f
     "2 dif"   Reading: DIFFERENT VEHICLE - 4292 was on another vehicle; the guard stopped a
     lost id from taking the exiting car's edge strip, which 4298 rightly holds. A THEFT STOPPED
     (the pre-look's "same car under a newer id" was wrong).
  3  cam5 1600, id 3906, refusal 16:49:14.2 (f605522), box held by 3899 (IoU 0.61), lost 3 f
     "3 same but unsure"   Reading: SAME VEHICLE, NOT CERTAIN - in the touching far-side queue
     he reads the cyan box as 3906's own car, which 3899 also holds (two ids on one queued car).
     Either way the refusal cost nothing: 3906 was back on its own box the next frame and held
     it for the following second (10 of 10). Where it matters is the twin: if 3899 and 3906 are
     one car, the queue carries a double id the guard did not resolve (3906 kept its box by the
     ordinary stage). Filed as SAME with the uncertainty noted.
  4  cam5 1600, id 6956, refusal 17:28:53.9 (f629319), box held by 6969 (IoU 0.68), lost 5 f
     "4 is corrupted it came after a theft"   Reading: CORRUPT BEFORE THE CLIP - the orange id
     had already been stolen onto another car earlier (its path from the lower left up into the
     far-side queue is that theft); the box it was refused belongs to a car 6969 holds. Ending
     an already-corrupt id there is the right outcome; the theft itself is upstream of the guard
     (a Phase B residual, the clip-3-of-the-theft-reel kind: a lost id under a passing SUV).
  5  FM51 0700, id 1033, refusal 7:46:06.1 (f279631), box held by 1029 (IoU 0.68), tracked
     "5 same"   Reading: SAME VEHICLE - the far car 1029 lost for two frames, 1033 born on it,
     1029 re-found it, 1033 refused and ended. The older id kept the car. A twin resolved.
  6  FM51 0700, id 1940, refusal 8:29:15.5 (f305525), box held by 1942 (IoU 0.78), tracked
     "6 same"   Reading: SAME VEHICLE - the white truck 1942 held throughout; 1940 sat on it
     two frames and was refused. A twin resolved; 1942 kept the truck.

  TALLY (6 clips, rulings 2026-09-19): SAME VEHICLE 4 (1, 3 unsure, 5, 6), DIFFERENT 1 (2),
  CORRUPT BEFORE THE CLIP 1 (4). In every SAME clip another id rightly held the vehicle by the
  ordinary stages and the refused id was a second id on it: the guard ended the twin and the
  vehicle kept one track. In the DIFFERENT clip the guard stopped a theft. In no clip did the
  guard refuse a vehicle's only track its own box. THE HELD-BOX GUARD STANDS AS BUILT (default
  0.6). Two things the film adds to the residual: (a) twins in the far-side queues (clip 3:
  two ids on one queued car, neither refused because both hold boxes by the ordinary stages) -
  the double-box class, upstream of recovery; (b) clip 4's theft happened before the guard could
  matter, a lost id under an occluder - the s25 residual the ledger already names next.

### The residual after the guard (2026-09-19, rg1 dumps: research_recovery_guard.py + research_thefts.py)

  recovery census on rg1      recoveries   OTHER (was)   SAME     held>=0.6 still: OTHER/SAME
  cam4 1600                     19978      289 (417)    15231        12 / 54
  cam5 1600                     23853      658 (862)    13351        40 / 107
  FM51 0700                      6316       71  (86)     5228         3 / 31
  The theft-class recoveries fell by a third to a half; what is left has the same shape as
  before (taken-box conf ~0.22-0.25, jump ~0.28 widths, angle against the motion for ~60-75%,
  no held-box overlap): no per-frame handle. THEFT switches on rg1 by the stage that made them:
  cam4 83 = s1 37 (conf 0.63, IoU(pred,B) 0.66, 13 swaps) + s25 43 (conf 0.25, IoU 0.30, 13 lost,
  13 swaps) + s2 1; cam5 196 = s1 67 + s2 18 + s25 109 (55 lost, 53 swaps); FM51 18 = s1 7 +
  s2 2 + s25 9. Two mechanisms remain: (1) recovery onto a neighbour's WEAK box while the own
  car is momentarily undetected (half; the box barely overlaps the prediction, IoU ~0.27-0.30
  against the 0.2 gate); (2) stage-1 occlusion swaps on CONFIDENT boxes overlapping the
  prediction well (the other half). Neither separates from the good matches by geometry; the
  physical discriminator is what the car looks like, which the tracker does not have (the
  detection cache carries no pixels, so an appearance check would be a live-pass-only feature
  and cannot be judged by re-tracking from cache). THEFTS ARE PARKED HERE: the cheap part is
  taken, the rest waits for appearance.

  WHERE THE YARDSTICK'S NUMBER NOW IS: breaks. rg1 breaks 2918 / 4057 / 766 against thefts
  83 / 196 / 18. The break census (wb_rg1_*.log, "the next real box at the break"): the
  tracker's OUTPUT box at the last covered frame overlaps the vehicle's NEXT real box by
  0.18 / 0.22 / 0.20 (median) where the real box itself overlaps its own next box by
  0.30 / 0.38 / 0.28 - the tracker's state is a worse predictor of the next detection than the
  last detection is. Classes: next box weak and IoU < 0.5 with the tracker box 1341 / 1774 /
  301; next box confident but fused IoU x conf < 0.2 1064 / 1463 / 306; confident and should
  match but taken by another id 265 / 562 / 119; weak with IoU >= 0.5 (stage 2 should match)
  248 / 258 / 40. cam4's far field (x >= 550, 17-px boxes at conf 0.17) is 848 of its 2918 and
  is the detection floor. NEXT (instrument first, the plan's rule): a miss log in the tracker -
  for every unmatched track at every frame, its PREDICTED box and its LAST OBSERVED box - joined
  to the break events, to say whether the prediction or the observation would have reached the
  next real box, and by which stage. Then the fix is declared from that, not before.

## BREAKS — the miss log (2026-09-19; plan ok-plan-it-out-breezy-kernighan.md, operator: "plan it out")

Built: tracker.py `miss_log` (diagnostics only, None = off; one record per track that ends a
frame without a box after stage 2.5: absolute frame, id, was_lost, age, PREDICTED box, LAST
OBSERVED box, Kalman vx/vy, observed vx/vy, fate; lost tracks logged while age <= 10; test
test_miss_log_records_misses_and_changes_nothing, suite 1279 green); research_tracker_break.py
`label_hits` factored out (timeline_all output byte-identical on the three rg1 dumps);
scripts/research_breaks.py (the dump's tracker in process with match + miss logs, the input
after the 0.8 dedup, every break joined: id A's status at f_n x the next real box's fate);
scripts/viz_break_reel.py. Logs runs/v2_week1/research_breaks_{fm51,cam4,cam5}.log, events
breaks_<proj>_<cam>_<variant>.json.

  rg1 dump               cam4 1600   cam5 1600   FM51 0700
  breaks (yardstick)       2918        4057        766
  id A at f_n:
    MISSED (in the pool, no box)   1124   1713   376
    ID_MATCHED_ELSEWHERE           1206   2147   300     the id took a DIFFERENT box that frame
    NO_RECORD (edge-exit retired)   437     34    24
    BACKFILL_AT_K (label on a back-filled row)  145  140  63
    LABEL_ARTEFACT / NOT_IN_INPUT     6/0   22/1   3/0
  the next real box's fate: free 1533 / 1573 / 286; a NEW id born on it 687 / 805 / 184;
    another existing id took it 472 / 1265 / 157 (of which twins 81 / 273 / 76).
  In-process ids == dump ids for every mapped break (stop-fracture relabels aside). The
  window-end trap (chains keep a hit at f1) fired 0 times on these dumps.

  MISSED, by the first gate that refused the box (gate 1 = the ordinary stage, gate 2 = recovery):
    cam4: s1_fused<0.2 390, s2_iou<0.5 355, s2_ineligible(lost) 286, s1_assignment_lost 92 /
          min_iou<0.2 538, size_ratio<0.3 340, held_guard 151, recovery_unexplained 93
    cam5: s1_fused<0.2 564, s2_iou<0.5 499, s2_ineligible(lost) 437, s1_assignment_lost 197 /
          min_iou<0.2 673, held_guard 388, size_ratio<0.3 358, recovery_unexplained 292
    FM51: s1_fused<0.2 171, s2_iou<0.5 84, s2_ineligible(lost) 67, s1_assignment_lost 52 /
          min_iou<0.2 188, held_guard 84, size_ratio<0.3 82, recovery_unexplained 21
  (recovery_unexplained = the box went to a NEARER candidate in the greedy recovery: it shows
  as another id's s25 match - a theft-class event from the box's side; held_guard with
  s1_assignment_lost = the box was contested and another id won stage 1 - the same class.)

  THE HYPOTHESIS TESTED. "The tracker's state is a worse predictor than the last detection"
  is NOT what the miss log shows: at a miss the prediction and the last observation are BOTH
  far from the next box (pred error median 0.64 / 0.45 / 0.71 widths, last-obs error 0.99 /
  0.69 / 0.79; the observation is closer in only a third to a half of the misses). What it
  shows instead, on the misses one frame after the last sighting (gap == 1, the clean case):
    cam4  658 misses: the car moved 1.22 widths/frame, the Kalman velocity said 0.67
    cam5 1037 misses: the car moved 0.55 widths/frame, the Kalman velocity said 0.31
    FM51  256 misses: the car moved 0.68 widths/frame, the Kalman velocity said 0.21
  and on FM51's confident-box misses, split by track life: Kalman / actual speed 0.70 at life
  <= 3 frames, 0.49 at 4-10, 0.21 at 11-30, 0.22 beyond 30 - the tracks are NOT young; the
  filter's velocity settles at a fifth of the vehicle's pixel speed on vehicles whose pixel
  speed keeps growing (approaching the camera: FM51's w 120 px at x 555). The last two
  observations give 0.64-0.69 of the actual speed. The next box lies along the Kalman heading
  in 80% of the cases: the DIRECTION is right, the MAGNITUDE lags. supervision's Kalman uses
  std_weight_velocity = 1/160 of the box height per frame (tuned for 30-fps pedestrians): at
  10 fps a car whose pixel speed doubles every second cannot be followed. THIS is the
  measured mechanism behind the "s1_fused<0.2 / min_iou<0.2" class (cam4 176, cam5 164,
  FM51 95 confident boxes, 31-48 px) and part of the weak-box classes.

  The other large classes, sized:
    - the far-field detection floor: s2_ineligible(lost)/min_iou (227 / 310 / 60, w 13-16 px,
      conf 0.13-0.14) and size_ratio<0.3 (340 / 358 / 82, w 7-19 px: the box on a distant car
      changes width by > 3x between frames). cam4's x >= 550 band holds 326 of its 1124
      misses. Instrument-limited, as ruled.
    - contested boxes (s1_assignment_lost + held_guard, recovery_unexplained): 91+47 / 195+119
      +292 / 52+27+21 - the theft class from the box's side. Parked with the thefts.
    - ID_MATCHED_ELSEWHERE (1206 / 2147 / 300): the id took a box 0.72 / - / 0.31 widths from
      the chain's next box (median). Within half a width in 424 / - / 179 of them with a NEW id
      born on the chain's box in 181 / - / 51: the DOUBLE-BOX TWIN class (two detector boxes on
      one car; the id keeps one, a newborn takes the other). Beyond half a width: the id on a
      neighbour (theft class) or the chain linker's own jump.
    - NO_RECORD = edge exit (437 on cam4): the chain's remaining hits after the break: median 2,
      travel 0 px, the box touching the left (247) or right (184) edge - the vehicle was
      leaving; 67 chains had >= 10 hits left, 5 travelled >= 100 px. A yardstick tail, not a
      tracker fault, except those few.

  BREAK REEL (scripts/viz_break_reel.py, gate min_iou<0.2, 2 per site), page
  https://claude.ai/artifact/2TzX7VKWYafDJuj9v3ZLki (clips 1-2 cam4, 3-4 cam5, 5-6 FM51;
  ORANGE = the id, CYAN ring = the missed box, MAGENTA dashes = the prediction, YELLOW dashes =
  the last observed box, WHITE = the id the vehicle got next). The question: "Is the vehicle
  under the cyan ring the same vehicle the orange id was on?" Pre-look: 5 (FM51, 717) is the
  mechanism on film - a dark SUV approaching fast, the prediction barely moves from the last
  box while the car moves half a width; 6 (FM51, 1568) the same truck already under a new id;
  2 (cam4, 5938) a car passing behind a box truck, the prediction 1.5 widths behind; 3 (cam5,
  3624) a lost id whose prediction ballooned 3 widths away; 1 (cam4) and 4 (cam5) bunched far
  field, his eyes needed.

OPERATOR RULINGS (his words, 2026-09-19), "Is the vehicle under the cyan ring the same vehicle
the orange id was on?": "1 same, 2 different, 3 same, 4 different, 5 same, 6 same"
  1  cam4 1600, id 3254, miss 16:42:04.4 (f601224), lost 4 f, conf 0.26, IoU pred 0.09 / obs 0.06
     SAME VEHICLE - a real break in the bunched far-side row; the car got a new id (3257).
  2  cam4 1600, id 5938, miss 17:20:19.7 (f624177), lost 2 f, conf 0.54, IoU 0.00 / 0.00
     DIFFERENT VEHICLE - the car emerging at the box truck's left is not the orange id's car;
     the yardstick's chain jumped through the occlusion. Not a tracker break.
  3  cam5 1600, id 3624, miss 16:46:30.3 (f603883), lost 4 f, conf 0.38, IoU 0.00 / 0.16
     SAME VEHICLE - a real break; the prediction had ballooned three widths away; the car got
     a new id (3642).
  4  cam5 1600, id 6461, miss 17:21:54.4 (f625124), lost 3 f, conf 0.49, IoU 0.00 / 0.14
     DIFFERENT VEHICLE - the chain jumped to a neighbour by the far signal; the orange id was
     re-found on its own car a frame later. Not a tracker break.
  5  FM51 0700, id 717, miss 7:33:48.8 (f272258), tracked, conf 0.91, IoU 0.11 / 0.19
     SAME VEHICLE - the mechanism on film: the SUV approaching fast moved half a width in one
     frame; the prediction barely moved from the last box; the car left the frame without an id.
  6  FM51 0700, id 1568, miss 8:10:35.8 (f294328), lost 5 f, conf 0.12, IoU 0.03 / 0.13
     SAME VEHICLE - the truck already under its new id 1569; a real fragment.
  TALLY: 4 of 6 real breaks (the tracker lost a car it should have kept), 2 of 6 the yardstick
  chain jumping between vehicles (an occlusion, a far-field neighbour). The min_iou<0.2 class
  is mostly real; a third of it may be chain error - read its counts with that discount.

### The fix declared (2026-09-19): the filter's velocity must follow the vehicle

From the measurement, not designed in advance: the misses of the largest confident-box class
are vehicles whose pixel speed the Kalman filter under-estimates by 2-5x (its velocity process
noise, std_weight_velocity = h/160 per frame, is the 30-fps pedestrian default). Candidate:
raise the velocity process noise so the filter follows a changing pixel speed, as a knob
(TRACKER_KF_VEL_STD, the fraction of box height per frame; 1/160 = the library), re-tracked
on the three sites and judged on the chains: one-track up, breaks down, thefts NOT up (a
looser filter predicts further and can overlap a neighbour). Arms vl1 = 1/80, vl2 = 1/40,
vl3 = 1/20 on FM51 first (the cleanest site for the mechanism), the best on cam4 / cam5.

### Arms vl1-vl3 on FM51 (recorded 2026-09-19): every measure improves with the weight

Built: config.TRACKER_KF_VEL_STD (env; default 1/160 = the library), fork kwarg kf_vel_std
set on both filters the library uses (the per-tracker one for initiate / update and the
class-shared one for multi_predict); recipe key kf_vel_std in the dump meta and
PASS1_RESUME_KEYS; research_breaks.recipe_check extended; test
test_kf_velocity_noise_follows_an_accelerating_vehicle (an 18%-a-frame accelerating chain
breaks at 1/160 and holds one id at 1/20); suite 1280 green.

  FM51 0700          weight    one-track   breaks   new id born   twins   THEFT   swaps
  rg1 (as it stands)  1/160      1168        766       152         97      18       5
  vl1                 1/80       1200        711       140         90      16       6
  vl2                 1/40       1234        655       134         90      13       3
  vl3                 1/20       1249        624       127         82      13       3
  Monotonic on every column; the curve has not turned at 8x the library. Thefts FALL (a
  prediction that keeps up with its own car overlaps the neighbour's box less, not more).
  Next: vl4 = 1/10 and vl5 = 1/5 on FM51 to find the knee; vl2 and vl3 on cam4 / cam5.

### Arms vl1-vl5 verdict (recorded 2026-09-19): 1/20 is the tracker's velocity noise

  site   weight        one-track   breaks   new id born   twins   lost 2-5 f -> ANOTHER   THEFT   swaps
  FM51   1/160 (rg1)    1168        766        152          97          37                18       5
  FM51   1/80  (vl1)    1200        711        140          90          34                16       6
  FM51   1/40  (vl2)    1234        655        134          90          34                13       3
  FM51   1/20  (vl3)    1249        624        127          82          31                13       3
  FM51   1/10  (vl4)    1254        614        122          81           -                12       2
  FM51   1/5   (vl5)    1257        599        122          75           -                12       2
  cam4   1/160 (rg1)    4241       2918        738         121         142                83      29
  cam4   1/40  (vl2)    4428       2539        626          93         107                71      31
  cam4   1/20  (vl3)    4422       2547        635          96         101                73      32
  cam5   1/160 (rg1)    3738       4057        878         329         408               196      99
  cam5   1/40  (vl2)    3938       3659        806         288         325               162      85
  cam5   1/20  (vl3)    3952       3637        795         293         324               149      78
  Logs runs/v2_week1/wb_vl*_*.log, research_thefts_vl*_*.log, arm_vl*_*.log.

  READING. The filter's velocity noise was the mechanism: raising it improves every column
  on every site, and thefts fall with it (the prediction that keeps up with its own car
  overlaps the neighbour's box less). The knee is 1/40 on cam4 (1/20 flat) and 1/20 on cam5
  and FM51 (FM51 still creeps at 1/10 and 1/5, cam4 does not). Across the three sites 1/20
  beats 1/40 on every sum: one-track 9623 vs 9600, breaks 6808 vs 6853, thefts 235 vs 246.
  DECISION (the tracker-engineering rule): TRACKER_KF_VEL_STD default 1/20. Against the
  tracker as it stood this morning: one-track +181 / +214 / +81 (4.3% / 5.7% / 6.9%), breaks
  -371 / -420 / -142 (-13% / -10% / -19%), thefts -10 / -47 / -5. Production dumps and
  standings untouched (the vl* dumps are scratch variants). The next basis for any tracker
  work is vl3_* (the tracker as it now stands).
  WHAT IS LEFT of the breaks, by the miss-log classes: the far-field detection floor (weak
  7-19 px boxes: min_iou / size_ratio on lost ids), the contested boxes (thefts, parked), the
  double-box twins (a newborn on the second detector box of one car: 181 / - / 51 within half a
  width of the id's own box), and the yardstick's own tails (edge exits, chain jumps: 2 of 6
  filmed misses). Next candidate by size with a mechanism: the double-box twins (measure
  first on the vl3 dumps with research_breaks.py + research_dup_boxes.py).

## TWINS — two ids on one vehicle (2026-09-19, operator: "lets do that"; scripts/research_twins.py on the vl3 dumps)

Every chain hit labelled with ALL dump ids overlapping it >= 0.3; a twin span = two ids on
one chain >= 5 consecutive hits; the younger id (first non-back-filled row) is the newborn,
the older the holder. Logs runs/v2_week1/research_twins_{fm51,cam4,cam5}.log, events
twins_<proj>_<cam>_<variant>.json.

  vl3 dump                cam4 1600   cam5 1600   FM51 0700
  twin spans (vehicles)   278 (153)   415 (273)    54 (46)
  holder ON the vehicle at the birth   275   399   54   (lost 3 / 16 / 0: the stacked-box
                                                          birth guard is not being bypassed
                                                          by a lost holder)
  geometry at the birth:
    NESTED  (one box >= 0.9 inside the other)      46   103   42
    STACKED (IoU 0.3-0.6, below the 0.6 guard)     35    59    3
    TOUCHING (IoU 0.1-0.3)                         75    66    2
    BESIDE  (IoU < 0.1; offset ~1.5 holder widths, newborn width 0.7 of the holder) 122  187  7
  twin life: median 6-8 frames; >= 20 frames 35 / 48 / 0 (those newborns live 415 / 227 frames:
    standing vehicles in queues carrying two ids); >= 50 frames 17 / 17 / 0
  survivor: the OLDER id 168 / 224 / 24, the NEWBORN 110 / 191 / 30 - in 40-55% the newborn
    takes the vehicle and the holder dies: a twin is also a BREAK
  newborn born by weak-box inheritance (back-filled start): 132 / 207 / 33 (half)
  pass-2 twin dedup (turn_merge.twin_track_dedup: common span >= 0.6 of the shorter life,
    IoU >= 0.2) can reach 20 / 42 / 12 of them: the common span is a tenth to a third of the
    shorter life (the newborn usually goes on alone), so the rest count twice if both cross
    the gates.

  READING before the film. Two different things share the name. NESTED twins are the
  detector's double box (a partial box inside the whole-vehicle box, or the reverse): born
  under the stacked-box birth guard because the guard tests IoU > 0.6 and a small box inside
  a big one has low IoU with high coverage; the weak-birth stage already uses coverage 0.6
  (max_cover) for exactly this reason, the ordinary birth does not. BESIDE twins are born one
  to two widths away and only later share the chain: the neighbour in a queue, the trailer
  behind a pickup (FM51 clip 5 - the Phase C case), or a ghost box at an occlusion edge that
  wanders onto the next car. The film sorts them.

  TWIN REEL (scripts/viz_twin_reel.py, one nested + one beside per site), page
  https://claude.ai/artifact/MwSBH41y4kPEe3bqQGu2NF (clips 1-2 cam4, 3-4 cam5, 5-6 FM51;
  ORANGE = the newborn, WHITE = the holder, CYAN ring = the chain's box at the birth). The
  question: "Is the orange newborn on the same vehicle as the white id, or on a different
  vehicle?" Pre-look: 2 (cam4 nested, 2440) a weak box born around a standing car as a school
  bus clears it, then drifting onto the next car; 4 (cam5 nested, 5657) a small box inside a
  queued car for 7.5 s; 6 (FM51 nested, 1381) a second box on the front of a pickup-and-
  trailer rig; 1 (cam4 beside, 2346) the next car in a standing row - different; 5 (FM51
  beside, 1380) born on the TRAILER behind the pickup, then taking the whole rig; 3 (cam5
  beside, 5096) the queue under a passing SUV, his eyes needed.

## ARM vl3-fleet (DECLARED 2026-09-20, BEFORE SCORING): what is the tracker worth on the deliverable?

Operator, 2026-09-20, pulling back from the reels: "I want to know if this is productive or a
best use of resources." The honest answer was that eight days of tracker engineering has been
judged only on proxies (one-track-per-vehicle, breaks, thefts) and never against the fleet.
ONE tracker change was ever fleet-scored: position recovery (d18b, 2026-09-12), 77.97 ->
80.36, +2.39, PASS on the letter. Everything since — confirmation by position, the motion
reset, edge exit, the double-box dedup, the stacked-box guard, weak-box births by
inheritance, THE HELD-BOX GUARD (2026-09-15) and THE KALMAN VELOCITY 1/20 (2026-09-19) — is
unpriced against the deliverable.

THE ARM. The tracker exactly as it now stands (no env overrides; the vl3 recipe, verified
equal to the live config on the three dumps that already existed), re-tracked from the
detection cache into vl3_* variants on the six ByteTrack windows (cam4 x3, cam5 x3), pass 2
under the shipped default, scored against the live standings. Cameras 1-3 are BoT-SORT
recipes, untouched by this tracker, and carry their fixed scores into the fleet mean. FM 51
(0acb12c0 cam 2, vl3_l1_study_0700 / _1600) is the held-out blank-site witness. apply=False
throughout; production dumps and standings are NOT touched.

THE BAR, declared now. The G-DEF-1 letter against the production 77.97 (fleet mean rises; no
camera -1.0; no window -3.0) is the SHIP test. But the honest test of the last eight days is
d18b's 80.36: position recovery alone reached it, so the six components added since must
clear it to have been worth anything on the deliverable. Three outcomes and what each means:
  > 80.36 and the letter passes  -> the tracker becomes the production basis (operator's
      ruling; every standing resets). Tracker engineering has been productive.
  77.97 < x <= 80.36             -> the proxies gained, the deliverable did not. The six
      components after position recovery are worth ~0 in TMC terms; stop tracker work and
      go back to the counting rules / gates.
  <= 77.97                       -> the tracker work is NEGATIVE on the deliverable. Hold,
      diagnose which window fell and why, before anything else.
CARRIED IN, so a rising number is not over-read: d18b's gain was the OVERCOUNTS falling
(SB_thru, the SB_right / NB_left phantoms) as fragments became single tracks; the northbound
SHORTFALL was not recovered and is capped by COUNTING (pass 2 drops a long track whose exit
crossing was observed but whose destination softmax fails on tail motion — G-EX-2, not
built). If this arm gains the same way, the verdict says so plainly rather than letting the
fleet number imply the shortfall is solved.
Logs: runs/v2_week1/arm_vl3fleet_*.log (the re-tracks), fleet_vl3.log, fm51_vl3.log; scores
runs/v2_week1/score_vl3_*.json.

## ARM vl3-fleet VERDICT (recorded 2026-09-20): the tracker is worth a lot on the BLANK SITE
## and is being converted into LOSSES on cam4 by a counting rule that was never built

  window        live    d18b     vl3   vs live   vs d18b     cov
  cam4 0700     73.3    80.9    71.1     -2.2      -9.8     0.789
  cam4 1100     78.7    80.9    78.7     +0.0      -2.2     0.819
  cam4 1600     70.2    71.7    69.8     -0.4      -1.9     0.685
  cam5 0700     79.0    79.8    78.0     -1.0      -1.8     0.579
  cam5 1100     73.3    79.0    83.0     +9.7      +4.0     0.640
  cam5 1600     71.8    82.7    82.7    +10.9      +0.0     0.677
  camera means: cam4 74.07 -> 73.20 (-0.87);  cam5 74.70 -> 81.23 (+6.53)
  six-window mean 74.38 -> 77.22 (+2.83)   [d18b was 79.17, +4.78]
  FLEET of 12 (cams 1-3 unchanged at 85.1 95.3 75.2 76.7 68.5 88.5, mean 81.55):
      77.97 -> 79.38 (+1.42)               [d18b was 80.36, +2.39]
  LETTER vs 77.97: fleet rises PASS; no camera -1.0 (cam4 -0.87, margin 0.13) PASS;
      no window -3.0 (worst cam4 0700 -2.2) PASS.  -> the arm PASSES the ship letter.
  THE DECLARED HONEST TEST (must clear d18b's 80.36): 79.38, FAIL by 0.97. The six
      components added after position recovery are NEGATIVE on the corridor.

  FM 51, THE HELD-OUT BLANK SITE (the prime directive's deliverable):
      window      b7      d18b     vl3        approach: b7    d18b    vl3
      0700       81.6     80.4    85.7                  54.2    62.5   73.9
      1600       80.0     80.4    89.8                  50.0    66.7   79.2
  The best FM 51 numbers on record, by a wide margin: +5.3 / +9.4 movement and
  +11.4 / +12.5 approach over d18b, on a site whose answers were never used to tune
  anything. Logs runs/v2_week1/fm51_vl3.log.

  WHY THE CORRIDOR AND THE BLANK SITE DISAGREE — measured, not guessed. The movement cells
  on the two extreme windows (Miovision | live | d18b | vl3, error against Miovision):
    cam4 0700  NB_thru   2713 | 2462 | 2412 | 2353     -251  ->  -301  ->  -360
               SB_thru   1957 | 2040 | 2033 | 2069      +83  ->   +76  ->  +112
               SB_right    22 |   46 |   31 |   46      +24  ->    +9  ->   +24
    cam5 1100  SB_thru   1496 | 1654 | 1550 | 1520     +158  ->   +54  ->   +24
               NB_left    185 |  352 |  312 |  341     +167  ->  +127  ->  +156
  cam5's gain is the SB_thru OVERCOUNT collapsing toward Miovision as fragments become one
  track. cam4's loss is the NB_thru SHORTFALL DEEPENING — the better the tracking, the FEWER
  northbound throughs get counted. That is not a tracking failure. It is the mechanism this
  ledger predicted on 2026-09-12 and again in the d18b verdict: pass 2 refuses a long track
  whose exit crossing WAS observed but whose destination softmax fails on tail motion
  (G-EX-2, the observed-exit binding, DECLARED AND NEVER BUILT), while the fragments that
  the straight-fragment rule used to complete into throughs no longer exist. The counting
  default was tuned on a fragmenting tracker; on cam4's northbound approach the two errors
  were cancelling, and a better tracker breaks the cancellation. CLAUDE.md already carries
  this for cam4 1600 (the ~366 duplicate NB throughs against an equal far-field deficit).

  DECISION (operator's, 2026-09-20, after "is this productive"): the answer is YES on the
  deliverable and NO on the corridor, for a reason that is now named and located.
  - The tracker is NOT the bottleneck any more. Do not ship it as the production basis yet:
    shipping now banks cam5's +6.5 and eats cam4's -0.87 while the counting rule that would
    convert the rest is missing.
  - The next work is G-EX-2 in PASS 2 (bind a journey whose exit crossing was observed even
    when the destination softmax fails on tail motion), then re-run THIS ARM. That is the
    change that turns longer tracks into counted northbound throughs.
  - STOP tracker engineering (twins, trailers, the far-field floor) until that is done. The
    twin reel (https://claude.ai/artifact/MwSBH41y4kPEe3bqQGu2NF) stays unruled.
  - Reels: the method stands but the width was wrong. Film only when a ruling changes what
    gets built next, 2 clips not 6 when the purpose is checking the instrument. The
    yardstick's own error rate is now measured at about a third (3 of 6 on the theft reel,
    2 of 6 on the break reel) and can be carried as a discount instead of re-measured.

Phase C instrument drafted (scripts/research_trailers.py, the plan's attached-pair test). First
run FM51 0700: 44 nose-to-tail pairs >= 1 s, 24 steady, 24 steady through a speed change - the
speed change is in PIXELS and perspective alone gives 2.75x on FM51's approach, so the test does
not separate rigs from followers yet; speed must be measured in box widths per frame. Not run
further until that is fixed.

## THE ERROR BUDGET AND THE PROBLEM LIST (2026-09-20, operator: "in a triage, what do we work on")

Built from the 5/95 rule rows themselves, with the worst-list cap lifted (the saved score
JSONs keep only 8 failing rows a window, which biased the first cut). cams 1-3 scored from
the SHIPPED d17 DBs (= production, 2026-09-12); cam4 / cam5 from the vl3 arm (NOT shipped);
FM 51 from the vl3 blank-site arm. The rule: per cell per 15-min bin, |ours-ref| <= 5 when
the reference is <= 100 a bin, else <= 5% (backend/services/rule595.py).

  group                      cell-bins   failing        approach bins   failing
  cams 1-3 (BoT-SORT, prod)       830    140 (16.9%)              325    91 (28.0%)
  cam4 + cam5 (vl3 arm)           464     99 (21.3%)              168    90 (53.6%)
  FLEET OF 12                    1294    239 (18.5%)              493   181 (36.7%)
  FM 51 (blank site, vl3)          98     12 (12.2%)               47    11 (23.4%)

  failing cell-bins across the fleet of 12, by cell:
    NB thru   71  |  EB right  45  |  NB left  41  |  SB thru  32  |  SB right  19
    WB right  11  |  EB left    8  |  EB thru   7  |  NB right  3  |  WB thru   2
  by movement type: THROUGHS 112, RIGHT TURNS 78, LEFTS 49.

THE PROBLEM LIST, ranked by the fleet points a perfect fix would return (upper bounds; the
cam4 / cam5 rows are measured against the vl3 arm, the rest against production):

  #  problem                          failing bins   direction        prize
  1  cam4 northbound through          24 of 24       under (-721 veh)  +4.16
  2  cam2 RIGHT TURNS (EB/SB/WB)      42 of ~84      over              +3.33
  3  cam5 northbound left             24 of 24       over (+54%)       +1.88
  4  cam5 eastbound right             22 of 24       under (-58%)      +1.72
  5  cam4 southbound through          10             over              +1.72
  6  cam4 southbound right             5             over              +0.81
  7  cam3 northbound through          29 of 42       both ways         +0.68
  Right turns as ONE theme (2 + 4 + 6, and cam5 SB right): ~64 bins, ~+5.9 fleet - the
  largest single mechanism in the budget if it IS one mechanism.

WHAT THE TWO GAPS TURNED INTO (they were gaps only because they were unsized):

GAP A - half the fleet had never been examined. cams 1-3 are 6 of the 12 windows, run
BoT-SORT recipes, and were untouched by all the tracker work. Budgeted now: 140 failing
bins, MORE than cam4+cam5's 99. Two new problems fall out.
  * cam2 (corridor) is the weakest camera in the fleet: movement 75.2 / 76.7 / 68.5,
    approach 50.0 / 59.4 / 50.0. Its 84 failures spread over 8 cells - no single mechanism -
    but HALF of them are RIGHT TURNS (EB right 21, SB right 11, WB right 10), all over.
    That is problem 2 and the second-biggest prize in the fleet.
  * cam3 0600 northbound through fails 29 of its 42 bins - the single largest cell-window
    failure anywhere, bigger than cam4's 24. But its WINDOW TOTAL is 13917 against
    Miovision's 13756, +1.2%, well inside the 5% bar. The count is right and the BINS are
    wrong: 23 bins over, 6 under. This is per-bin dispersion, a different failure class from
    everything else on the list.
  * A DEAD END, closed cheaply: a constant timestamp offset does NOT explain it. Scored at
    lags -5..+5 minutes, lag 0 is already optimal on cam3 (75.4% vs 73.4 at -1, 73.4 at +1)
    and on cam2 1600 (32.6% vs 30.6 / 27.7). Do not re-run this. What remains is VARIABLE
    delay (our gate line vs Miovision's reference point, the gap growing with queue length)
    or genuine per-bin misclassification that averages out over the window. Distinguishing
    them needs the per-bin residual against queue state, not another lag sweep.

GAP B - the approach bar is the customer metric and is twice as bad as the movement one.
  Fleet of 12: 181 of 493 approach bins fail (36.7%) against 18.5% on movement. cam4 sits
  at EXACTLY 41.7% on all three windows (10/24 each time - an identical number three times
  is structural, not noise); cam2 corridor 50.0 / 59.4 / 50.0; cam5 43.8 / 56.2 / 50.0;
  cam1 90.3 / 86.7 and cam3 76.8 are the healthy ones. By leg across the fleet the approach
  failures are NB 83, SB 44, EB 44, WB 21. Nothing in the ledger has ever targeted the
  approach bar directly - every arm has been judged on the movement score.

READING. The list is NOT one global bug. The same cell fails in OPPOSITE directions on
different cameras (northbound through is under on cam4 and over on cam3; eastbound right is
under on cam5 and over on cam2), which points at per-site geometry, channels and gates
rather than one algorithm. The exceptions are problem 1, which has a named unbuilt fix
(G-EX-2, the observed-exit binding), and problem 7, which is a distinct dispersion class.
The tracker is not on this list; FM 51 is the healthiest site in the budget.
