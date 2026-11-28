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
