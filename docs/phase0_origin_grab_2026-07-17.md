# Origin-grab cycle phase 0 — birth-geometry autopsy (2026-07-17)

Per `plan_origin_grab_cycle_2026-07-17.md`: every side-leg ORIGIN CLAIM on
the FM51 fine-tuned dumps (ftv1_am/pm replays, project 0acb12c0 cam2, the
promotion residual) and cam4's driveway cell (97a7849a, study-window replays)
joined back to its raw-dump track (join keyed on vehicle_track_id + segment
frame range, finalize-gap splits mirrored; 100% join on all windows) and
measured against the OPERATOR/BANK geometry mechanism 2 would use at runtime
(entry_gates.build_gates + applied-bank polylines — no GT anywhere in the
loop; Miovision appears only in the reconciliation footers). Script:
scratchpad `phase0_origin_grab.py` (session artifact, per the item-8 phase-0
precedent); per-claim features committed as
`evaluations/phase0_origin_grab_claims.json` (313 claims).

Features per claim, from birth geometry: `s_in` (signed px along the claimed
mouth's inward gate normal; >0 = born INSIDE the box beyond the mouth),
`lat` (offset along the gate axis), `d_mouth` (birth → mouth anchor),
`d_main` (birth → nearest main-road bank polyline), `brg_side`/`brg_main`
(birth velocity vs the claimed leg's road direction / the local main-road
tangent), nearest mouth anchor at birth.

## FM51 (claimed mouth = leg 3 "S", the Co Rd stem) — 228 claims

Internal contrast labels, no Miovision in the loop: `killed_through` (95
through-gate-rejected 3→2 = geometrically impossible = CERTAIN grabs),
`acc_left(3-1)` (54; Mio says ~3 genuine → ~94% grabs), `acc_right(3-2)`
(76; Mio ~67 → mostly genuine).

| group | n | s_in p10/50/90 | d_mouth p50 | d_main p50 | brg_side p50 |
|---|---|---|---|---|---|
| killed_through | 95 | 64 / 70 / 81 | 89 | 16 | 6° |
| acc_left(3-1) | 54 | 62 / 69 / 78 | 89 | 16 | 7° |
| acc_right(3-2) | 76 | −9 / 8 / 85 | **15** | **80** | 16° |

The two grab groups are ONE tight cluster: born ~70 px past the stem's gate
INSIDE the box, ~90 px from the mouth anchor, sitting ON the main-road
polyline (d_main p90 ≈ 20 px), moving along the main road. Genuine S-rights
are born AT the mouth (d_mouth p50 15) far off the main road (d_main p50 80).

**The proximity hypothesis is half-wrong, in a useful way:** the grabs'
births are NOT nearest the claimed anchor — 92/95 killed and 50/54 acc-left
births are nearest **leg 1 (W main-road mouth)**. The claim comes from the
TIER-0 POLYLINE match: in far-field compression the stem mouth sits ~80 px
from the W mouth and the 3→x path entry segments run along the main road, so
a main-road birth prefix matches a side-leg entry segment within the 30 px /
25° tier-0 gates. (Also explains why brg_side ≈ brg_main here: leg 3's road
direction at the mouth IS nearly the main-road axis.) Consequence: a veto on
"born beyond the claimed mouth" gates the CLAIM, and the natural fallback
(next candidate polyline / nearest anchor) points at the correct main-road
origin — the killed 3→2 throughs would become W-origin SB throughs instead
of dying, which is the SB −6.5% restoration path.

## cam4 (claimed mouth = leg 34, the Donut driveway) — 85 claims

Replay (pre-turn-merge) claim population for (34→33): 78 in window 0700 (+7
from a partial 1100 replay; 1600 pending — see caveats). Clean bimodal split
with an EMPTY [0,60) s_in band between clusters: 18 claims born at/outside
the driveway mouth moving inward (genuine class), 65 born mid-block on the
arterial (s_in 60–300+ or far-lateral, d_main p50 14 — ON the 33/35 axis),
reproducing the item-8 census shape (79% mid-block) on a second population.
Same anchor finding: 81% of claim births are nearest an ARTERIAL mouth
(52 leg33 / 17 leg35), not the claimed driveway.

## THE SIGNATURE (the deliverable — measured, not assumed)

`s_in` alone (the plan's "beyond the mouth" margin) is site-DEPENDENT: at
FM51 s_in>60 separates perfectly (98%/93% of grabs, 21% of mostly-genuine),
but at cam4 the arterial births straddle the driveway gate's extended line —
the gate axis doesn't extend along the crossing road. The site-INVARIANT
form is **"born on the crossing main road, away from the claimed mouth's
throat"**:

    GRAB iff  d_main < 25 px   AND   d_mouth > 60 px

where d_main = distance from birth to the nearest bank polyline of a
leg-pair NOT involving the claimed leg, and d_mouth = distance from birth to
the claimed mouth anchor. Both from operator/bank geometry; both length
constants, no time constants. Measured performance:

| population (internal label) | flagged |
|---|---|
| FM51 killed_through (certain grabs) | 89/95 (94%) |
| FM51 acc_left (~94% grabs per dev scorer) | 50/54 (93%) |
| FM51 acc_right (~88% genuine per dev scorer) | 18/76 (24%) |
| cam4 (34→33) replay claims | 73/85 (86%) |

Sensitivity: D_MAIN 20→30 moves FM51 acc_right capture 21%→38% (the knee is
at ~25 — beyond it the rule starts eating the genuine mouth-adjacent
cluster); M (d_mouth) is flat 40→70 at both sites (the clusters are far
apart — the constant is uncritical inside that window). s_in>60 as an
additional OR-arm adds only killed-through singletons; not needed.

Dev-scorer reconciliation (display only): gating the FM51 accepted claims by
the rule leaves side-leg ≈ 64 vs Miovision ~60–72 ✓. The 89 flagged
killed-throughs become main-road-origin candidates instead of kills (SB
restoration — phase 2 scores it end-to-end). cam4's end-to-end effect runs
through turn-merge and is a phase-2 measurement.

## Caveats recorded

- cam4 windows 1100/1600 replays were still running at write time (a
  stationary clutter track makes `_assign_origin` re-scan its trajectory
  every frame — quadratic; window 1100 alone ran >35 min vs 87 s for 0700).
  The signature above should be re-checked against them when they land, and
  that replay pathology is worth its own small fix note (unassigned
  never-moving tracks re-attempt origin per frame over the full trajectory).
- The FM51 acc_right flagged set (18) exceeds the dev scorer's net excess
  (+9): either far-field genuine misses offset grabs inside the accepted 76,
  or ~8 genuine would be over-gated. Phase 1 must route vetoed claims
  CONSERVATIVELY (fall to next candidate origin or origin-uncertain flag,
  never silent drop) so this ambiguity lands in the queue, not in the counts.
- acc_left(3-1) grabs move EASTWARD at birth (with the killed throughs) yet
  carry dest=W — they are short fragments whose destination came from the
  posterior, consistent with Mio S-left ≈ 3. Fixing the origin claim
  dissolves the cell; no separate dest mechanism needed.

## Phase-1 direction this licenses

Mechanism 2 as a CLAIM-TIME veto in `_assign_origin` tier 0 (and the anchor
tiers): a candidate origin leg whose gate/mouth the birth already lies
beyond — by the composite rule above — may not take the origin; scoring
falls through to the remaining candidates (the main-road path match), else
origin-uncertain → flag queue. Constants D_MAIN=25 px, M=60 px FROZEN from
this doc before the phase-2 blind sweep (FM51 replay + corridor: cam4
(34→33)→~live-111 watch, cam3 3.2 tripwire, no cam2 regression).
