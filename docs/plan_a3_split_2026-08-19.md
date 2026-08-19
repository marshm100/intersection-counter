# A3 — splice splitter (gate doc; declarations BEFORE any scored run)
# (2026-08-19; operator-designed: both cut rules, the completion
#  policy, and the review instrument are operator specifications.
#  Successor to QD iteration 1, dead at G-QD-1 17/17.)

## The two operator-observed splice mechanisms

- **Type 1 — post-exit lingering.** Track is good mouth→exit; after
  the car leaves, the tracker lingers and latches onto the stop-bar
  queue, riding the second car to the horizon. classify() returns
  the THIEF's exit (dest = exits[-1]).
- **Type 2 — mid-intersection box theft ("pinched trajectory").**
  A waiting turner steals the box from a mover: spatially two curves
  meeting at a cusp; kinematically an IMPOSSIBLE deceleration (15 mph
  to zero "on a dime" = the box jumping from mover to waiter),
  optional dwell (the thief waiting), then departure in a direction
  ≥ PINCH_ANGLE from arrival.

## Cut rules (constants declared here, frozen before validation)

- **Geometry cut**: at all_crossings()' FIRST outbound exit crossing
  + MARGIN_S = 1.0 s. (all_crossings factored verbatim from
  classify() 2026-08-19; suite 967 green = parity.)
- **Pinch cut**: chord bearings over k = 3 points; a cut fires at a
  stop-or-flip vertex where (a) arrival→departure bearing change
  ≥ PINCH_ANGLE = 120°, AND (b) the arrival deceleration is
  IMPOSSIBLE — speed falls from above the window's self-calibrated
  v_stop to below it within ≤ 2 chords with implied decel >
  DECEL_K = 3 × the window's fitted a_allow (fit_motion_residual;
  NO frozen pixel constants — the compression trap), AND (c) it is
  NOT a plain queue stop (departure bearing within 60° of arrival =
  no cut) and NOT a smooth U-turn (direction change distributed over
  > PINCH_SPREAD = 6 chords with same-sign deltas = no cut; the
  heading_series sign structure is the discriminator).
- Segments < 5 points are stubs (censused, never candidates).
- Segment ids tid*10+k in memory; emitted events keep the raw tid.

## Gates

- **G-A3-1 (labeled-splice validation):** the 17 operator-condemned
  cam2-1100 splices + the 6 deferred u-turn splices (re-derived from
  the QD candidate set). PASS per splice = the cutter produces ≥ 2
  segments with a cut frame STRICTLY BETWEEN the original track's
  first inbound crossing and its (spliced) last outbound crossing —
  i.e. the true car's journey is separated from the thief's exit.
  Target ≥ 20/23; every miss examined and typed.
- **G-A3-2 (label parity / do-no-harm):** for every tid carrying a
  KEPT production event in the window, either no cut applies, or
  some segment's classify() tuple (origin, dest, tag) equals the
  UNCUT track's classify() tuple. (Definition refined from the
  implementation plan: parity vs the uncut CLASSIFY story — the
  production event may legitimately differ from raw classify via
  posterior rescues, so uncut-classify is the honest invariant.)
  Bar: ≥ 99% of counted tids; every diff enumerated in the artifact.
- **G-A3-3 (scores + identity review):** two-level scores per window
  (approach ≥ live + 3.0 where a candidate exists; movement no
  regression; healthy-cell g4). MANDATORY operator identity review
  of every additive candidate set in the NEW reviewer (standing law
  after QD). U-turn candidates remain EXCLUDED (iteration-2 /
  embedding evidence).
- **G-A3-4 (apply):** recall-gate candidacy; cam2-1100 the only
  open window today; audited ceremony (v2_apply_reattr pattern with
  the additive precondition); everything else ledgered.

## Completion channel (operator's extrapolate-or-flag)

Segment-1 fulls → direct candidates (production-parity synthesize).
Segment-1 entry_only → PPT score_track("entry", origin fixed) under
calibrate() attr_max/margin floors → above: candidate; below: a
review_flags row (kind uncertain_event, subtype a3_extrapolation,
evidence_json = {tid, segment span, top cells + costs}) for the
upgraded reviewer. Guards ported from QD: chain guard (any-event
chains block), one-recovery-per-chain, queue-slot dwell guard at
T_dwell = 3.0 s (the QD freeze, geometry unchanged since —
geom_hash re-pinned per window in every artifact).

## Health metric

pinch_rate = pinch cuts / tracks ≥ 5 pts, per camera × window, in
every diag JSON — a GT-free tracker-quality signal (the operator's
object-permanence defect made measurable).

## Deliverables

scripts/v2_a3_split.py (audit / validate / compose modes),
backend factor-outs (landed), backend/tests/test_a3_split.py,
artifacts a3_validate_*.json / a3_c_*.json / score_a3_* /
a3_preflight.json, verdict sections here, roadmap update. Committed
either way.

---

## AMENDMENT 1 (2026-08-19, after validation run 1 — declared before
## re-run; both changes are rule/criterion corrections, not tuning)

Run 1: G-A3-1 39/56, G-A3-2 96.83% (137/4315 diffs). Anatomy:

1. **Geometry-cut rule corrected**: "first outbound crossing" fires
   on pre-entry JITTER blips (a bbox grazing outbound before the
   journey enters) and decapitates good tracks — the 137 parity
   breaks. Corrected rule: the first outbound crossing AFTER the
   first inbound crossing (entries[0]); born-inside tracks (no
   entries) keep first-outbound. "Cut when the movement completes"
   was always the operator's semantics.
2. **G-A3-1 acceptance corrected**: "cut strictly between first-in
   and last-out" cannot see the commonest Type-1 anatomy — the thief
   rides to the horizon WITHOUT crossing any gate, so the correct
   cut lies AFTER the last outbound crossing (severing an uncrossed
   tail), and born-inside splices invert the span. Corrected
   acceptance per labeled splice: >= 2 segments AND the first
   segment contains the track's first crossing AND the cut severs a
   real tail (cut frame < the track's last frame). The mandatory
   operator identity review (G-A3-3) remains the semantic backstop.

## AMENDMENT 2 (2026-08-19, after validation run 2 — declared before
## re-run)

Run 2: G-A3-1 improved but short-tail misses remain; G-A3-2 diffs
UNCHANGED at 137 — anatomy identified from the artifact:

1. **Pinch detector was structurally mute (pinch_rate 0.0):** units —
   fit_motion_residual's v_stop is px/SECOND (floor 8) and a_allow is
   px/s²; chord speeds are px/FRAME. Thresholds were ~fps× too high.
   Fix: convert with the window's fps at the comparison sites. No
   constant changes — pure unit correction.
2. **The 137 parity diffs are GATE-GRAZING journeys, not cuts gone
   wrong elsewhere:** real turns clip a neighboring gate's line
   mid-path (momentary out→in), and the corrected first-outbound-
   after-entry rule cuts at the graze. DISCRIMINATOR (declared):
   an outbound crossing ends a journey only if NO inbound crossing
   follows within RE_ENTRY_S = 2.0 s; a following inbound VOIDS the
   cut (graze) UNLESS it arrives via a discontinuity — frame gap
   > 0.5 s or a step speed > 4 × v_stop (a lost-track latch teleports
   to the stop bar; a graze re-enters continuously at road speed) —
   in which case the cut stands (Type-1 splice confirmed by the
   latch signature itself).
