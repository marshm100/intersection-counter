# ARM fq1 — a standing track keeps its place (far-queue track theft) (2026-11-28)

DRAFT. Nothing has been run or built. No re-track and no fleet starts until the operator says go.
Acts on docs/diag_cam2_eb_right_2026-11-28.md. Form: docs/ARM_TEMPLATE.md.

## Bad news and what is unproven (read first)
- **The stage that does the theft is not known.** Only 1 of the 7 named tracks has a stage on disk: 3907, in the
  2026-10-09 cam2 1600 match-log run (runs/v2_week1/thefts_97a7849a_2_study_1600.json, frame 1488335 = 16:32:13):
  **stage 2** (low-score box, conf 0.13, track still Tracked, IoU(predicted, box) 0.52). The other six are not in that file.
- **It is probably not one stage.** Geometry rules stage 2 out for 3952: 19 -> 48 px wide in one step gives IoU <= 0.40,
  and stage 2 needs 0.5. So 3952 was stage 1 (IoU x conf >= 0.2, needs conf >= 0.5) or stage 2.5 (position recovery:
  size ratio 0.40 >= 0.3, IoU >= 0.2). In the same October file, far-band switches onto a box >= 2x the area split
  s25 106 / s1 38 / s2 21 (all switch kinds, not only standing cars). A fix written for one stage will miss the others.
- **The one case with numbers sits on the edge of every candidate bar.** 3907: width 28 -> 40 px (1.40x, under the 1.5
  reinit bar), area 2.0x, IoU about 0.50. Measured on yardstick boxes, not the track's own. The bar cannot be chosen
  honestly before step M1.
- **The existing theft instrument is as blind as the box-jump signature.** research_thefts.py found 1 of the 4 thefts
  filmed in 16:32 (same 1-in-4). Its yardstick chains need >= 15 hits and >= 120 px of travel, and a queued car's
  detections stop while it is covered. Both instruments are lower bounds.
- **The fix can feed the second leak.** A track that is no longer carried off stays on the queued car. If it dies there,
  it is a still piece, and still pieces are counted today (about 120 at cam2 1600, see item S). The EB-right cell may not
  fall until item S is also done. The arm must report still counted tracks before and after.
- **Hungarian is global.** Refusing one pair in stage 1 can reshuffle other pairs in that frame. Expect diffs outside the
  far band; they are judged by the tracking gate, not assumed harmless.
- Unproven: whether the passer is also counted on its own track (true double) or its own track breaks; how many thefts
  are gradual (several high-IoU steps while two boxes merge) and so invisible to any one-frame rule.
- Window count: the scored default list is 11 windows (cam1 0700 has no DB, per the 11-21 trial); CLAUDE.md says 12.
  The result must say which.

## 1. Requirement — question it
- **Failure:** cam2 EB-right over-counted +91 / +46 / +101 (0700 / 1100 / 1600; ref 167 / 351 / 699). In 16:32 Miovision
  has 0 and we count 6: 4 thefts at the far EB queue (3907, 3928, 3952, 4008), 2 still cars. Labelled-clip phantoms
  655, 686, 929 are the same theft.
- **Owner:** operator, memory "fix tracking inside the box, not count patches" (doubles = misses); CLAUDE.md "The
  tracker" (judged by tracking evidence); one-default ruling 2026-09-29.
- **Physics or recommendation?** Physics. A car at rest does not change image size or place. A box 1.5-2.5x its size
  moving at full speed is another vehicle. If we do nothing: cam2 keeps failing the approach bar by extra vehicles.
- **Raw video + calibration alone?** Yes. The rule reads only the track's own observed boxes and the offered box.
  No gate lines, no counts, no proportions, no redraw.

## 2. Delete — before adding
- `_reverse_jump_mask`, TRACKER_RECOVERY_REVERSE_DEG, TRACKER_RECOVERY_REVERSE_JUMP, `n_recovery_refused_reverse`
  (tracker.py, config.py): a default-OFF recovery guard with a written negative (rg3: few thefts removed, +235 / +542 / +49
  breaks). Same aim as this arm, worse test (needs observed motion; a standing car has none). Deleted in this arm;
  no fleet needed (off by default; the fork-equality test proves no change).
- scripts/diag_cam2_eb_right/instant.py's box-jump signature is retired as a judge once instrument T2 (below) passes
  its recall check. The script stays as the diagnosis record.
- NOT deleted: THEFT_SPLIT (a different shape: follow away, slow, come back; no one-frame jump), the held-box guard,
  COEXISTING_TWIN_DEDUP (measured -1.71 when off, LESSONS 2026-11-21). If fq1 ships, THEFT_SPLIT goes to a removal
  trial at the review date, not now.
- Add-back: expected ~0 % (the reverse guard never shipped).

## 3. Simplify — the mechanism, fewest constants
**Step M1 first (no code change to the tracker).** Run the dump's tracker in process on cam2 1600's cached detections
with `match_log` and `decision_log` on (research_thefts.py `stage_run` does exactly this; CPU, writes only a JSON under
runs/). For 3907, 3928, 3952, 4008, 655, 686, 929, and for every instant.py hit, read the record at the frame the box
leaves the queued car:
stage (s1 / s2 / s25 / unconf / confirm_pos), was_lost and lost age, det conf, IoU(predicted, det), IoU(last observed, det),
width ratio det / last observed, whether `_adopt` re-initialised the motion state (width jump > 1.5), whether the box
overlaps >= 0.6 a box another id took that frame, whether any detection (conf >= 0.10) still sat on the queued car, and
how long the track had stood. Accept M1 only if the in-process run reproduces the dump box for >= 6 of the 7.

**Branch on the answer:**
- **A. One-frame jump off a standing track, any stage(s)** (expected): build rule R below, in the stages M1 names.
- **B. The stolen box is stacked (>= 0.6) on a box another id holds, in stage 2:** extend the existing held-box guard
  (TRACKER_RECOVERY_HELD_IOU 0.6, today stage 2.5 only) to stage 2. No new rule, no new constant. May combine with A.
- **C. Gradual (no single step fails any bar; boxes merge over several high-IoU frames):** STOP. A per-frame rule cannot
  reach it. Write a new plan around the anchor test (T2 below) as the mechanism. Do not build R.
- **D. Mostly `unconf` / `confirm_pos` / births (a new id, not the standing one):** the diagnosis is wrong about the
  route. STOP and re-diagnose.

**Rule R (branch A).** A track is STANDING when its observed centre is within 1 box width of where it was 1 s ago
(speed under THEFT_MOVE_WPS = 1.0 widths/s over THEFT_RUN_S = 1.0 s; both exist in the linker's theft split and mean
exactly "moving"). A standing track is not offered a box that is not the box it stands in; the test is against its last
OBSERVED box, not the Kalman prediction. The pair is masked before assignment (so the box stays free for its real
owner, a deferred birth or a weak-birth history); the standing track coasts, which costs nothing because its
prediction is where the car stands, and it re-takes its own box when the passer has gone.
- The test, chosen by M1 from EXISTING bars only, in this order:
  1. width ratio beyond TRACKER_REINIT_WIDTH_JUMP (1.5). The fork already detects this jump in `_adopt` and answers it
     by restarting the motion state on the new box with the observed displacement as velocity: for a standing track
     that restart IS "standstill to full speed in one step".
  2. if (1) refuses fewer than 6 of the 7: IoU with the last observed box under TRACKER_STACK_IOU (0.6), the fork's
     existing "this box is that vehicle's box" bar.
  Selection rule, declared now: take the first test that refuses >= 6 of 7 named thefts in the M1 log. M1 also prints
  each test's COST from the existing dumps of all five cameras (no tracker run): the share of standing-track frames
  whose own next observed box would have been refused. If neither test reaches 6 of 7, branch C.
- **Constants added: none.** New state: one anchor (centre, frame) per track, plain attributes, `getattr` defaults so old
  checkpoints load. One env override TRACKER_STANDING_GUARD (X=0 = off, fork byte-identical; a test proves it).
- The standing status ends when the track has had no box for TRACKER_RECOVERY_LOST_PATIENCE_S (0.5 s): otherwise a
  refusal is sticky (the reference box never updates) and a car that pulls away after a missed frame would die.

**Near-field cameras (cam4, cam5).** R is inert for any moving track by construction: a large box moving fast is never
standing, at any size, because the test is in box widths per second. What can still go wrong: a large STOPPED car whose
box really changes (a crossing vehicle uncovers it; a car stopped half over the frame edge). M1's cost column is read
per camera before any build; after the build, the tracking gate is per site and the unit tests add: a near box at
200 px moving 0.5 widths/frame is never masked; a stopped edge strip that drives in is not killed.

## 4. Accelerate
- Slowest stage: the re-track of all windows (about 2 h serial from cached detections, no video; cam4 1100 53-120 s,
  cam2 and cam3 0600 700-3400 s each) and then a cold linker in pass 2.
- M1 and the cost column need no re-track of dumps. The first build is judged on ONE window (cam2 1600) before the
  other ten are re-tracked.
- A pass-1 change cannot be trialled by a pass-2 fleet over existing dumps (LESSONS 2026-11-23): new dumps under prefix
  fq1, never over study_*, and the linked dump is rebuilt from them.

## 5. Automate — nothing yet.

## Measuring thefts without the 1-in-4 detector
- **T1, the tracker's own log:** every `match_log` record where a standing track took a box failing the chosen test,
  by stage, per site. Complete for one-frame events by definition. With the guard on this is the refusal count.
- **T2, the anchor test (stage-free, catches gradual thefts too):** a track stands >= 1 s, then is >= 1 box width away,
  and within the next 1 s a detection (conf >= 0.10) sits on the box it left (IoU >= 0.6). That is what the film
  showed: "the queued car stays where it was". A car that really drives off leaves its spot empty for that second.
  Read-only on dump + detection cache.
- **Recall check before T2 is trusted:** it must flag >= 6 of the 7 named tracks and >= 3 of the 4 passer thefts among
  the 8 hits already checked on video. Precision: one sheet of 12 random T2 hits as stills (strip.py), no reels.
  If T2 fails this, say so and judge on T1 + labels only.
- research_thefts.py (chain yardstick) is still run per site, for comparison with the September numbers.

## Item S — still tracks counted (separate; deferred open item with its own plan)
- Should a track that never moved reach rescue_supports / branch1 at all? No. A path spanning under 2 box widths cannot
  have entered over one line and left over another; any "crossing" it has is a box jittering on a line it sits on.
- Why NOCROSS_DROP_SMALL / NOCROSS_NO_FALLBACK did not catch them: both look only at gate_tag = no_crossing. Read-only
  join of still.py's set with track_fates on the sf0 cam2 1600 DB (this session, about 120 still counted tracks):
  entry_only 50, exit_only 38, full 23, no_crossing 9. By source: no posterior source 64, motion_ray 24, motion_lane 11,
  branch1 11, rescue_supports 7. So the leak is wider than the two paths the diagnosis names: MOUTH_FROM_MOTION's
  "waited in a queue" paths and plain gate events carry most of it. 4014 = entry_only / rescue_supports (25 rows,
  28.7 px); 4052 = branch1.
- Scope of S: decide where gate evidence is built that a crossing needs displacement (one place, upstream of every
  counting path), not a patch in each path. Pass 2 only, existing dumps, one fleet (about 40 min).
- Order: S is planned after fq1's tracking result, because fq1 changes how many still pieces exist. S is NOT run in the
  same fleet as fq1 (two changes, one score).
- Flag for the operator, not this arm: rescue_supports and branch1 pick by "corpus-support proportions", which the
  memory "no inference beyond on screen" forbids.

## Gate (declared before scoring)
ARMS: control = the shipped default on the promoted study_* dumps (run 0). fq1 = the same code with the guard on,
dumps fq1_study_*, fleet stem fq1 (no underscore in the stem, LESSONS 2026-11-21).
- **G0 basis:** run 0 gives 91.88 and score files equal to sf0. If not: STOP, the control is not known.
- **G-M (before building):** M1 names the stage for >= 6 of 7 and a test refuses >= 6 of 7. Else branch C or D: no build.
- **G-T tracking (decides first; per site cam1-5 and FM 51):** on cam2, T2 thefts fall in all three windows and >= 6 of
  the 7 named tracks stay on their queued car. On every site: thefts (T2 and research_thefts) do not rise; breaks do not
  rise by more than thefts fall (the 2026-09-15 bar); one-track-per-vehicle (research_tracker_break.py timeline_all) does
  not fall. FAIL = any site worse on any of the three. A fleet gain does not rescue a G-T fail.
- **G-L labels:** eval_journeys.py control vs fq1, all clips, car by car: none worse, McNemar not against the arm,
  phantoms 655 / 686 / 929 gone with no new phantom. Held-out clips reported.
- **G-F fleet (G-DEF-1 letter, docs/plan_default_2026-09-10.md):** fleet rises over 91.88; no camera mean falls > 1.0;
  no window falls > 3.0. Pooled approach reported against 83.3, FM 51 reported (print the working DB mtime). Named cell:
  cam2 EB-right excess falls in each window, and still counted tracks are reported before / after.
- FAIL also if: G-T passes but EB-right does not move (then thefts are not what drives the cell: report, do not ship
  on a fleet number); or the letter is missed by any margin (no arguing it down, LESSONS 2026-09-24).
- Known before running: gains should be on cam2, possibly cam3's and cam5's far field; cam4 at risk from stage-1 reshuffles.

## Run queue (serial, one at a time; each needs an operator go; never two fleets at once)
| # | Run | Machine time |
|---|---|---|
| 0 | Confirming fleet on the promoted study_* dumps, deleted-collapse code, stem sfc. Expect 91.88 = sf0. PENDING from 11-23 | ~40 min (warm linker dumps) |
| 1 | M1 + cost column: in-process tracker with logs on cam2 1600; dump-only cost on all cameras. CPU, read-only | ~1 h |
| 2 | Build R (per branch). Guard-OFF re-track of cam4 1100 and cam2 1600: must be bitwise-equal to study_* | ~2 min + up to 1 h |
| 3 | Guard-ON re-track cam2 1600 (prefix fq1); T1, T2, named tracks. Stop here if G-T fails on this window | up to 1 h |
| 4 | Guard-ON re-track of the other 10 windows; tracking evidence per site | ~1.5 h + ~1 h CPU |
| 5 | Pass-2 fleet over fq1 dumps, stem fq1, FLEET_WORKERS=4 (cold linker) | ~1-1.5 h |
| 6 | eval_journeys control vs fq1; FM 51 re-track + fm51_arm.py | ~30 min |
Total about 6-7 h, of which about 4.5 h is re-track and fleet. No promotion of fq1 dumps to study_* without a ruling.

## Out of scope (not explained by the diagnosis; this arm does not fix them)
- EB-right excess in EB-green minutes (+0.56 / min at 1600): not inspected. fq1 will show how much of it was theft
  (T2 hits by phase); what remains is a separate diagnosis.
- SB-thru at 1600 (-84 net = +119 / -203 by minute): looks like minute-boundary and platoon timing. fq1 says nothing
  about it, except that a stolen track's passer was SB in the one case checked, so SB-thru could move either way.
- Steady WB over-count (+41 to +60), SB-right +71: not inspected; fq1 tells us only whether T2 finds thefts there.

## Independent review
`/review-arm docs/plan_far_queue_theft_2026-11-28.md` in a fresh session, ground truth first, before any ship.

## Review date
2027-02-28. If the guard never changed a result by then, it goes to a removal trial.
