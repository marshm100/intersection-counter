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

## STAGE 0 — THE SHELF INVENTORY (2026-09-20, reading only, no compute)

The question stage 0 asks: of the eight problems, which already have a diagnosed and
validated fix sitting on the shelf, which are diagnosed with no fix, and which are
undiagnosed. Sources read: backend/config.py end to end (every off-by-default counting
mechanism), the counting/attribution plan docs (NOT the tracker ones), the diagnostic
scripts, and the live per-camera knob values in the two project DBs.

### TWO CORRECTIONS TO THE SHELF AS IT WAS DESCRIBED

**(1) The origin-evidence gate and the partial-evidence posterior are NOT shelved. They
are the default on every window that has coverage.** ORIGIN_EVIDENCE_GATE_ENABLED and
ORIGIN_POSTERIOR_ENABLED both read False in config.py, and that reads like two shelved
mechanisms. They are not the live path. EVIDENCE_ACTIVATION_ENABLED is default ON and
EVIDENCE_ACTIVATION_COVERAGE is 0.20 since G-BAR-1, and two_pass.py:1619-1642 replays
every window in PROBE mode, measures the window's own origin-evidenced coverage, and
re-replays with evidence_mode="on" when it clears the bar. pipeline.py:214-222: an
explicit evidence_mode="on" sets BOTH _evidence_mode and _posterior_on to True and
never consults the two config flags. Coverage on the vl3 arm was 0.579-0.819 on all six
corridor windows and FM 51 sits at 0.24-0.30, so the gate + posterior pair is live
everywhere today. The two flags are only the non-activation path (env overrides for
experiments). Anything built on the assumption that the posterior is off is built wrong.
  Consequence for the 2026-07-15 stage-6 disposition ("blanket five-camera default FAILS;
  cam2 80% evidenced wins, cam1/4/5 36-60% lose"): that failure was SOLVED, by the
  activation precondition, and the solution was a per-window measurement taken from the
  site's own data. It is the precedent that matters for the per-camera ruling below.

**(2) The July shared-exit root cause does NOT map onto problem 2 as stated.** The claim
was that cam2's SB-thru/EB-right shared-exit confusion (config.py L797-853, root-caused
2026-07-02) IS problem 2. docs/plan_cam2_rights_2026-09-08.md measured the opposite in
September: of 1,009 EB_right events in cam2's evening window the ground-anchored gate
evidence witnesses 880 entering over the W gate and THREE over N. A SB->EB origin rewrite
would show as N-entries booked EB. It is not happening at the scale of the +505. That doc
carries five hypotheses, four ruled dead by the operator (misattributed origin, duplicates,
shape mismatch, reversal-shaped tracks), one real and small (stationary/jitter exit, 15-18%
of the excess - and the journey state machine that addresses it has since shipped
default-ON). It also carries an unbiased 5-of-5 sample from the 08:30 bin in which every
event is a genuine vehicle and four are clean counted right turns, i.e. evidence that the
REFERENCE is undercounting that bin. Problem 2 is the most-investigated problem on the list
and the least fixable by anything on the shelf.

### THE EIGHT PROBLEMS, BUCKETED

  #  problem                  bucket  what is actually on the shelf
  1  cam4 NB through          (b+)    Diagnosed to the line and the fix DECLARED but never
                                      built: G-EX-2, bind a journey whose exit crossing was
                                      OBSERVED even when the destination softmax fails on
                                      tail motion. Measured twice (2026-09-12 d18: 537 long
                                      NB tracks with no event, 316 tagged "-->N exit_only"
                                      at a median 26 px/frame, not creep; again in the vl3
                                      verdict). The "box sides ARE the gates" ruling covers
                                      the case and finalize has no branch for it. Highest
                                      prize (+4.16) and the only problem whose fix is named,
                                      specified and unwritten.
  2  cam2 right turns         (b-)    Diagnosed hardest, fixed least. Four of five
                                      hypotheses dead by operator ruling; the fifth shipped.
                                      The July shared-exit fix does not apply (above). A
                                      labelled sample points at the reference. The shelf has
                                      nothing for this; the next honest step is more
                                      labelled sample, not more mechanism.
  3  cam5 NB left             (a)     TWO candidates. (i) SPEED_TIEBREAK, shelved, validated
                                      net-positive on cam5 (NB 9.0->5.3, 2027 fires) and
                                      cam2 (EB 33.2->28.8, SB 12.3->10.8), inert on cam1/cam3,
                                      REGRESSED cam4 (NB 4.9->5.8). (ii) "Far-field
                                      stub-claim discipline", named as a NEW mechanism in
                                      plan_cam5_eb_bankhole_2026-07-27 with NB-left phantom
                                      +646 as its target and a hard constraint attached (the
                                      same stub population correctly carries NB-thru, so the
                                      discriminator must be segment coverage past the
                                      divergence, never entry evidence, never stub-ness).
                                      Never built. The 2026-09-11 reel ruled 4 of 5 sampled
                                      NB_lefts REAL and put the phantom rate near 1 in 5,
                                      concentrated in the 116 no-crossing far-field tracks.
  4  cam5 EB right            (b)     Diagnosed 2026-07-27 and CLASSIFIED: "EB-right journey
                                      formation -207: 13/21 real-geometry tracks per window;
                                      the near-field turn rarely survives tracking.
                                      Capability class (birth/association at the turn)."
                                      That is a TRACKER problem, written before position
                                      recovery, weak-box births, the held-box guard and the
                                      Kalman velocity existed. It has never been re-measured
                                      on the current tracker. Bank-hole path-fill is retired
                                      THREE times at this camera and must not be retried.
  5  cam4 SB through          (c)     Undiagnosed as its own cell. Over by +112 on vl3 0700
                                      (was +83 live), i.e. it got worse under the better
                                      tracker, same direction as problems 1 and 6.
  6  cam4 SB right            (a*)    Diagnosed and THE FIX ALREADY SHIPPED
                                      (STRAIGHT_FRAGMENT_INCLUDE_PATH_FITS, default ON since
                                      2026-09-11: 115/125/329 -> 48/24/117 against Mio
                                      22/16/39). What remains is a residual of the same class
                                      that the better tracker RE-INFLATED (0700: d18b 31 ->
                                      vl3 46). Ties to problem 1: both are cam4 far-field
                                      N-entries, one dropped and one sent into the driveway.
  7  cam3 NB through          (b)     Diagnosed as a distinct class (per-bin dispersion; the
                                      window total is +1.2%, inside the bar). Constant-lag
                                      explanation measured and closed. No fix anywhere.
  8  the approach bar         (c)     Never targeted by any arm in the ledger. Determined by
                                      ORIGIN assignment alone, so the stage-1 fate ledger's
                                      origin fields attribute it directly.

  bucket (a) shelved validated fix: 3, and 6 already harvested.
  bucket (b) diagnosed, no fix:    1 (fix declared, unbuilt), 2, 4, 7.
  bucket (c) undiagnosed:          5, 8.

### THE SPEED TIEBREAK, READ IN THE CODE RATHER THAN THE COMMENT

Three facts that change how the open ruling should be decided:

1. **It is inert today for a reason that is one command away.** expected_speed is NULL on
   every path of every camera in both project DBs (corridor 33 paths, FM 51 9 paths).
   build_bank_gtfree.py:673-686 already computes it, blind, from each path's own claimed
   supporting tracks - no ground truth, no reference. scripts/backfill_expected_speed.py
   exists to write it onto existing banks. So "inert until build_bank supplies
   expected_speed" is no longer a blocker; it is a backfill.
2. **The self-limiting guard the ruling would need ALREADY EXISTS in the code.**
   trajectory_classifier.py:881-882 skips any rival whose signature differs from the top
   path's by less than SPEED_TIEBREAK_MIN_SEP (1.5 px/step) - i.e. the mechanism already
   refuses to fire where the two collinear paths' speeds do not separate, which is exactly
   the stated reason cam4 regressed. cam4 nonetheless fired 1,487 times at that constant, so
   1.5 px/step was too loose there, not absent. Whether a single GLOBAL constant fitted from
   the banks' own measured separations makes cam4 inert while cam2 and cam5 keep firing is
   unmeasured, cheap, and needs no per-camera knob at all.
3. **The per-camera surface is only cam4.** The tiebreak is mdh-only, so cam3 (pinned
   dtw_mean) can never fire it; cam1 has no qualifying cluster. cam2 and cam5 are the
   validated positives. The entire per-camera argument rests on one camera.

### WHAT THE PRODUCTION BASIS ACTUALLY DOES ABOUT PER-CAMERA CONFIGURATION

Measured, not recalled - cameras table, project 97a7849a:

  cam1  pass1_backend botsort+reid
  cam2  pass1_backend botsort, pre_track_nms_iou 0.85, tracker_match_threshold 0.9
  cam3  pass1_backend botsort, bbox_buffer_scale 1.3, track_quality_filter 1,
        new_track_thresh 0.18, cost_metric dtw_mean
  cam4  (none - pure defaults)
  cam5  (none - pure defaults)

Ten per-camera knob columns exist; seven are exposed in the operator API
(routers/intersections.py:229-237, 519). calib_speed_tiebreak exists in the schema and is
read by pipeline.py:1697, but is NOT exposed in the API or the UI - wiring it is a build item.

FM 51, the blank site, has every knob NULL on all three cameras. That is the fact that
decides the ruling's stakes: a per-camera knob contributes NOTHING to the deliverable
unless a brand-new operator can set it correctly from the raw video and their own drawing,
with no reference to compare against. For the speed tiebreak they cannot - the thing that
decides it (whether two collinear paths' speed signatures separate) is a number in the
bank, not something visible on moving video.

Which is why a third option exists and is the one the project has already used once: make
the decision FROM THE SITE'S OWN DATA at run time, as EVIDENCE_ACTIVATION_COVERAGE does,
instead of asking the operator for it. Same shape, same precedent, one global default, no
knob.

## G-EX-2 ARM gx1 (DECLARED 2026-09-20, BEFORE THE FLEET SCORING): the observed exit binds

Stage 0 found this is the only problem on the list whose fix is named, specified and simply
unwritten. Built today, with the journey fate ledger (stage 1) in the same pass because the
six silent drops live in the same function.

THE RULE. `_finalize_vehicle_data`'s rescue block covered `full` (gate supremacy) and
`entry_only` (rescue_supports) and was guarded on `gate_origin is not None`. `exit_only`
means gate_origin is None BY CONSTRUCTION (entry_gates.classify_pair returns
`None, dest, ..., "exit_only"`), so a track born past its entry gate whose EXIT crossing was
witnessed could not reach the block at all: origin by heading, softmax destination refused
for tail motion at the vanishing point, whole journey dropped. When
`GATE_EXIT_ONLY_BINDING=1` such a track binds its destination to the OBSERVED exit leg,
movement by the cell's applied path label else derive_movement - the rescue_full convention
verbatim. Two guards: never when origin == the exit leg (classify_pair's exit_only path
never runs the u-turn admission tests, so a heading-tier origin equal to the exit leg would
mint the phantom u-turns the first-exit ruling killed), and the event bins off start_frame,
never the finalize frame (problem 7 is already a per-bin dispersion problem).
Inert below EVIDENCE_ACTIVATION_COVERAGE by construction - the gate locals are only bound in
evidence mode "on".

NOTED HONESTLY, a guard that does NOT exist: the straight-fragment rule cannot police these
events. It requires `posterior_source is None` and `destination_leg_id != gate_dest`, and a
bound journey fails both - evidence outranks the shape rule, exactly as it does for
gate_full. So nothing downstream checks turn inflation from this branch; the watch cells
below are the only check. (Measured on the smoke window: 5 of 438 bound events were turns.)

THE POPULATION, re-censused on the vl3 basis before building (the d18-era 537/316 came off
the `pr` dump, before the held-box guard and the Kalman velocity). classify_pair over the
dump, cross-referenced against the vl3 arm DBs' counted track ids:

  window                tracks  exit_only  of those NO event  dropped, exiting over N
  cam4 vl3_study_0700     5451        637        466 (73%)         445
  cam4 vl3_study_1600     8747        949        511 (54%)         458
  cam5 vl3_study_1100     4735        428         79 (18%)          41
  (same windows, for contrast: `full` drops at 1% / 1% / 6%, `no_crossing` at 92% / 84% / 71%)

cam4 0700's NB_thru shortfall is -360 with 445 dropped N-exits sitting there; cam4 1600's is
about -460 with 458. The sizes match. On cam5, whose cells are already OVER, there are only
79 candidates - the population sits where the undercount is and is near-absent where
inflation would hurt. FM 51 was deliberately NOT censused; it is held out and scored once,
after the corridor.

SMOKE WINDOW, disclosed because it was run before the fleet (cam4 vl3_study_0700, rule on):
  71.1 -> 86.7 movement, 41.7 -> 70.8 approach; events 4488 -> 4971 (+483 against a censused
  466); NB_thru 2353 -> 2786 against Miovision 2713 (was -360, now +73, inside the 5% bar);
  SB_thru unchanged at 2069; SB_right 46 -> 49. Of 438 rescue_exit events, 433 are throughs
  to leg 33 and 5 are turns. The fate ledger's remaining drops on that window: no_crossing
  362, no tag 49, full 26, entry_only 25, exit_only 18 (from 466).

THE ARM. Two legs, all 12 windows, same harness, same sitting - gx1 is a PASS-2 rule, so
unlike the vl3 tracker arm it moves cams 1-3 too and the control must be re-derived here
rather than carried over. cam4/cam5 on the vl3 dumps, cams 1-3 on production dumps.
  ctrl  FLEET_STEM=gx0, rule off   (must reproduce vl3's 79.38 / cams 1-3's standings)
  arm   FLEET_STEM=gx1, GATE_EXIT_ONLY_BINDING=1
  FM 51 held out, scored last: scripts/fm51_arm.py on vl3_l1_study_0700 / _1600, both legs.

PASS =
  1. the G-DEF-1 letter against the gx0 control: fleet mean rises, no camera's mean falls
     more than 1.0, no window falls more than 3.0; AND
  2. THE HONEST TEST, declared now: the fleet must clear d18b's 80.36. The vl3 arm reached
     79.38 and failed this by 0.97. The whole purpose of G-EX-2 is to convert eight days of
     tracker work into counted vehicles, so clearing the number position recovery reached
     ALONE is the test that means anything. A result between 79.38 and 80.36 is a MISS that
     still says the mechanism is real and under-firing, and iteration 2 is the exit-only
     SUPREMACY variant (bind an observed exit that DISAGREES with the softmax), not a
     constant tweak.

WATCH CELLS, pre-declared:
  - cam4 NB_thru must rise toward Miovision 2713 / 1546 / 2439. Overshoot is the risk now,
    not shortfall: the smoke window already crossed Mio by +73.
  - cam4 SB_thru and SB_right are already OVER (+112, +24) and must not inflate.
  - cam5 NB_left is already over (+156 at 1100) with only 41 northbound candidates; more
    than a few events on that cell means the branch fires wider than the census predicts.
  - cam3 0600 NB_thru per-bin dispersion (problem 7) must not worsen; its window total is
    +1.2% and inside the bar today.
  - The approach bar (problem 8, never targeted by any arm) is REPORTED, never decisive -
    but the smoke window moved it 41.7 -> 70.8 and that wants watching.

THE FATE LEDGER (stage 1, shipped with this, TRACK_FATE_LEDGER default ON). One `track_fates`
row per finalized track - disposition, reason, place, time - at each of the six silent
returns plus the counted path. Two of those six were counted by NOTHING before today (an
empty trajectory, and a no-origin track shorter than ORIGIN_ASSIGN_MIN_FRAMES); they now have
counters too. Diagnostics only: a run with it off is identical in the counts, held by a test.
Generalises scripts/cam5_sbinsuf_diag.py from one cell on one camera to every track.

## G-EX-2 ARM gx1 VERDICT (recorded 2026-09-20): the mechanism is real and large, and it
## MISSES the letter because it only ever ADDS

  window              ctrl(gx0)   arm(gx1)   delta    cov
  cam1 study_0700        85.1       77.0     -8.1    0.464
  cam1 study_1600        95.3       93.0     -2.3    0.570
  cam2 study_0700        75.2       77.1     +1.9    0.579
  cam2 study_1100        76.7       77.7     +1.0    0.500
  cam2 study_1600        68.5       71.3     +2.8    0.500
  cam3 study_0600        88.5       87.3     -1.2    0.585
  cam4 vl3_study_0700    71.1       86.7    +13.4    0.789
  cam4 vl3_study_1100    78.7       93.6    +14.9    0.819
  cam4 vl3_study_1600    69.8       84.9    +14.7    0.685
  cam5 vl3_study_0700    78.0       78.0     +0.0    0.579
  cam5 vl3_study_1100    83.0       83.0     +0.0    0.640
  cam5 vl3_study_1600    82.7       82.7     +0.0    0.677
  camera means: cam1 90.20 -> 85.00 (-5.20); cam2 73.47 -> 75.37 (+1.90);
                cam3 88.50 -> 87.30 (-1.20); cam4 73.20 -> 88.40 (+15.20);
                cam5 81.23 -> 81.23 (0.00)
  FLEET of 12: 79.38 -> 82.69 (+3.31)

  THE CONTROL IS CLEAN. gx0 reproduced the standing basis window for window - 85.1 95.3
  75.2 76.7 68.5 88.5 71.1 78.7 69.8 78.0 83.0 82.7, fleet 79.38, identical to the vl3
  verdict table. So the fate ledger is inert on the counts as designed and every number
  below is attributable to this rule alone. Logs runs/v2_week1/fleet_gx0.log, fleet_gx1.log.

  THE DECLARED HONEST TEST (must clear d18b's 80.36): 82.69. PASSES, by 2.33. This is the
  largest single counting-rule gain anywhere in this ledger, and cam4 - the camera that
  made the vl3 tracker arm fail - moves +15.20, its three windows +13.4 / +14.9 / +14.7.

  THE G-DEF-1 LETTER: FAILS, on two of three clauses.
      fleet rises                    +3.31   PASS
      no camera mean falls > 1.0     cam1 -5.20, cam3 -1.20   FAIL
      no window falls > 3.0          cam1 study_0700 -8.1     FAIL
  THE ARM DOES NOT SHIP. A default that ruins cam1 is not robust, which is what the clause
  is for.

  FM 51, THE HELD-OUT BLANK SITE: 85.7 / 89.8 movement, 73.9 / 79.2 approach - IDENTICAL to
  the control, one extra event across two windows. The rule is inert there, and for a
  reason that is the blank-site operating rule working as intended: lines drawn where
  vehicles are TRACKED means entries get witnessed, so exit_only is rare. No regression on
  the deliverable, and no gain either.

  WHY IT FAILS, measured from the fate ledger rather than guessed. The rule ONLY EVER ADDS.
  Where the tracker leaves a real deficit the additions land on real missing vehicles; where
  the count is already complete they are surplus:
      cam4 1100  NB_thru  1546 | 1356 (-190) | 1575 (+29)    the deficit closes
      cam1 0700  SB_thru  1756 | 1715 ( -41) | 1885 (+129)   a healthy cell overshoots
      cam1 1600  SB_thru  2498 | 2516 ( +18) | 2583 (+85)
      cam3 0600  SB_thru 14385 | 14490 (+105) | 14697 (+312)
  (Miovision | ctrl | arm.) THE DISCRIMINATOR, from track_fates: of cam1 study_0700's 227
  bound events, 115 - 51% - are born within 1.5 s and 120 px of an ALREADY-COUNTED track's
  death. On cam4 study_1100 that figure is 4 of 220, 2%. The bound track is the TAIL HALF OF
  A FRACTURED VEHICLE whose head half was already counted, and we count it a second time.
  cams 1-3 run BoT-SORT recipes and have never had the recovery tracker, so they fragment;
  cam4 and cam5 run it and hold one track per vehicle. That is the whole split, and it is
  why the rule's sign flips by camera.
  (This is also the first time the fate ledger paid for itself: the diagnosis is one query
  over track_fates, with no dump re-read and no new instrument.)

  ITERATION 2, the named fix - HIS OWN FRACTURE RULE, EXTENDED. FRACTURE_DEDUP (shipped
  2026-09-12 on his ruling) already says a short-gap, same-spot, same-heading death-and-
  rebirth is ONE vehicle. It admits only the pair whose EARLIER half lacks its exit, because
  until today nothing counted the later half. G-EX-2 now counts it. So the guard is the same
  ruling applied to the same geometry: refuse to bind an exit-only track that is the
  fracture-continuation of a journey already counted. Blind - a time-and-distance test on the
  dump, measured in box lengths like the shipped rule, no reference anywhere near it.
  NOT the exit-only SUPREMACY variant named in the plan: that was the iteration for a rule
  that UNDER-fires, and this one over-fires.

  NOTE for whoever runs iteration 2: cam4's northbound now slightly OVERSHOOTS (0700 +73,
  1100 +29 against Miovision) where it was -360 and -190. The duplicate guard will take some
  of that back, which is the right direction. Watch that it does not reopen the shortfall.

## ARM gx2 (DECLARED 2026-09-20, BEFORE THE FLEET SCORING): the bound-chain conservation guard

Iteration 2 of the G-EX cycle. gx1's failure has one shape: G-EX-2 only ever ADDS, so where
the tracker leaves a real deficit the additions are real vehicles and where the count is
already complete they are surplus. The surplus is a vehicle tracked in TWO HALVES - a head
with a witnessed entry and no exit, already counted, and a tail with a witnessed exit and no
entry, which G-EX-2 now counts as well.

THE GUARD. A bound journey whose fragment CHAIN already holds another counted event is
rejected (write-then-reject, rejected=1, reviewable). It runs as a pass-2 post-pass
immediately after the fracture rule - so that rule stays byte-identical and this one cleans
only the residue - and before the turn merge, the same reason the two existing dedups are.

IT ADDS NO CONSTANTS, which is the point. track_chains.chain_tracks already encodes exactly
this pairing and has since 2026-07-08: its tag gate is A_OK (entry_only, no_crossing) ->
B_OK (exit_only, no_crossing), i.e. a head that never exited followed by a tail that never
entered; its moving-break window is STITCH_MOVE_GAP_S (-0.48, 3.0) s, commented "occlusion
break mid-box", within STITCH_MOVE_DIST 70 px; a box-full journey may never chain (the
dedup-ceiling lesson); and CHAIN_DIR_TOL_DEG vetoes a direction disagreement while waiving a
dwelling endpoint (the queue-dwell law). The real pairs were measured BEFORE that module was
read - gap p10 -0.20 / p50 0.85 / p90 4.10 s on cam1 - and the July window and the September
measurement agree independently. 70 px is 2.56 box lengths on cam1 and 3.63 on cam4, so it is
not a tight bound either.

ONE CHANGE TO HOW THE CHAIN RULE IS FED. build_chain_map_ev tags with centre-point classify();
the counting default has used the JOURNEY STATE MACHINE since 2026-09-10 and the two disagree
- a track the pipeline calls entry_only can read 'full' under centre points, which blocks the
chain that should have formed. The guard therefore builds the bottom corners from the dump
and calls classify_pair, exactly as pipeline._gate_evidence does, falling back to classify
when the machine is off. Measured: 42 -> 66 rejections on cam1 study_0700, cam4 unchanged at 0.

SCOPE, and why this cannot cost a legacy vehicle: the pass may only reject rows whose
posterior_source is 'rescue_exit'. Its worst case is reverting part of what G-EX-2 added.
VERIFIED on cam1 study_0700 before the arm: 66 newly rejected, all 66 rescue_exit, 0 events
un-rejected, and with the guard OFF the window reproduces gx1 exactly (77.0, 5131 events) -
so the _pinned_gates extraction left the shipped fracture path byte-identical.

DRY RUN over the gx1 arm DBs, read-only, before building (frozen chain rule + state-machine
tags):
  window                 bound events   guard rejects
  cam1 study_0700             219           66 (30%)
  cam3 study_0600             347          158 (46%)
  cam2 study_1600              43            2 ( 5%)
  cam4 vl3_study_1100         219            0 ( 0%)
It bites on the two cameras that LOST and is silent on the two that gained. Runtime on cam3,
the largest window: 15 s.

SMOKE WINDOW, disclosed because it was run before the fleet (cam1 study_0700, both flags on):
  gx1 77.0 -> gx2 83.8 movement (control 85.1, so -1.3, INSIDE the -3.0 window bar);
  approach 71.0 -> 83.9. 66 events rejected, matching the dry run exactly.

THE ARM: FLEET_STEM=gx2, GATE_EXIT_ONLY_BINDING=1 BOUND_CHAIN_CONSERVE=1, all 12 windows,
cam4/cam5 on the vl3 dumps. No new control leg - gx0 (79.38) ran this session on this tree and
reproduced the standing basis window for window; gx1 (82.69) is the second reference. FM 51
held out, scored last.

PASS = the G-DEF-1 letter against gx0 (fleet rises; no camera mean -1.0; no window -3.0) AND
the fleet clears d18b's 80.36. Reported against gx1 as well, to price what the guard costs on
the cameras G-EX-2 helped.

PRE-DECLARED EXPECTATIONS, from the dry run, so the arm can falsify them:
  - cam4 loses NOTHING (0 of 219 on the sampled window). If cam4 drops, the guard fires wider
    than measured and the arm is wrong.
  - cam5 is untouched (almost no bound events at all).
  - cam2 keeps its +1.90 (2 of 43).
  - cam1 and cam3 recover most of their loss.
STATED HONESTLY BEFORE SCORING: cam3's surplus is ~+207 against 158 rejections, so cam3 may
still sit under its control. I will not widen a constant to buy a pass - that is tuning to the
answer. If gx2 misses, the two-iteration budget CLOSES the cycle and the deliverable is the
verdict plus two named successors: the residual complementary pairs the greedy chain refuses
(95 by a direct pair test vs 66 the chain links on cam1 - a chain-assignment question, not a
threshold one), and MERGE INSTEAD OF DROP (rewrite the head half's destination to the tail's
witnessed exit, making one complete gate-evidenced journey; worth 3 of 68 today, but it is the
variant that honours "the box sides ARE the gates" rather than discarding the witnessed side).

## ARM gx2 VERDICT (recorded 2026-09-20): the guard works, and the letter MISSES BY 0.20

  window              gx0 ctrl   gx1      gx2     gx2 vs ctrl
  cam1 study_0700        85.1    77.0     83.8       -1.3
  cam1 study_1600        95.3    93.0     94.2       -1.1
  cam2 study_0700        75.2    77.1     77.1       +1.9
  cam2 study_1100        76.7    77.7     77.7       +1.0
  cam2 study_1600        68.5    71.3     71.3       +2.8
  cam3 study_0600        88.5    87.3     89.0       +0.5
  cam4 vl3_study_0700    71.1    86.7     86.7      +15.6
  cam4 vl3_study_1100    78.7    93.6     93.6      +14.9
  cam4 vl3_study_1600    69.8    84.9     84.9      +15.1
  cam5 vl3_study_0700    78.0    78.0     78.0       +0.0
  cam5 vl3_study_1100    83.0    83.0     83.0       +0.0
  cam5 vl3_study_1600    82.7    82.7     82.7       +0.0
  camera means vs ctrl: cam1 90.20 -> 89.00 (-1.20); cam2 73.47 -> 75.37 (+1.90);
      cam3 88.50 -> 89.00 (+0.50); cam4 73.20 -> 88.40 (+15.20); cam5 81.23 (0.00)
  FLEET of 12: 79.38 -> 83.50 (+4.12)

  THE HONEST TEST (clear d18b's 80.36): 83.50. PASSES by 3.14. The fleet is the highest
  number in this ledger by a wide margin, and cam4 - the camera whose losses made the vl3
  tracker arm fail - finishes +15.20 with every window up 15 points.

  THE G-DEF-1 LETTER: MISS, on one clause by 0.20.
      fleet rises                    +4.12                          PASS
      no window falls > 3.0          worst cam1 study_0700 -1.3     PASS
      no camera mean falls > 1.0     cam1 -1.20                     FAIL by 0.20
  THE ARM DOES NOT SHIP ON THE LETTER. Recorded as a MISS, not argued down.

  EVERY PRE-DECLARED EXPECTATION HELD, including the one I flagged as likely wrong.
      cam4 loses nothing to the guard:  gx1 and gx2 identical on all three windows.
      cam5 untouched:                   identical on all three.
      cam2 keeps its +1.90:             identical on all three.
      cam1 recovers:                    77.0 -> 83.8 and 93.0 -> 94.2.
      cam3, which I said might still sit under control: 87.3 -> 89.0, i.e. +0.5 ABOVE its
      control. The prediction that it would fall short was WRONG, in the good direction.
  The guard rejected 74 + 22 bound events on cam1 and took cam3 from -1.2 to +0.5, while
  costing cam2, cam4 and cam5 exactly nothing. The discriminator behaved as measured.

  FM 51, THE HELD-OUT BLANK SITE: 85.7 / 89.8 movement, 73.9 / 79.2 approach - identical to
  the control to the decimal, one event different across two windows. Both rules are inert
  on a site drawn by the blank-site operating rule, because lines drawn where vehicles are
  TRACKED get their entries witnessed and exit_only is rare. No regression on the
  deliverable across this entire cycle.

  WHAT IS LEFT ON cam1, the 0.20 (Miovision | ctrl | gx2):
      study_0700  SB_thru  1756 | 1715 (-41) | 1820 (+64)     153 bound events survive
      study_1600  SB_thru  2498 | 2516 (+18) | 2569 (+71)      99 bound events survive
      study_0700  NB_thru  2141 | 2030 (-111) | 2044 (-97)    <- this one IMPROVED
  cam1's whole residual is southbound-through surplus from bound events with no counted
  chain partner. Two populations are in there and they are not separable from the score:
  vehicles whose head half was DROPPED rather than counted (so there is no partner to find,
  and binding the tail is CORRECT), and duplicates whose pair the greedy chain refused. A
  direct pair test found 95 complementary partners on study_0700 where the chain links 74,
  so ~21 of the residual are known-refused pairs; the rest are unclassified.

  NOT DONE, deliberately: no constant was widened to buy 0.20. That is tuning to the answer
  and the prime directive forbids it.

  THE CYCLE CLOSES HERE on the declared two-iteration budget. The deliverable is this verdict
  plus two named successors, neither a threshold tweak:
  1. THE GREEDY CHAIN'S REFUSALS. chain_tracks allows each track at most one predecessor and
     one successor and resolves by a (dist + 0.5*gap) score. On a dense arterial the right
     partner can lose that contest to a nearer wrong one. 95 direct vs 74 linked on cam1
     study_0700 is the size of it. A chain-assignment question, not a threshold question.
  2. MERGE INSTEAD OF DROP. Rewrite the head half's destination to the tail's WITNESSED exit
     instead of discarding the tail, making one complete gate-evidenced journey out of two
     halves. Worth only 3 of 68 on today's agreement measurement, but it is the variant that
     honours "the box sides ARE the gates" rather than throwing the witnessed side away.

  THE SHIP DECISION IS THE OPERATOR'S, and it is a real one rather than a formality: the
  letter fails by 0.20 on ONE test-footage camera, against +4.12 on the fleet, +15.20 on
  cam4, +1.90 on cam2, +0.50 on cam3, zero on cam5 and zero change on the held-out blank
  site. cam1 ends at 89.00, still the second-best camera in the fleet. Recommendation
  recorded: this is worth shipping and the letter's camera clause is worth him ruling on,
  because it was written to stop a default that RUINS a window (the -3.0 clause did that job
  here) and a 1.2-point camera mean against a 15-point gain is not that failure mode.

## SHIPPED — G-EX-2 + THE BOUND-CHAIN GUARD (operator go 2026-09-24: "ship it")

backend/config.py GATE_EXIT_ONLY_BINDING and BOUND_CHAIN_CONSERVE default "1" (commit
80ae8e9); test_default_off -> test_default_on for both; 1307 green, no env flags set.
The default is now EIGHT rules. scripts/reprocess_default.py guards all eight and compares
against the gx2 arm (with an ARM_VARIANT map, since cam4/cam5 ran that arm under the vl3_
variant name).

BASIS PROMOTED WITH IT. cam4/cam5 study_* dumps are now the RECOVERY TRACKER — the vl3 dumps
renamed into place, the old library-tracker basis kept aside as pre_gx2_study_*. This is the
tracker ship the operator deferred on 09-20 pending G-EX-2; the 83.50 was measured on it, so
shipping the rules without it would have left production in a third, unmeasured configuration.

Backup data/projects/97a7849a/backups/ (the apply gate takes its own per-window backup too).
All 12 windows reprocessed (force_once, apply through the gate; ~62 min, cam3 25 of them).
PRODUCTION == ARM ON 12 OF 12, row-for-row hash over
(track_id, movement, origin, dest, rejected, posterior_source) scoped to each window's
timestamp range. Log runs/v2_week1/reprocess_gx2_20260924.log.

  window       was     now    delta   health
  cam1 0700    85.1    83.8   -1.3    amber
  cam1 1600    95.3    94.2   -1.1    green
  cam2 0700    75.2    77.1   +1.9    green
  cam2 1100    76.7    77.7   +1.0    green
  cam2 1600    68.5    71.3   +2.8    green
  cam3 0600    88.5    89.0   +0.5    amber
  cam4 0700    73.3    86.7  +13.4    green
  cam4 1100    78.7    93.6  +14.9    green
  cam4 1600    70.2    84.9  +14.7    green    (supersedes the 70.2-by-ruling note)
  cam5 0700    79.0    78.0   -1.0    red
  cam5 1100    73.3    83.0   +9.7    red
  cam5 1600    71.8    82.7  +10.9    red
  FLEET        77.97   83.50  +5.53

FM51 stays the held-out witness and is UNCHANGED by this ship (85.7 / 89.8 movement,
73.9 / 79.2 approach, one event different across two windows); its counts are not shipped.

### WHAT THE SHIP SURFACED: cam5's health went RED on all three windows

Not caused by the counting rules. Attributed by direct measurement on cam5 study_0700, cell
counts for the two cells the health instrument flags:

  basis / rules                                  N_right (39->36)   N_left (39->38)   bound
  old production (library tracker, six rules)           18               418            0
  vl3 basis, the two new rules OFF                      34               456            0
  vl3 basis, the two new rules ON  (= shipped)          35               456            4

The whole move is the TRACKER BASIS PROMOTION. The new rules contributed 1 event to N_right
and 0 to N_left, and only 4 bound events exist on that window at all. The health verdict is
reading two real signals: N_left now counts 1.93x its historical flow (456 vs ~236), which is
problem 3 on the old list and is now LARGER in absolute terms under the better tracker; and
N_right shows 35 counts with NO history and 86% gate-override, flagged phantom_suspect.

So the recovery tracker bought cam5 +9.7 and +10.9 on two windows while making its NORTHBOUND
TURN cells worse. That trade was already visible in the vl3 verdict (NB_left 167 -> 156 over
Miovision at 1100) and is now the clearest open item on cam5. It is NOT a regression caused by
this ship and it does not argue against it — cam5's camera mean went 74.70 -> 81.23 — but the
red verdicts are honest and should not be cleared without an arm.

NEXT, unchanged by the ship: rebuild the error budget from these reprocessed DBs with
rule595.compliance's worst_n cap lifted. Problem 1 (cam4 northbound through, the old +4.16)
is SOLVED. cam5's NB_left / EB_right pair is the biggest thing the budget will now find, and
the July record classifies EB_right as a TRACKING capability problem written before the
recovery tracker existed — re-measure it on the current basis before treating it as counting.

## THE ERROR BUDGET, REBUILT AFTER THE gx2 SHIP (2026-09-24)

Same method as the 09-20 budget (5/95 rule rows, worst_n cap lifted), now over the reprocessed
PRODUCTION project.db for all 12 windows. Cross-checks: the 09-20 basis (d17 cams 1-3, vl3
cams 4/5) re-scores at 79.39, production at 83.50, both matching the recorded fleet numbers.

  basis           fleet mv   fleet ap   cell-bins failing     approach bins failing
  09-20 basis       79.39      57.35    239 / 1294 (18.5%)    181 / 493 (36.7%)
  production        83.50      63.35    211 / 1295 (16.3%)    168 / 493 (34.1%)

  per window (movement, approach):  cam1 83.8/83.9  94.2/80.0 | cam2 77.1/53.1  77.7/59.4
  71.3/46.9 | cam3 89.0/74.4 | cam4 86.7/70.8  93.6/70.8  84.9/70.8 | cam5 78.0/43.8
  83.0/56.2  82.7/50.0.  cam4's approach is again IDENTICAL on all three windows (17/24),
  moved from 41.7 -> 70.8; what is left of it is the SB approach.

THE PROBLEM LIST, rebuilt (prize = fleet points a perfect fix of the cell's failing bins returns):

  #  problem              fail/bins  dir     ours / ref      err     prize mv   approach prize
  1  cam5 NB left          24/24     over    1171 / 760     +54%      1.88     cam5 NB 6.25
  2  cam5 EB right         22/24     under    259 / 594     -56%      1.72     cam5 EB 5.47
  3  cam4 SB thru          10/24     over    6886 / 6578    +4.7%     1.72     cam4 SB 5.56
  4  cam2 EB right         21/24     over    1582 / 1217    +30%      1.66     cam2 EB 4.69
  5  cam2 SB right         11/24     under   1019 / 1108    -8%       0.87     cam2 SB 2.60
  6  cam4 SB right          5/24     over     216 / 77     +181%      0.81     (in cam4 SB)
  7  cam2 WB right         10/24     over     832 / 693     +20%      0.79     cam2 WB 4.17
  8  cam3 NB thru          29/56     both   13918 / 13756   +1.2%     0.68     cam3 NB 1.44
  9  cam1 NB left           6/16     over     667 / 611     +9%       0.66
  -- cam4 NB thru (old #1)  24 -> 2 failing bins, prize 4.16 -> 0.36: SOLVED.

WHAT MOVED: only cam4 NB thru (solved), cam2's NB left / SB thru / EB thru / EB left (each 1-3
bins better) and cam1 (worse: SB thru 1 -> 3 failing bins, SB approach 1 -> 4, EB approach
3 -> 4; cam1's approach bar fell 90.3 -> 83.9 and 86.7 -> 80.0 — the G-EX-2 residual). Every
other cell on the old list is unchanged to the bin, including all of cam5 (production cam5 ==
the vl3 arm on the movement and approach bars).

cam5 NB left + EB right is now the top of BOTH bars (3.60 movement, 11.72 approach). The EB
right deficit (-56%) is measured ON the recovery tracker: the tracker work did not reach it.

THE no_crossing POPULATION, sized from the gx2 arm DBs' track_fates (== production): 25,442
dropped no_crossing tracks fleet-wide, 71-85% of all drops on every window. By first->last
displacement: 17,802 (70%) move < 20 px, 6,855 move 20-60 px, 727 move 60-150 px, 58 move
>= 150 px. It is overwhelmingly stationary / jitter stubs, and the budget's top items are
mostly OVERcounts, which no drop can repair. The only undercount it could feed at scale is
cam5 EB right (-335 over three windows) against 134 cam5 no_crossing drops moving >= 60 px —
at most a partial answer, and only if they sit at the W/S corner. (path_distance is NULL on
most no_crossing rows; use the first/last points.)

## cam5 NORTHBOUND LEFT, measured on the shipped basis (2026-09-24, operator: "do left first")

Basis: the gx2 arm DBs (== production), surviving events only (the ledger's 'counted' rows
include events later rejected by dedup; join to vehicle_events.rejected).

1. WHERE THE EXCESS LIVES. Counted NB lefts by gate tag (0700 / 1100 / 1600): full 206/109/138,
   exit_only 65/54/62, entry_only 27/21/29, no_crossing 158/157/145. no_crossing is 40-47% of
   NB lefts but only 6-12% of NB throughs. The witnessed lefts alone (full + exit_only,
   271/163/200) sit BELOW Miovision (335/185/240); the excess is the unwitnessed stubs.
2. THE STUBS NEVER REACH THE DIVERGENCE. Full lefts leave the full-through corridor (15 px) at
   x ~ 360; the no_crossing lefts run x 546 -> 467 with 24-px boxes. 458 of 460 no_crossing
   lefts and 72 of 77 entry_only lefts stay inside BOTH corridors: nothing in their geometry
   says left. Their profile is identical to the no_crossing THROUGHS (same start, end,
   heading, straightness, box size). They are labelled left at ~1:1 against through where
   the approach's real split is ~1:8. (The ruling constraint holds: the discriminator here is
   segment coverage past the divergence, not stub-ness or entry evidence.)
3. THE LABEL'S SOURCE IS NOT YET REPRODUCED. The stubs lie upstream of every bank path's start
   (x ~ 441), so score_path_joint admits nothing; replaying score_destination_by_polyline on
   the stored trajectory does not reproduce the left either. Something else assigns it.
4. RELABELLING IS WRONG; SOME ARE DUPLICATES. Priced on cam5 (5/95, all three windows):
   all undetermined stubs -> through: mv -0.92 (NB thru overshoots). Dropping them all: mv
   +4.42, ap +20.8. So they are not missing throughs; the NB APPROACH is itself +10% over.
   A plain 0-3 s / 70 px partner test is NOT evidence: at time shifts of +-10/20 s it still
   finds a partner for 26-49% of stubs (dense queue, the follower trap). The stub's own
   velocity DOES separate: a counted NB track born within the tracker's frozen recovery reach
   (0.9 box, tracker._recovery_cost) of the stub's predicted position: 56/42/47 real vs
   ~5/4/5 at chance, ~90% precise. About a quarter of the stubs are provably the far-field
   head of a vehicle already counted from its later track. That explains roughly half the NB
   left excess; the other ~130 stubs a window are unexplained (distinct vehicles or
   duplicates the prediction misses).

## Arm pc1 DECLARED before scoring (2026-09-25): THE PREDICTED-CONTINUATION RULE

THE RULE (config.CONTINUATION_DEDUP, default OFF until a ruling). Movement-agnostic, one vehicle
is one count. Reject the event of track A when:
  1. A carries an unrejected event and lacks its exit (entry_only / no_crossing, pinned gates);
  2. track B carries an unrejected event, is born within STITCH_MOVE_GAP_S (-0.48, 3.0 s) of A's
     death, and outlives A;
  3. B's birth lies within TRACKER_RECOVERY_REACH (0.9) box widths of A's PREDICTED position
     (A's death + A's end velocity over its last CHAIN_BEARING_END_S x gap); box = max(A's width
     at death, B's width at birth), the tracker's _recovery_cost semantics;
  4. endpoint bearings agree within CHAIN_DIR_TOL_DEG when both exist;
  5. both events name the same ORIGIN leg (an entry_only A never loses a witnessed origin).
Greedy by residual/box + 0.5 * gap, each track in at most one pair, write-then-reject. It runs
AFTER the fracture rule and the bound-chain guard, so both stay byte-identical and this one only
cleans their residue. FRACTURE_DEDUP's 1.0 s / 1.0 box window is NOT widened. NO NEW CONSTANTS.

WHY: fracture measures from A's DEATH point; at the ~1 s median gap a moving far-field car has
left that box. Prediction is what separated real continuations from chance on cam5 (56/42/47 vs
~5 a window, the section above).

GATED DRY RUN FIRST: continuation_pairs over the 12 gx2 DBs + dumps, precision by the +-10/20 s
time-shift null. If chance exceeds ~20% of the real pairs on any camera, stop before the arm.

PASS = the G-DEF-1 letter against 83.50: fleet rises; no camera mean -1.0; no window -3.0; FM 51
not worse (85.7 / 89.8 movement, 73.9 / 79.2 approach). Approach bar reported alongside.
EXPECTED SIGN: cam5 up (NB left, NB approach); cam4 small; cams 1-3 UNKNOWN (BoT-SORT fragments
differently, more pairs will fire); cam1 is closest to the letter's edge. If cam5 gains and
cams 1-3 lose, it is reported as it stands.

### Arm pc1 dry run VERDICT (2026-09-25): GATE FAILED, the fleet arm was NOT run

scripts/research_continuation.py over the 12 gx2 windows (== production), no pass 2. The rule as
declared would reject 113/58 (cam1), 68/40/102 (cam2), 818 (cam3), 34/28/108 (cam4), 184/93/137
(cam5). Chance, measured by moving each fragment's death +-10/20 s at the same position and
velocity, as a share of the real pairs:
    cam1 31.2%   cam2 42.9%   cam3 18.4%   cam4 30.7%   cam5 36.6%    (declared bar: 20%)
Split by whether the fragment ENDED MOVING (the chain rule's frozen STITCH_STAT_SPEED_PXS):
    moving   cam1 27.0  cam2 32.2  cam3 17.3  cam4 29.2  cam5 29.2 %
    stopped  cam1 108   cam2 65.5  cam3 52.8  cam4 58.3  cam5 83.8 %
Stopped fragments are pure follower trap (prediction = death point = the next car's spot). But
moving fragments alone still fail on four cameras, so the fix is not a speed filter.
WHY THE cam5 MEASUREMENT DID NOT GENERALISE: the ~9% chance figure was on one population, the
undetermined NB-left stubs that never reach the divergence, sparse at x ~ 467. Over all
exit-lacking fragments of all origins, the rule samples dense queues at the mouths, where a
0.9-box circle around a moving prediction still catches the next car ~1 time in 3.
THE CODE STAYS, default OFF (config.CONTINUATION_DEDUP, turn_merge.continuation_pairs, 12 tests).
Nothing in production changed.

## cam5 EASTBOUND RIGHT, re-measured on the current tracker (2026-09-25): NOT a tracking problem

The July record called it tracking capability ("the near-field turn rarely survives tracking").
On the recovery tracker the ledger says otherwise. Tracks WITNESSED entering over W and exiting
over S (gate_tag 'full', W->S) that are DROPPED as classifier_insufficient: 99 / 100 / 146 a
window (0700/1100/1600), against an EB-right shortfall of 335 over the three windows. The
tracker forms the journeys; counting throws them away.

THE MECHANISM (trajectory_classifier.classify_trajectory): a right turn from the near-field W
leg into the far-field S leg reads as a ~142 deg heading change under perspective, which lands
in the U-TURN branch (>= TRAJECTORY_UTURN_MIN_ANGLE 135); the u-turn branch demands 90 px of net
displacement (TRAJECTORY_UTURN_MIN_NET_DISPLACEMENT_PX) that a turn into the compressed far field
does not have, and returns insufficient_data. pipeline._finalize_vehicle_data drops it at line
~1620, BEFORE the gate evidence is computed, so GATE_FULL_SUPREMACY (operator ruling 2026-08-24:
a full journey's crossings ARE the class) never sees it.

FLEET-WIDE: 1,613 full journeys are dropped this way on the 12 windows (cam2 200-281 a window,
cam3 307, cam5 122-186, cam1/cam4 15-37).

PRICED, by re-adding every dropped full journey (origin != dest) at its gate cell's label:
  cam5 +6.27 movement, +13.54 approach (EB right 76 -> ~175 at 0700; the deficit closes)
  cam2 -4.69 / -7.29   cam1 -2.03 / -1.61   cam3 -1.69 / -3.57   cam4 0.00
  FLEET 83.50 -> 83.42 movement (-0.08), approach +1.00. A blanket bypass FAILS the letter.
THE TWO POPULATIONS DIFFER: cam5's dropped journeys run ~9.5 s at ~7 px/s net with 6-10% of them
overlapping a counted twin; cam2's run 23-26 s at 2-3 px/s net with 24-28% twins (cam3 15 s,
3.9 px/s, 16%). cam2's are queue dwellers crossing gate lines slowly, the operator's queue-creep
ruling (2026-08-24: "queue creep across a gate line is not a journey"), which already has a
frozen test: MOTION_QUALIFIED_EVIDENCE's crossing_speed against STITCH_STAT_SPEED_PXS. Not yet
measured on these tracks.

### The dropped full journeys, split (2026-09-25)

MOTION TEST REFUTED. crossing_speed at both gate crossings vs STITCH_STAT_SPEED_PXS/fps: 1,543 of
~1,570 dropped full journeys cross IN MOTION, cam2's included (creep: cam2 23 over three windows,
cam3 1). Adding back only the moving ones: fleet 83.57 (+0.07), cam2 still -4.07. Not queue creep.

THE SPLIT IS SHAPE. Dropped vs counted full journeys of the SAME gate cell (|heading|, straightness):
  cam5 W->S (EB right)   dropped 142 deg, 0.43   counted 130 deg, 0.45   -> the same turn
  cam1 W->S              dropped 156, 0.41       counted 118, 0.44
  cam2 N->W (SB right)   dropped 150, 0.51       counted 85, 0.56        -> ambiguous
  through cells, cam2/3/5 N->S and S->N: dropped ~170 deg, straightness 0.03-0.07 against
  counted ~16 deg, 0.99 -> tracks that DOUBLE BACK (ID corruption); the classifier is right
  to drop them.
PRICED, adding back only drops with straightness >= 0.25 (a scratch cut, NOT a frozen constant):
  fleet 83.50 -> 84.28 movement (+0.78), approach 63.35 -> 66.46 (+3.12)
  cam5 +6.26 / +15.62   cam2 -1.79 / -2.08   cam1 -2.03 / -1.61   cam3, cam4 0.00
  Fails the -1.0 camera clause on cam1 and cam2. Caveat: this adds events AFTER the dedup
  passes; a real pass 2 would run fracture / twin dedup over them (24-28% of cam1/cam2's drops
  coexist with a counted twin), so only an arm prices it honestly.
NO FROZEN CONSTANT separates a loop from a turn (the only straightness constants are 0.95 and
0.97, for straight fragments). The frozen instrument that does judge in-box shape is the joint
scorer's admission against the bank path of the journey's own gate cell (CLAUDE.md: "the in-box
shape matched to operator channels").
