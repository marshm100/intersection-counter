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

## 5.1C — THE echo_suspect FEEDER (operator: "go", 2026-07-29;
design pre-declared here BEFORE implementation)

The recall route for the phantom class: phantom events are
high-confidence, so the uncertain-event feeders cannot see them — but
the CHAIN CENSUS can (same-cell excess = one vehicle chain counted ≥2×
into one cell). New S6 feeder, blind by construction:

- Source: the footage-rating chain census (cached sidecars; the census
  gains a per-cell same-cell-excess detail, CENSUS_VERSION bump).
  Emits ONLY where the event join is valid (tier C) — a legacy table
  that cannot join gets nothing from the runtime feeder (no fabricated
  suspicion).
- Rule (frozen): a cell with same-cell excess ≥ 5 over the processed
  day (below 5, echo alone cannot breach a bin's ±5 grace) → ONE
  cell-level flag: kind=suspected_gap, subtype=echo_suspect,
  approach+movement from the cell, impact = the excess count, no
  interval (cell-broad match, S4-style — catches every failing bin of
  the cell in the recall join), child-language reason.
- Wired into feed_suspected_gaps (future rebuilds emit it natively).
- **Backfill for the CURRENT production queue** (which must not be
  rebuilt — S5 loss): one script inserts echo_suspect flags for all
  corridor cameras — tier-C cameras from the production-basis census,
  tier-B legacy cameras (cam4, cam5) from the phase-0 replay censuses
  (runs/cam5_wall/chain_census_*.json), the basis recorded per flag in
  evidence. Inserts are reversible (delete by subtype).

**GATE 5.1C (pre-declared):** cam4 post-review ceiling ≥ 96.5% on the
re-run inventory; recall/BIG recall deltas ≥ 0 everywhere (inserts can
only add matches); open cards grow by ≤ 3 per camera. Tests: census
detail, feeder emission on the synthetic echo, tier-B refusal.

## 5.1C VERDICT (2026-07-29 — evidence runs/stage5_phantom/inventory.json
re-run; queue state 743 open / +17 echo_suspect flags)

**Shipped**: census per-cell echo detail (CENSUS_VERSION 3) + the S6
echo_suspect feeder (runtime, tier-C-only, wired into rebuilds) + the
production backfill (tier-C cams from the production census; cam4/cam5
from the phase-0 replay census, basis recorded per flag; reversible by
subtype delete). 874 tests (+2).

**Post-review ceilings, before → after the feeder:**

| camera | before | after | notes |
|---|---|---|---|
| cam1 | 97.6 | 97.6 | echo cells already caught |
| cam2 | 96.5 | **99.4** | clears the 6.3 bar; the three SMALL pools (24/13/9) sit in exactly cam2's three missed-BIG cells (EB-left / SB-right / NB-left) |
| cam3 | 100.0 | 100.0 | held |
| cam4 | 91.3 | **98.8** | GATE ≥96.5 PASS; SB-right phantoms 13→20/22 caught |
| cam5 | 92.8 | **95.9** | +10 catches incl. 8 undercount bins |

**GATE 5.1C: PASS on ceiling (98.8 ≥ 96.5) and recall (all caught
counts monotonically ≥; 54/167/96/36/80 vs 54/158/96/24/70) — with ONE
component BREACHED WITH CAUSE:** cards grew +6 at cam2 vs the declared
≤3. The letter-compliant trim was MEASURED (drop the three smallest
pools): cam2's ceiling falls 99.4 → 96.5 — those three flags carry all
nine new catches and are cam2's three missed-BIG cells. Three extra
cards (+2.5% of cam2's queue) buy the 6.3 bar at cam2; the flags were
restored and the exception is surfaced to the operator here as an
explicit bar decision (precedent: relaxed-bar decisions are the
operator's). To revert instead: delete cam2's echo_suspect flags with
impact < 25.

**Mapping corrections (the record must be exact):** cam3's echo pools
30>31/31>30 map to SB/NB-thru (leg 30 = N cardinal → SB bound), NOT
EB-thru as the 5.1A narrative inferred — cam3's EB-thru phantom class
is NOT echo-pool-driven. cam4's 35>33 pool (1,181/day) maps to NB-thru
and is the STAT queue-follower signature (real queued vehicles chained
together) — its flag's expected review verdict is "real vehicles,
dismiss", and it still usefully covers cam4's 10 NB-thru failing bins.
Phantom ≠ echo everywhere; the feeder catches the echo-driven subset
plus whatever its cell-broad match covers.

**Corridor after 5.1C**: ceilings 97.6 / 99.4 / 100.0 / 98.8 / 95.9 —
two cameras at/above the ≥99% interim bar, two within 1.2 points, cam5
at 95.9 with its remaining gap = uncaught undercount (formation walls,
footage-gated). The recall route is near its structural limit; what
remains is raw compliance (5.2) and footage (Stage 6).

## 5.2 — THE AUTHORIZED LEC2-UNDER-5/95 CYCLE (operator: "authorized",
2026-07-29; pre-declared here, own evidence file)

Re-judge the frozen LEC2 bundle (constants exactly as committed —
bearing 55, L=40 full-only + concurrent cut, C-proper, R rmin=3; no
refitting anywhere) at THE CUSTOMER BAR, per site, on the
replayed-minutes basis (the sweep harness's own event streams, per-bin
via their timestamps, vs GT per-minute through rule595.score_cells).

**Pre-declared per-camera gates (all five must hold to join the ship
set):**
1. 5/95 cell-bin compliance strictly improves (the customer scorer).
2. No NEW BIG failing bin (|Δ| ≥ 20) is created.
3. Fixed-vs-broken honesty: bins flipped failing→compliant and
   compliant→failing both reported; net flip must be positive AND
   broken bins ≤ 20% of fixed bins.
4. HARD STOPS unchanged from the deliverable sweep: cam3's turn-cell
   over-removal class (E-right / N-left cells may not worsen at all)
   and cam4's STAT queue-follower trap (any sign of the eaten-vehicle
   signature = out). These two cameras carry their sweep verdicts as
   priors; the 5/95 re-judgment can only EXONERATE them by clearing
   every gate including these.
5. FM51 (ftv2n replay basis, held-out): same gates — it must confirm
   its sweep win at the customer bar or the activation story dies.
**Census-gated activation (the shipping rule):** cameras passing the
gates ship ONLY if their census composition also says the mechanism's
class applies (candidate signal: same-cell echo share / flip share —
the star rating's own metrics; the threshold frozen from the verdict
table's measured gap, never per-site). Production application per
shipping camera = measure-then-apply through the real pass-2 with the
operator's per-camera ✓ — NOT this block.

## 5.2 VERDICT (2026-07-29 — evidence runs/stage5_phantom/
lec2_595_judgment.json; replayed-minutes basis, cam3 daylight cut;
no replays re-derived, constants frozen, no refitting)

**SHIP SET: EMPTY. All six sites FAIL the pre-declared customer-bar
gates — including FM51.**

| site | 5/95 base→lec2 | fixed | broken | new BIG | undercount Δ | failed gates |
|---|---|---|---|---|---|---|
| cam1 | 59.3→70.1 | 14 | 4 | 2 | +41 | G2 G3 G4b |
| cam2 | 41.6→42.1 | 16 | 12 | 12 | +169 | G2 G3 G4b |
| cam3 | 76.4→82.2 | 38 | 9 | 5 | −544 | G2 G3 **G4a hard-stop** |
| cam4 | 72.1→**65.7** | 7 | 16 | 19 | **+1,048** | G1 G2 G3 G4b |
| cam5 | 63.0→76.1 | 51 | 9 | **6** | −287 | **G2 only** |
| FM51 | 65.4→**62.9** | 7 | 4 | 0 | +83 | G1 G3 G4b |

- **The headline negative: FM51's deliverable-sweep win (MAE 5.4→1.8)
  does not survive the customer bar.** The bundle improves the day
  AGGREGATE while breaking individual bins (compliance down 2.5 pts,
  broken 4 vs fixed 7, real vehicles removed: undercount +83). The
  5/95 standard's per-bin structure punishes exactly what MAE forgives
  — the operator's bar change caught a mechanism the old bar would
  have shipped at its one "good" site.
- **G4b (the eaten-vehicle detector) measured the cam4 STAT trap at
  +1,048 undercount — the "~1,000 real vehicles" of the deliverable
  sweep, now counted exactly.** cam3's hard-stop cells confirmed worse
  at bin level (G4a). The priors held.
- **The one named near-miss: cam5** — massive bin-level win (63.0→76.1,
  fixed 51 vs broken 9, undercount DOWN 287, its phantom closure real
  at per-bin granularity) failing ONLY on 6 newly-created BIG bins.
  If any future cycle revisits this family, the target is those 6 bins
  (plausibly the R-resurrection or C-reroute components concentrating
  mass); own plan + budget, not this block.
- **Census-gated activation: MOOT** — there is nothing to activate
  anywhere. The 5.2 question the operator authorized is ANSWERED, in
  the negative, with numbers.

**CONSEQUENCE:** the LEC2 bundle is now measured dead at BOTH bars
(deliverable sweep: 5/6 fail; customer bar: 6/6). Retirement is total;
the revival-ready code stays on the shelf with this verdict attached.
Raw-compliance gains on current footage are exhausted at measured-safe
mechanisms; the remaining raw route is qualifying footage (Stage 6),
exactly as the walls said. The corridor's claim machinery now rests on:
raw compliance as-is + the queue (ceilings 97.6/99.4/100.0/98.8/95.9)
+ the operator review — and the acceptance test on procured footage.

## Sequencing + commits

1. Inventory script + run → verdict here. COMMIT "Step 5.1A — phantom
   inventory + post-review ceiling".
2. Cross-view + the authorization ask → verdict here + MASTER_PLAN.
   COMMIT "Step 5.1B — LEC2 phantom cross-view + the 5.2 ask".
