# PLAN — CAM5 NEAR-GAP CYCLE (operator-authorized 2026-07-29)

The 5.2 judgment's one live thread: at the customer bar (per-bin 5/95,
replayed-minutes basis) the frozen LEC2 bundle takes cam5 **63.0 →
76.1% compliance (fixed 51, broken 9, undercount DOWN 287)** and fails
ONLY G2 — six newly-created BIG bins. This cycle diagnoses which
component manufactures those six and whether a NARROWED bundle passes
cam5's full gate set. Count-changing mechanism work: authorized by the
operator; two-iteration budget (standing rule); cam5-only scope.

## The six bins (from lec2_595_judgment.json — the targets, by name)

| bin | cell | ours→ | ref | direction |
|---|---|---|---|---|
| 07:30 | N through | 312 | 344 | UNDER (−32) |
| 08:00 | N through | 261 | 284 | UNDER (−23) |
| 08:15 | N through | 229 | 263 | UNDER (−34) |
| 07:00 | S through | 205 | 173 | OVER (+32) |
| 11:00 | S through | 196 | 166 | OVER (+30) |
| 16:00 | S through | 375 | 321 | OVER (+54) |

All six are PROTECTED-THRU cells — the lane_echo iteration-1 band
failure, now visible per-bin. Suspects by mechanism: NB-thru UNDER =
the E survivor selection (keep-one) eating real fragment-fed thru
events (the load-bearing fragment feed the ±3-pt invariant guarded);
SB-thru OVER = C-proper's thru-reroute default and/or R's zero-event
chain resurrection adding thru events, and/or L's widened admissions.

## Phase 0 — component attribution (no mechanism change)

Re-run the cam5 judgment with LEAVE-ONE-OUT ablations of the frozen
bundle — E (survivor keep-one), L (the lpatch40 widened events vs
stock), C (the thru-reroute), R (resurrection) — constants untouched,
flags only. For each of the six bins: which arm(s) clear it, and what
each arm costs in fixed-bin mass. GATE 0: the attribution table — each
bin named to its component(s), evidence
runs/stage5_phantom/cam5_neargap_phase0.json.

## Iteration 1 — the narrowed bundle

Drop or guard the offending component(s) per phase 0 (candidate
shapes, chosen BY the table: R-off; C-thru-default-off (reroutes drop
instead of defaulting to thru); L-only-with-E; E-keep-one exempting
protected-thru cells). THE GATES (identical to the 5.2 pre-declared
set, cam5 rows):
  G1 compliance strictly improves vs base;
  G2 ZERO new BIG failing bins;
  G3 net flips positive, broken ≤ 20% of fixed;
  G4b undercount mass ≤ base × 1.05.
Retained-gain fraction (narrowed vs full bundle's +13.1) is REPORTED,
not gated — worth is the operator's call at apply time.

## Iteration 2 (the budget's last, only on a near-miss)

One refinement of the same shape. A second miss CLOSES the cycle with
the phase-0 table as the deliverable.

## Ship shape (NOT this cycle)

A gate-passing narrowed bundle ships CAM5-ONLY, census-gated (cam5's
same-cell echo composition qualifies it; the clean sites stand down),
via measure-then-apply through the real pass-2 with the operator's
explicit ✓ on the production numbers — per the deliverable-sweep
standing rule. FM51/cam3 are untouched by a cam5-only flag; their
tripwires re-run at apply time anyway.

## Basis (named)

Replayed-minutes (the sweep harness's own streams, BASE + lpatch40 DBs
already on disk), GT = Miovision per-minute, scorer =
rule595.score_cells. Never mixed with production numbers.

---

## CYCLE CLOSE (2026-07-29 — evidence runs/stage5_phantom/
cam5_neargap_phase0.json; harness scripts/cam5_neargap_phase0.py,
full-arm parity with the committed 5.2 judgment EXACT)

**Phase-0 attribution (decisive):**

| arm | 5/95 | fixed | broken | new BIG | targets cleared |
|---|---|---|---|---|---|
| full bundle | 76.1 | 51 | 9 | 6 | 0/6 |
| E_off | 62.7 | 9 | 9 | 12 | 3/6 |
| L_off | 71.5 | 39 | 12 | 15 | 2/6 |
| C_off | 70.1 | 33 | 10 | 7 | 0/6 |
| **R_off** | **76.8** | **52** | **8** | **3** | 3/6 |
| it1 R_off+E-keep-fulls | 76.8 | 52 | 8 | 3 | 3/6 (null delta) |
| it2 R_off+E-max-concurrency | 74.5 | 44 | 7 | 4 | 2/6 FAIL |

- **R is pure negative at cam5 under the customer bar**: it
  manufactures ALL THREE SB-thru over-bins (07:00 205→181, 11:00
  196→176, 16:00 375→340 — all clear with R off) and R_off STRICTLY
  DOMINATES the shipped bundle (compliance up, broken down, new-BIG
  halved). Recorded against any future LEC2 revival: resurrection does
  not belong in it.
- **The three NB-thru AM bins are E's fragment-chain over-collapse**:
  keep-one eats real vehicles whose fragments were direction-gate-
  chained with a neighbor's at AM density. Both constant-free
  narrowings failed measured: keep-per-full-member = NULL (the eaten
  events sit on ≤1-full chains); keep-max-temporal-concurrency = WORSE
  (74.5, re-admits collateral) — one-vehicle echo fragments and
  two-vehicle follower fragments are temporally disjoint alike, so
  concurrency does not separate them. This is the cam4 STAT-follower
  class at lower intensity, and the image-space discriminator families
  for it are already measured dead (×3).

**VERDICT: NOTHING SHIPS — G2 unmet by every arm; the two-iteration
budget is spent; the cycle CLOSES.** Standing record: the best known
cam5 configuration is R_off at 76.8% (+13.8 over base) with 3 new BIG
bins — a strictly better bundle than the one already retired, still
failing the customer bar. The residual mechanism (fragment-chain
follower over-collapse at peak density) joins the source-resolution
wall family; the honest route to cam5's thru bins remains qualifying
footage (Stage 6). Whether the R_off partial ever justifies a
relaxed-bar apply is an operator bar decision, explicitly not a
default — same precedent as the LEC2 sweep authorization.
