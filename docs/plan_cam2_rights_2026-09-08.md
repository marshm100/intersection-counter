# CAM2 DOUBLED RIGHT TURNS (2026-09-08) — diagnosis

cam2's EB_right is the corridor's biggest single wrong cell:
  Miovision 1,217 across the day | production 1,722 | +505 OVER
And the biggest under is SB_thru: Mio 4,695, production 4,032 (-663).

## Hypotheses tested

1. MISATTRIBUTED ORIGIN (the cam5 invented-origin class — SB throughs
   booked as EB rights, which would explain both the over and the
   under at once). TESTED AND REJECTED: of 1,009 EB_right events in
   the evening window, the ground-anchored gate evidence witnesses
   880 entering over the W gate and only THREE over N. They really do
   come from the west arm. The two errors are separate problems.

2. SHAPE: these "right turns" average a net heading change of +9.5
   deg with straightness 0.855 — nearly straight, and nearly
   identical to the same approach's THROUGH (-10.8 deg, 0.923). For
   contrast the same camera's other rights bend +24.3 and +36.5 deg,
   and its EB LEFT bends -103.3 deg with straightness 0.446 (a proper
   turn shape). So the label does not match the motion. Note the
   shipped straight-fragment rule cannot reach them: their
   destination comes from a bank path fit, not a guess.

3. DUPLICATES. The loose test (coexist in time, end within 120 px)
   flags 711 of 1,009 — but that is the QUEUE TRAP the operator
   identified on cam5, where queued vehicles naturally coexist and
   end near each other. The tight test — median centre distance
   <= STITCH_STAT_DIST (35 px) across the whole shared life — flags
   155 pairs, the tightest 3-6 px apart for 166-428 frames. Queued
   vehicles sit a car length apart, so those are candidates for one
   vehicle counted twice. 155 would account for half the +310 excess
   in that window.

Note COEXISTING_TWIN_DEDUP is shipped and default ON, so these pairs
are passing it — worth checking which of its three criteria
(overlap fraction, median distance, median IoU) they slip through.

Filmed pair 4613+4616 (3 px apart for 17 s) for operator ruling:
one vehicle counted twice, or two vehicles that close?

## OPERATOR RULING (2026-09-09): the pair is TWO REAL RIGHT TURNS

"They're detecting the same vehicle [at first]... the blue detection
goes, and the orange is just kinda lingering there and just so
happens to catch the vehicle that pulls up and fills the spot that
the blue vehicle was in... then the orange vehicle also makes a right
hand turn. So it's both correct in the sense of two vehicles, two
right hand turns."

CONSEQUENCE — ALL THREE HYPOTHESES ARE NOW DEAD:
1. misattributed origin  — rejected by the gate evidence (880/1009
   genuinely enter over W).
2. duplicates            — rejected by this ruling. The 155 "tight
   pairs" are NOT one vehicle twice; they are a LINGERING BOX sitting
   in a spot that a second, real vehicle then fills. The counts are
   right. My tight proximity test is a second trap of the same family
   as the queue trap (a stale box occupies the same pixels a real
   vehicle later occupies).
3. shape mismatch        — ALSO refuted: he confirms both of these
   ~9.5-deg tracks made genuine RIGHT TURNS, so on cam2's geometry a
   real right registers around 9.5 deg. My "the label does not match
   the motion" argument was wrong.

THE +505 EXCESS REMAINS UNEXPLAINED.

## NEW DEFECT FOUND (separate from the over-count) — LINGERING BOX

A detection fires early and then LINGERS in place instead of holding
lock on a vehicle; when a different vehicle later pulls into that
spot, the stale box locks onto it. The resulting track's early
portion is false and its later portion is a genuinely different
vehicle. It did not cause this over-count, but it is a real
identity defect and a cousin of the progressive box-creep seen on
cam3. Chartered.

LESSON FOR THE INSTRUMENTS: proximity between two tracks proves
nothing about whether they are one vehicle. Twice now (queue on cam5,
lingering box here) a spatial-overlap test has produced a confident
wrong answer. Any duplicate claim needs the operator's eye or a
non-spatial signal.

## WHERE THE EXCESS SITS IN TIME (2026-09-09)

  study_0700  Mio 167 | prod 310.  Worst bins: 08:30 44/11, 08:45
              44/11, 08:00 38/11, 08:15 27/8 — a 4x gap AFTER 8am,
              while 07:30 and 07:45 run only ~1.5x (53/36, 63/40).
              Miovision's EB rights COLLAPSE to ~11 per bin after
              08:00; ours stay at 27-44.
  study_1100  Mio 351 | prod 444.  ~1.3-1.6x, spread evenly.
  study_1600  Mio 699 | prod 968.  A STEADY ~1.45x in every bin
              (146/97, 139/94, 136/92, 134/89).

Two different signatures: a uniform multiplicative excess in the
evening, and a collapse-vs-plateau divergence late morning.

## WHAT IS IN THE 08:30 BIN

44 events. Its three LONGEST tracks carry heading changes of
+179.6 deg (src gate_full), -133.4 and -151.1 — full or near-full
reversals, every one of them labelled a RIGHT TURN, on a camera
whose real rights bend ~9-30 deg (operator-confirmed). Filmed as
tids 17428 / 17526 / 18607 for his ruling.

So the reversal-shaped-track problem is not confined to cam3's
u-turn cell: on cam2 the same shape lands in the RIGHT-TURN cell.

## OPERATOR RULINGS ON THE 08:30 REVERSALS (2026-09-09)

Clip 1 (17428, nhc +179.6): "a right turn with no errors."
Clip 3 (18607, nhc -151.1): "perfect tracking of a right hand turn."
Clip 2 (17526, nhc -133.4): a vehicle PARKED waiting for traffic to
  clear, presumably to turn right — "the bounding box has not crossed
  the exiting threshold before the exiting label fires."

CONSEQUENCE: my heading-change reasoning is REFUTED for this camera.
Tracks at +179.6 and -151.1 deg are CORRECT right turns, so the
metric (exit chord vs the leg's calibrated reference heading) does
not describe vehicle motion on cam2's fisheye geometry. The
"reversal-shaped tracks booked as rights" inference was wrong.

CLIP 2'S BUG CONFIRMED IN THE DATA: tid 17526's crossings are
  W-in -> W-OUT -> W-OUT -> W-OUT -> W-OUT -> S-OUT -> S-in -> N-OUT
Four consecutive OUTWARD crossings of its OWN ENTRY GATE — a
stationary vehicle's box wobbling across the line while it waits,
exactly as he described. Neither the first-exit rule nor the
threshold law addresses it: the exit fires while the vehicle has not
moved.

SCALE OF THAT DEFECT (measured):
  study_0700: 25 of 169 excess  |  study_1600: 54 of 310 excess
  ("exit fired while essentially stationary", and separately
   "jitters over its own entry gate >= 2x": 25 and 49)
Real, but only ~15-18% of the over-count.

## STANDING: FIVE HYPOTHESES, FOUR DEAD, BULK UNEXPLAINED

 1 misattributed origin   REJECTED by gate evidence (880/1009 from W)
 2 duplicate tracks       REJECTED by operator ruling (lingering box)
 3 shape mismatch         REJECTED by operator ruling
 4 reversal-shaped tracks REJECTED by operator ruling
 5 stationary/jitter exit REAL, ~15-18% of the excess

THE DECISIVE TEST NOW IS A LABELLED SAMPLE, not another hypothesis.
Of three sampled events in the 08:30 bin (we count 44, Miovision 11),
the operator ruled TWO CORRECT and one buggy-but-a-real-waiting-
vehicle. If that rate holds across a larger sample, the excess is
NOT ours — Miovision would be undercounting that bin, which is the
possibility he raised at the cam1 driveway ("we might be entering a
space where we are more accurate than them"). More rulings settle it.

## SAMPLE RESULT (2026-09-09): 5 of 5 ARE REAL VEHICLES

Unbiased even-spread sample from the 08:30 bin (we count 44,
Miovision 11). Operator rulings across both rounds:
  17428  clean right turn, no errors
  18607  perfect tracking of a right turn
  16722  clean eastbound right, box on one vehicle
  17744  clean eastbound right, box on one vehicle
  17526  a real vehicle waiting to turn right (premature-exit bug)
FIVE OF FIVE describe genuine vehicles; four are clean counted right
turns. On this evidence THE EXCESS IN THIS BIN IS NOT OURS — the
reference is undercounting it. That is the possibility he raised at
the cam1 driveway ("we might be entering a space where we are more
accurate than them"), now with a sample behind it.

CAVEAT: five events out of a 44-vs-11 gap. It supports the reference
hypothesis; it does not close it. Note also the evening window's
steady 1.45x is a DIFFERENT signature and is not covered by this.

## NEW INSTRUMENT: THE THREE-STATE LABEL (his design)

He asked for three labels instead of two: ENTERING (detected, not yet
over the mouth), OCCUPYING (in the space of the intersection), EXITED
(over a threshold on the way out) — so that flicker becomes visible
and countable. Built as scripts/viz_states.py; every crossing flips
the state. First output:

  clean right (16722):   2 crossings, 1 flip
      OCCUPYING(W) -> EXITED(S)
  waiting vehicle (17526): 8 crossings, 3 flips
      OCCUPYING(W) -> EXITED(W) x4 -> EXITED(S) -> OCCUPYING(S)
      -> EXITED(N)

His predicted signature is exactly what appears: a clean pass is one
long occupancy then out; a waiting vehicle emits repeated exits over
its OWN entry gate. FLIP COUNT IS NOW A SCORABLE SIGNAL over the
whole population — a journey with many flips is a waiting/jittering
vehicle, not a clean movement.
