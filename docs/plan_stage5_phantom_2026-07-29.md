# PLAN — STAGE 5.1: THE PHANTOM-SMALL-CELL CLASS (2026-07-29)

Parent: `plan_595_standard_2026-07-28.md` checklist 5.1. Written before
mechanism; this plan first RECORDS a supersession the checklist itself
could not know, then scopes what 5.1 honestly is now.

## The supersession (on the record before anything runs)

Checklist 5.1 says: "Phantom-small-cell treatment corridor-wide (the
proven C-proper/geometric-guard family) — own plan + pre-declared
gates." That sentence was written 2026-07-28 HOURS BEFORE the
operator-authorized deliverable-truthfulness sweep landed its verdict
(`plan_cam5_lane_echo_2026-07-27.md`, SWEEP VERDICT): **the frozen LEC2
bundle — which contains C-proper — FAILED the corridor blanket at every
corridor camera for four distinct measured reasons** (cam1/cam5
compensating-phantom MAE dependence; cam2 undercount deepening; cam3
turn-cell over-removal HARD STOP; cam4 the queue-follower STAT trap,
~1,000 real vehicles eaten), with FM51 the lone, large pass (MAE
5.4→1.8). 5.1-as-blanket is therefore ALREADY MEASURED DEAD; running it
again would relitigate a paid-for negative.

What is NOT dead, and is the honest residue of that sweep:

1. **The sweep's bar predates the 5/95 adoption.** Bars (1)–(4) are
   abs-err / net / approach-MAE shaped. Two corridor failures (cam1,
   cam5, bar 4) were CANCELLATION UNMASKING — per-cell truth improved
   while approach MAE worsened because phantom cells had been cancelling
   real deficits. Under THE standard (per-cell-bin 5/95), moving both
   cells toward truth is compliance GAIN, not loss. The bundle has
   never been judged at the customer bar. (cam3's over-removal and
   cam4's eaten vehicles are real failures under ANY bar — those stand.)
2. **The phantom-small-cell class is visible and unshipped.** Base
   production cells like cam1 N-right 77-vs-3 and W-through 38-vs-1
   (sweep evidence, replay-cells basis) are steady phantom trickles
   into near-zero-ref cells — every 15-min bin they touch fails the ±5
   grace. cam4's SB-right 20-vs-0 bin (a MISSED BIG in the recall
   study) and the star rating's cam4 echo-pool finding are the same
   family seen from two other directions.

## What this block does (5.1 v2 — measurement; no mechanism ships)

**A. Phantom inventory + post-review ceiling (production basis, the
promised 6.3 pre-measurement).** For every failing cell-bin (rule595
scorer, same windows as all Stage-1/2 evidence):
- class = PHANTOM-SMALL (ours > ref, ref ≤ 10) / OVERCOUNT (ours > ref,
  ref > 10) / UNDERCOUNT (ours < ref);
- caught/uncaught by the post-sweep open queue (the shared join);
- per camera: the post-review CEILING = (bins − fails + caught fails)
  / bins — what a perfect reviewer working today's queue could deliver;
  vs the 6.3 interim gate of ≥99%;
- the top offender CELLS (bins aggregated) per class — where the
  phantom mass lives, by name.
GATE A: the inventory table exists (runs/stage5_phantom/inventory.json)
and names, per camera, how much of the ceiling gap is phantom-class vs
undercount-class vs uncaught.

**B. The cheap sweep-evidence cross-view (replay-cells basis, named).**
From sweep_deliverable.json (no replays re-run): per site, which
phantom-small CELLS the frozen LEC2 bundle closes vs leaves vs
overshoots — cell-level only (per-bin does not exist in that evidence).
GATE B: the per-site phantom-closure table, labelled by its basis.

**C. The pre-declared design for the AUTHORIZATION ASK (not run).**
Re-judging the frozen LEC2 bundle at the customer bar = replayed-minutes
per-bin scoring, per camera, against the 5/95 cell-bin scorer, with
per-site shipping decided by the census activation signals (flip share /
same-cell echo share — the star rating's own metrics, C=0.45 precedent)
— i.e. exactly checklist 5.2 "[OP authorizes] census-gated LEC2
activation cycle". This plan STOPS at that boundary. The ask goes to
the operator with A+B's numbers; if authorized, that cycle gets its own
plan doc, budget, pre-declared per-camera 5/95 gates (cam3's
over-removal class and cam4's STAT trap as HARD STOPS unchanged), and
the replay re-derivation cost (~2–3 min/window, _replay_scratch).

## Scoring bases (named)

A: production project.db vs Miovision GT over the dev windows —
identical basis to rule595.json / the recall study / the Stage-2 sweep.
B: the sweep evidence's replayed-minutes cells (BASE vs LEC2) — a
different basis; cell-level; never mixed with A in one table.

## 5.1A/B VERDICT (2026-07-29 — evidence runs/stage5_phantom/inventory.json)

**A. Post-review ceilings (production basis, post-sweep queue — the 6.3
pre-measurement):**

| camera | raw | ceiling | gap to ≥99% | failing-bin classes (bins/veh, caught) |
|---|---|---|---|---|
| cam1 | 65.3% | 97.6% | 1.4 | over 27/564 (26) · phantom 16/129 (14) · under 15/439 (14) |
| cam2 | 46.7% | 96.5% | 2.5 | under 97/1,777 (88) · over 68/891 (67) · phantom 4/52 (3) |
| cam3 | 77.3% | **100.0%** | — | all 96 caught (over 34 · phantom 23 · under 39) |
| cam4 | 76.4% | **91.3%** | 7.7 | **phantom 22/295 (13)** · over 8/189 (7) · under 8/183 (4) |
| cam5 | 70.9% | 92.8% | 6.2 | under 44/640 (27) · over 24/543 (20) · phantom 25/201 (23) |

Only cam3 clears the 6.3 interim gate today. THE RECALL GAP, not
labor, is now the binding constraint on the deliverable claim — and it
decomposes by name:
- **cam4's gap is ONE CELL**: SB-right phantom-small, 20 of its 38
  failing bins, 281 veh — the star rating's echo pool, the 20-vs-0
  missed BIG, and the queue's weakest class in one place. Phantom
  events are HIGH-confidence tracks, so the uncertain-event feeders
  under-catch them (13/22) — the class needs either removal (mechanism)
  or a census-driven feeder (the chain census already knows which
  cells carry echo pools — an "echo_suspect" S6 feeder is the named
  cheap recall option, own small gate).
- cam5's gap is mostly UNCAUGHT UNDERCOUNT (SB-thru 381 veh, EB-right
  formation 167 veh — the known footage-gated walls) plus the named
  WB-phantom class (WB-right 11 bins/96 + WB-thru 9/70).
- cam2 is undercount-dominated (S3-blocked classes, 1,777 veh) —
  phantom work barely moves cam2; its route stays qualifying footage.
- cam1: NB-right phantom 12 bins/102 veh (the 77-vs-3 cell) beside
  attribution over/under on the thrus.
- cam3's EB-thru phantom (20 bins/450 veh — its 30>31 echo pool) is
  fully caught, so the ceiling holds, but it is raw-compliance mass a
  reviewer must hand-work every study: removal still pays labor.

**B. LEC2 on the phantom cells (replay-cells basis, named):** the
frozen bundle improves or closes EVERY base phantom-small cell in the
sweep evidence — cam1 N-right 77→25 (ref 3); cam3 N/S u-turns CLOSED
(31→9, 36→1); cam2 S-u-turn 98→48; FM51 N-left 51→25 (ref 1) — even
where its blanket failed other bars. The phantom-killing component
works; the blanket died of over-removal (cam3 turn cells) and the STAT
trap (cam4), which are DIFFERENT cells than the phantom class.

**THE ASK (checklist 5.2 — [OP authorizes], not run):** re-judge the
frozen LEC2 bundle per-site at the CUSTOMER bar (per-bin 5/95 cell-bin
compliance on replayed minutes), shipping per-site/per-class under the
census activation signals, with cam3's over-removal and cam4's STAT
trap as pre-declared HARD STOPS. The prize, sized by this inventory:
up to ~86 phantom bins / ~1,150 veh of raw failure mass corridor-wide
(plus FM51's proven 5.4→1.8), concentrated exactly where the ceilings
bleed. Alternative/complement at cam4 specifically: the echo_suspect
feeder (recall route — cheaper, no count changes, closes the ceiling
gap without touching the counts). Both need the operator's word; the
numbers above are the decision brief.

## Sequencing + commits

1. Inventory script + run → verdict here. COMMIT "Step 5.1A — phantom
   inventory + post-review ceiling".
2. Cross-view + the authorization ask → verdict here + MASTER_PLAN.
   COMMIT "Step 5.1B — LEC2 phantom cross-view + the 5.2 ask".
