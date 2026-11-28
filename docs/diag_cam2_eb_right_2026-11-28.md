# DIAGNOSIS — cam2's EB-right over-count (2026-11-28)

Data on disk only: the sf0 fleet DBs and dumps (the 91.88 control), the Miovision reference, the operator's journey
labels and event audit a1. No new labels. Scripts: scripts/diag_cam2_eb_right/. Images: screenshots/cam2_eb_right_2026-11-28/.

## Bad news first
- The over-count is not cam2 1600 alone, and it is not mainly a swap with SB-thru. EB-right is over in all three
  windows: +91 (0700, ref 167), +46 (1100, ref 351), +101 (1600, ref 699). SB-thru is under only at 1600 (-84). At 0700
  and 1100 it is over (+73, +36).
- cam2 also over-counts three of its four approaches in most windows: EB +78/+68/+118, WB +60/+41/+58, SB +96/+66/-12.
  So the approach bar (50.0 / 62.5 / 65.6) is failed by EXTRA vehicles, not by wrong labels.
- The cause found below accounts for SOME of the EB-right excess, not all of it. The numbers are lower bounds.

## The reference can be trusted here
Operator journey labels and Miovision agree to within 1-2 vehicles per cell on both cam2 clips (16:05-16:08,
16:50-16:53; mio_vs_labels.py). In those 6 labelled minutes we are within +1 on EB-right. So the excess is real, but it
happens in minutes the labelled clips do not cover.

## Where it happens
- Per minute (permin.py): at 1600 the excess is bursty. 22 of 120 minutes carry +83 of the +101. Several have
  Miovision at 0 against our 5-8 (16:32 0/6, 16:14 0/5, 12:15 0/8, 08:05 0/5).
- By signal phase (phase.py; an "EB red" minute = Miovision saw no EB thru or left): the excess per minute is about 2x
  higher when EB is red. 1600: +1.24 red vs +0.56 green. 0700: +0.95 vs +0.57. 1100: +0.86 vs +0.24.

## The mechanism, seen on the video
Camera geometry: lines 28 (W, the EB entry) and 29 (S, the exit) both lie along the FAR band, top of frame at
y ~ 105-130 px. EB cars queue just past line 28 (top right) as small far boxes, 18-35 px wide. A second line of
stopped cars sits past line 29 (top left). SB-thru and other traffic sweeps right to left along the band, directly in
front of the EB queue, and exits over 29. EB-right = enter 28, exit 29 = the same right-to-left sweep.

All 6 EB-right events in 16:32 (Miovision EB-right = 0) were looked at (s1632a/b.png, d3952.png):
- 4 THEFTS (3907, 3928, 3952, 4008). The track sits on a STOPPED car in the EB queue for 10-16 s. A passing car covers
  it, and the box jumps onto the passer (3952: 19 -> 48 px wide, standstill to full speed in one step). The track rides
  the passer out over 29. The event keeps the queued car's origin (28) and takes the passer's exit (29) = EB-right.
  The queued car stays where it was (the next frames show it still parked).
- 2 STILL CARS (4014, 4052). The track never moves: one car is in the EB queue, one in the stopped line past line 29.
  They were counted anyway, by the rescue_supports and branch1 paths.
The phantoms on the labelled clip (655, 686, 929) show the same theft (strip655.png, strip686_929.png).

## How big (lower bounds)
- Theft signature (instant.py): a stationary run of >= 2 s, then within 1 s the box area changes >= 2x AND the box
  moves >= 0.08 widths/frame. Hits on counted EB-right: 17 (0700), 12 (1100), 49 (1600) = 6.6 / 3.0 / 6.1 % of the
  cell. Every other cell sits around 0.3-2.8 %. Exception: NB-right 4/27 and 2/26, too few to read.
  - Precision: 8 random 1600 hits checked on video (jv.png). All 8 were bad tracks: 4 thefts by a passer, 4 boxes
    hopping between neighbouring stopped cars.
  - Recall is LOW. The signature caught 1 of the 4 thefts in 16:32 (3952 only); 3907, 3928 and 4008 were missed.
    The true theft share is larger than 49 at 1600, by how much is unmeasured.
- Still tracks (path spans < 2 box widths, still.py): EB-right 18 (1600), 3 (1100), 0 (0700). Other cells at 1600:
  SB-right 26, WB-right 18, EB-left 17, EB-thru 12, SB-thru 12.

## What this does NOT explain (unproven)
- EB-right excess in EB-green minutes (+0.56/min at 1600). Not inspected.
- SB-thru at 1600: -84 net hides +119 / -203 per minute (histogram -13..+6). It looks like minute-boundary and
  platoon timing as much as missing cars; not inspected. SB-right +71 at 1600 is spread thinly (108 of 120 minutes
  within ±2).
- WB over-count (+41 to +60): never over by >= 3 in any minute, so a steady small excess. Not inspected.
- Whether the passer is ALSO counted on its own track (which would make each theft a true double), or whether its own
  track breaks. On 3952 the passer was a SB vehicle; its own count was not checked.

## What it points at (for the planner, not a decision)
This is tracking inside the box, not counting: per the operator rule, doubles are misses. A track holding a small
stationary far box is matched to a larger moving box when the passer covers it, probably through ByteTrack's
low-score or predicted-box association (the queued car's own detection disappears while it is covered). The
tracker's held-box guard (2026-09-15) covers recovery only, and THEFT_SPLIT covers a different shape (follow away,
slow at a small box, come back). The physical fact a fix can use without proportions: a stopped car cannot reach
full speed and double its image size in one frame.
Still tracks counted as turns are a separate, smaller leak in rescue_supports / branch1: a track whose whole path
spans under two box widths crossed nothing.

## ADDENDUM 2026-11-28 (later): where cam2 actually fails, and what will NOT fix it
Scripts: scripts/diag_cam2_eb_right/{ceiling,bins,bysrc,wide,worst,shift,sheet,phantoms}.py (read-only, sf0 DBs of 2026-11-21).
Stills: screenshots/cam2_phantoms_2026-11-28/ (local).

Bad news first:
- **Removing the diagnosed causes does not pass cam2.** Dropping every still track AND every theft-signature track
  (ceiling.py) moves approach 50.0 / 62.5 / 65.6 -> 65.6 / 68.8 / 71.9 and movement 86.0 / 89.1 / 78.0 -> 88.0 / 87.1 / 78.0.
  Even with the signature's low recall, the theft arm (docs/plan_far_queue_theft_2026-11-28.md) is not the path to 5/95 on cam2 alone.
- **No single counting path is the culprit** (bysrc.py): dropping any one posterior source / gate tag raises approach by
  at most ~12 points in one window and lowers it elsewhere. Most counts (and most excess) are ordinary full journeys.
- **The journey labels cannot see the over-count.** Most cam2 "phantoms" (29 on the two clips) are cars that finish after
  the clip ends (6773, 6737, 6805, 6801, 6822, 6790, 796: smooth real EB-left / WB paths), as Step 9.103 found.
  Inside labelled minutes we match labels within 1-3 per approach-minute.
- **Not a clock offset** (shift.py): shifting our timestamps by -60..+90 s, shift 0 is best or tied on all 11 windows.
  (Miovision's per-minute split differs from the labels — 16:50 EB labels 11 / Mio 3; 16:51 labels 12 / Mio 19 — but this
  washes out in 15-min bins.)

Where it fails (bins.py, approach level): almost every failing bin is an OVER-count on the two light approaches,
EB +5..+21 per bin in every window, WB +4..+16. NB passes; SB fails some bins (+11..+27 at 0700/1100).
EB per-minute (worst.py, 1600): +244 in over-minutes vs -126 in under-minutes; the over-minutes are packed with
28->26 / 28->27 / 28->29 full journeys from the far EB queue.

Seen on video (sheet.py): near-field WB queue at the left edge, big boxes (130-250 px): tracks hop between neighbouring
queued cars (6801 red car -> white SUV, 6798 pickup -> red car, 6790 parked silver car for 50 s then a far box).
Far EB queue: tracks sit 20-60 s on queued cars; their exits are smooth and look real.

Unproven / next: which extra EB/WB full journeys are doubles (one car, two tracks) vs hops vs real. The fastest test is
an operator-free look at every counted EB event in the 3 worst minutes (worst.py lists them: 17:14, 16:50, 16:37) -
26+12+12 events - classifying each as real / double / hop.

## ADDENDUM 2 2026-11-28 (evening): the worst-minute classification, and a reference question
Scripts (read-only, sf0 DBs): pairs, nested, seqdbl, cross, cycles, onset, sheet2, xsheet, paths .py in
scripts/diag_cam2_eb_right/. Stills: screenshots/cam2_worst_2026-11-28/ (local).

Bad news first:
- **Doubles and hops are NOT the bulk of the EB excess.** Counted tracks co-moving on one car (nested.py: overlap
  >= 0.7 of the smaller box for >= 0.5 s, both moving >= 1 width, offset steady): EB 3 / 6 / 13 per window against an
  EB excess of +83 / +72 / +118. Sequential fragment doubles (seqdbl.py: B born <= 3 s after A dies, at A's extrapolated
  position, same heading): EB 2 / 2 / 5. A tracking fix for doubles cannot pass cam2 EB.
- **The whole EB excess is EB-right.** EB thru+left, Mio vs ours: 347/337, 502/524, 950/968 (fine). EB-right:
  167/258, 351/397, 699/800.
- **0700: EB-right matches until 08:00, then Miovision drops 4x at the hour boundary.** Per 15-min bin, Mio/ours:
  07:00 27/30, 07:15 23/28, 07:30 36/40, 07:45 40/44 | 08:00 11/33, 08:15 8/22, 08:30 11/26, 08:45 11/35.
  No other Mio movement absorbs it (all 16 slots printed; Lights/Mediums/Trucks all drop together). In red minutes
  07:01-07:47 Mio and we agree (~49 vs ~47); from 07:49 Mio has 0 EB-right in almost every red minute, we have 1-5.
- The 7 post-08:00 extras inspected on video (9228, 9263, 9073, 9098, 9136, 9144, 9169): all are real vehicles that come
  from the far right on the W leg, (some wait ~20 s at the far corner), and leave along the S leg. onset.py: none sat
  still then jumped, no box-size jump at motion onset, no other track died on its box. No theft, no double.
  Whether they are EB approach right turns (Mio missed them, or right-on-red is excluded) or e.g. driveway traffic at
  the far corner that a stop-bar count would not include is NOT decidable from the data; it needs a person on the video.
- 1600, cycle 17:14 (+17 vs Mio): line-28 crossings (cross.py) come at 1.6-3.6 s headways per lane position, i.e.
  saturation flow of distinct cars; on video 1 co-moving double (9553/9550), 1 nested box (9569 in 9548), 1 still car
  (9502, counted motion_lane). The rest look like real distinct cars. Mio per-minute split (16+15 over 17:14-15
  against our 26+15) cannot be checked further without labels.
- Side finding (not EB): an SB car leaving over line 29 often gets a second, same-heading fragment counted 29>27
  (NB) or 29>28: 27>29 -> 29>27 is the top sequential pair (15 / 4 / 9). One instance seen: 9271 (29>28) on 9228's car.

Unproven: WB worst minutes not classified. 1100 (excess grows after 12:15) and 1600 bins not checked against the
0700 pattern.

What it points at: before any arm, an operator ruling on the reference. 2-3 minutes of video (08:31-08:33, cam2) counted
by hand for EB-right decides whether cam2 0700 EB is a tracking problem or a Miovision one.

## ADDENDUM 3 2026-11-28 (night): the EB-right excess is right-on-red, and our tracks do not change at 08:00
Scripts (read-only, sf0 DBs): movbins.py (per-movement 15-min bins), ebr_phase.py (EB-right split by EB phase),
ebr_permin.py (per-minute EB-right), ebr_origin.py (start/end/wait/source of EB-right tracks, match vs excess bins).

Bad news first:
- **Nothing here is a tracking cause.** No arm is proposed. The reference question is now sharper, not answered.
- **WB is not doubles either** (nested.py: co-moving WB doubles 4 / 2 / 1 vs WB excess +62 / +43 / +58). The WB excess
  is spread over every WB movement at +5..+10 % per bin (movbins.py), all three windows. Not classified further.

Findings:
- **The EB-right excess is in EB-red minutes.** Phase proxy: a minute is "red" when Miovision EB thru+left <= 2
  (those match ours, so the proxy does not lean on the disputed cell). EB-right Mio/ours:
  0700 07-08 red 57/61 (+4), green 69/81 | 08-09 red 7/64 (+57), green 34/52
  1100 red 88/130 (+42), green 263/267 (+4)
  1600 red 172/238 (+66), green 527/562 (+35)
  At 1600 the per-minute pattern alternates with the cycle: green minutes match (11/13, 12/11, 15/14), red minutes are
  0/5, 0/6, 1/6, 0/3.
- **Our EB-right population does not change at 08:00; Miovision's does.** Our red-minute EB-right is 61 in 07-08 and 64
  in 08-09; Miovision's is 57 then 7. The tracks counted in the post-08:00 excess bins start, end, wait and are decided
  exactly like those in the bins that match (ebr_origin.py, 0700: start x median 467 vs 490, y 121 vs 121; end x 117 vs
  98; duration 14 s vs 14 s; still 4 s vs 3 s; same mix of posterior sources). If the tracker were inventing ~20 cars
  a bin from 08:00, something in the scene or the tracks would have to change at 08:00. Nothing does.
- 1100/1600 excess bins have somewhat longer waits than matching bins (1600 still-time p90 19 s vs 9 s; more branch1 /
  rescue_supports). This is the only hint left of a queue-related tracking cause, and the ceiling test (Addendum 1:
  dropping theft-signature + still tracks) already bounds it at a few points of approach.

What it points at: the dispute is right-turn-on-red from the EB approach. Either Miovision under-counts / excludes
RTOR (consistently after 08:00 at 0700, partially at 1100/1600), or our red-phase EB-right tracks include vehicles
a stop-bar count rightly excludes (e.g. driveway traffic at the far corner). The hand count should therefore count
EB right turns made while EB is red, separately from those on green.
Unproven: everything above about which side is right. Journey labels (16:05-08, 16:50-53) agree with Miovision on
EB-right (15 vs 14, 10 vs 10) but contain few red-phase minutes.

## ADDENDUM 4 2026-11-28: operator hand count, 08:31:00-08:33:59 — Miovision under-counts EB right-on-red
Tool: frontend/handcount.html (Step 9.137), session cam2_ebr_083100; scored by scripts/diag_cam2_eb_right/handcount_compare.py.
| minute | Miovision | ours | hand red | hand green |
| 08:31 | 0 | 5 | 5 | 0 |
| 08:32 | 1 | 2 | 0 | 1 |
| 08:33 | 0 | 1 | 2 | 0 |
| total | 1 | 8 | 7 | 1 |
- The hand count is 8 (7 on red, 1 on green). Miovision has 1. Ours has 8. **This is a reference defect, not ours**: in this
  sample Miovision misses EB right-on-red after 08:00 (consistent with Addendum 3: Mio red-minute EB-right 57 -> 7 at 08:00
  while ours stays 61 -> 64).
- Car by car (press time vs our origin-crossing time, <= 4 s): 5 of 8 match (9136, 9144, 9169, 9203, 9263). 3 presses
  (08:31:22, 08:31:49, 08:33:42) and 3 of our events (9073 08:31:00, 9098 08:31:13, 9228 08:32:50) are unmatched at 4 s.
  The totals agree; whether the 3 + 3 are the same cars with a late or inferred timestamp (9098 rescue_supports,
  9228 branch1) or 3 misses + 3 false counts is NOT shown. Not yet checked on video.
- Unproven: one 3-minute sample, one counter. 1100 / 1600 red-minute excess (+42 / +66) are not covered; a 16:32 count
  (Mio 0, ours 6) would show whether Mio's RTOR under-count also explains 1600.
Consequence: cam2 0700 EB-right after 08:00 (~+75) should be treated as a Miovision defect when judging cam2; no tracking arm
follows from it.

## ADDENDUM 5 2026-11-28: the 3+3 are the same cars; event time is first sighting; WB is not phase-bound
Scripts (read-only): hc_cars.py (who is at the EB line at each press), handcount_compare.py (now matches on the exit-line
crossing), retime.py (re-times every event at its track's LAST origin-line crossing and rescores; PHASE=WB|EB adds the
red/green split both ways), phase_split.py (phase_split for any approach).

Bad news first:
- **Our event timestamps are not crossing times.** `timestamp_real` comes from `vehicle["origin_frame"]`, which is set when
  the origin is ASSIGNED (path-shape prefix match after 4-8 points, pipeline.py:1223; rescues stamp `start_frame`,
  :1530/:2152) - for a queued car that is its first sighting, up to minutes before it leaves the stop line. The comment at
  pipeline.py:2218 says the intent is the crossing. This is a production timing defect on every camera.
- **Fixing it does not fix cam2.** Re-timed at the stop-line departure, only 21 / 32 / 32 events change 15-min bin;
  cam2 movement / approach 5/95 86.0/50.0 -> 85.0/56.2 (0700), 89.1/62.5 -> 87.1/62.5 (1100), 78.0/65.6 -> 78.9/62.5 (1600).
- Addendum 3's WB red/green split was mostly this artefact (below). No tracking cause found; no arm.

Findings:
- **Hand count 08:31-08:33: all 8 presses are our 8 cars.** Matched on the exit-line crossing, 7 of 8 presses lead our
  track's exit crossing by 1.0-2.1 s (9073, 9136, 9144, 9169, 9203, 9228, 9263); per minute 5/1/2 = hand 5/1/2. The 8th car
  (press 08:31:27) is one car in two pieces: 9098 (queue fragment 08:31:10-15, x 524->431, never reaches a line, COUNTED
  by rescue_supports) and 9117 (starts 3 s later at x 420 where 9098 ended, makes the turn, DROPPED classifier_insufficient).
  Counted once, timestamped 14 s early. Not a miss, not a false count. The earlier "3+3 unmatched" was the comparator
  matching on the first-sighting timestamp.
- **WB excess is not right-on-red.** Stamped: WB-right red +28 / green -2 (0700), WB-thru red +20. Re-timed: WB-right red +7 /
  green +19, thru red +7 / green +11; 1100 and 1600 the same way. Queued WB cars first seen in a red minute were binned
  into it. Re-timed, the WB excess is spread over phases and movements: a uniform over-count of fully seen journeys
  (partial-track rescues are only 30 / 33 / 60 WB events against +62 / +43 / +58). Still unclassified.
- **EB-right red-minute excess survives re-timing** (+61 -> +71, +42 -> +32, +66 -> +72) while the control cells move as they
  should (0700 EB thru / left on red +30 / +45 -> +1 / +11). Addendum 3-4's right-on-red reading stands.
- Labelled clips, WB: 16:05 labels 7 = ours 7; 16:50 labels 13, ours 16 (+2 26->27, +1 26->29). Of the +3, two tracks end after
  the clip (6801, 6822: not phantoms); 6798 (n 22, rescue_supports) is a second id on a near-field van that 6801 also
  carries - one double. Too few to classify the window-level WB excess.
Unproven: which side is right on WB (no WB hand count yet); whether the timestamp fix helps the fleet (not run).

## ADDENDUM 6 2026-11-28: hand counts at 16:32 and 12:15 - at 1100/1600 the red-minute EB-right excess is OURS
Sessions cam2_ebr_163200 (presses 16:31:40-16:34:24, 24) and cam2_ebr_121500 (12:14:48-12:16:08, 8); handcount_compare.py now
takes [FROM TO] and aligns minute rows to whole minutes (the old code looked Mio up at the span's start SECOND and read 0).
Bad news first: **this reverses Addendum 4's generalisation.** Only the 08:31 sample shows a Miovision RTOR gap.
| minute | Mio | ours | hand |
| 16:32 (EB red) | 0 | 6 | 1 |
| 16:33 | 15 | 17 | 15 |
| 12:15 (red until ~:55) | 0 | 4 | 2 (both green, 12:15:56/58) |
- 16:32-16:34: 22 of 24 presses match our tracks (exit-line time, 1-2 s lag); 2 presses missed. 10 of ours unmatched, 7 of them inside
  the 66 s red gap 16:32:01-16:33:07 where the operator pressed nothing and Mio has 0: 3873 motion_lane, 3907, 3928 motion_lane,
  3952, 4008, 4014 rescue_supports, 4052 branch1. Four (3873, 3907, 3952, 4008) are FULL journeys: they cross the EB line's upper
  (far-road) end and then the exit line, running right-to-left along the far road (stills: paths.py study_1600 1488150 / 1488735).
  i.e. cross-street traffic moving while EB is red is being given origin 28 (EB) where the EB gate's far end reaches across the far
  lanes. The same shape is in the labelled-clip phantoms (16:05: 655, 686, 929) and in 27->29 labels counted as 28->29 (16:50: 689, 772).
- 12:15: the 2 unmatched (5566 motion_wait, 5606 branch1) are partial tracks with no exit crossing, in red.
- Where they really come from is NOT shown: SB-left is not under-counted (+4 / +0 / +12), NB-left is (-21 / -33 / -29). Needs the
  far-road tracks' full paths against all four gates (which leg's line do they cross before 28?).
Next: classify the 1600 red-minute EB-right tracks by where they are born and which gates they cross (far-road right-to-left vs EB
queue); if far-road traffic is the bulk, that is a tracking/origin cause -> one-page arm (no line redraws: solve in software).
