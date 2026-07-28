# PLAN — BEAT THE 5/95 STANDARD (operator directive, 2026-07-28)

Two directives, verbatim intent:
1. **The Miovision 5/95 rule is THE standard to beat** — per movement
   cell per 15-min bin: ref ≤ 100 → ±5 vehicles; ref > 100 → ≥95%.
   Same conditions Miovision attaches: qualifying footage, night /
   low-light / glare excluded.
2. **Minimize human reliance.** Where a human IS needed, the UI/UX must
   pass the CHILD TEST: one clear question, one obvious action,
   impossible to do wrong (guarded + undoable), visibly verifiable.

## What "beat it" means (the claim, precisely)

Miovision's ~100% is pipeline + their human-fix layer on 5-star video.
Ours is the same shape: **the DELIVERABLE (post-review) hits 100%
cell-bin compliance on qualifying footage**, with (a) raw-pipeline
compliance and (b) queue recall/precision as the two tracked
sub-metrics, and (c) radically less human labor per study than a
Miovision-style ops team. Dev scoring = `rule595_compliance.py` (the
customer scorer); interval-MAE demotes to a diagnostic.

## Measured baselines (2026-07-28, all on record)

| metric | state |
|---|---|
| raw cell-bin compliance | cam1 65.3 / cam2 46.7 / cam3 77.3 (daylight) / cam4 76.4 / cam5 70.9 / FM51 71.0 % |
| queue recall vs failures | 88.5% overall; **94.3% of BIG (≥20 veh)**; every missed BIG = an already-named wall |
| open-card workload | 123–1,740 flags/camera (impact-ordered, flood-controlled — still too many) |
| footage | corridor 640×480 oblique = NOT qualifying (the measured source-resolution wall = their 5-star precondition) |

## Workstream 1 — the standard into the machinery (first, cheap)

1. 5/95 becomes the reporting scorer everywhere a number is shown
   (per-camera compliance % + failing-cell list beside the TMC export).
2. The acceptance gate adopts the ±5-absolute grace: spot verdicts and
   per-approach rows judged by the 5/95 shape (also dissolves the
   small-cell CI-straddle problem measured in §3-B).
3. Extend the scorer to movement×class cells (L/M/A) — the standard
   says "any given classification"; class cells are small → ±5 grace
   dominates there.
4. Re-baseline everything once, one commit, the numbers table above
   becomes the wall chart.

## Workstream 2 — raw compliance (fewer failures to fix)

Priority by measured failure mass, each inheriting full gate discipline:
1. **Bin-edge audit (cheap, possible quick win):** several worst rows
   sit at window edges (17:45s) — box-crossing binning vs trim-edge
   truncation may be manufacturing failures. Measure, fix if real.
2. **Phantom small cells (> ±5):** the C-proper/geometric-guard family
   already proven at cam5; apply the same measured treatment to the
   WB-phantom class corridor-wide.
3. **Census-gated LEC2 activation** — NOW justified by the standard:
   its site class (FM51) passes clean (MAE 5.4→1.8); the census
   composition signals gate it per-site. Own plan exists in outline;
   needs its authorized cycle.
4. **The named walls** (cam2-EB splits, cam5 stubs/laterals/formation):
   substantially source-resolution-gated on current footage — attacked
   AFTER Workstream 4 delivers qualifying footage, not before (three
   mechanism families already measured dead at 640×480).

## Workstream 3 — autonomy + the child test (the UX directive)

The five human moments, each redesigned to ask less and ask simpler:

- **3a Queue precision + auto-resolution (the big labor lever):**
  measure flag precision (noise on compliant cells); auto-resolve
  decisively-evidenced classes (zero-volume holes post-census, exact
  duplicates, cells the 5/95 grace already forgives); group survivors
  into per-failing-cell-bin cards. TARGET: open cards per camera drop
  from hundreds to TENS, recall on BIG failures ≥98%.
- **3b Review cards:** one looping clip, ONE question ("one vehicle or
  two?", "did it turn left?"), giant buttons + single-key answers,
  undo everywhere, live progress + the stopping rule. The C-polish
  keyboard flow is the base; the child-test pass rewrites every card's
  language and guards.
- **3c Spot counting:** a dedicated tally screen — the system serves
  each stratified window, big per-movement +1 buttons (or arrow keys),
  a live certification meter ("keep counting… ✓ certified") from the
  extend-to-certify math. INDEPENDENCE PRESERVED: no AI overlay during
  counting. The ~850-vehicle CI floor is irreducible math; the UX makes
  it mindless instead of miserable.
- **3d Calibration:** auto-cal is review-first with F2/F3 shipped; add
  auto-trims proposal (from footage coverage → one-click accept) and a
  cardinal wizard ("tap where north is" against a map thumbnail — the
  FM51 mislabeled-cardinals audit failure is exactly a child-test
  failure today).
- **3e The final gate screen:** one traffic light per intersection-day
  + plain-language "what stands between you and export" (the
  acceptance items exist; they get the child-language pass).

## Workstream 4 — the footage standard (the precondition)

1. Write OUR qualifying-footage spec (resolution ≥1080p-class, camera
   height/angle envelope, daylight) into the runbook as the analog of
   Miovision's 5-star requirements + Scout guidance.
2. **The star rating is computable:** the blind census metrics already
   built (stub share, flip share, evidence coverage, offset bimodality)
   ARE a video-quality rating — run them AT INGEST and tell the
   operator, before processing, whether this footage supports the
   guarantee ("★★★★★ — guarantee applies" / "★★ — totals only").
   This is the single highest-leverage autonomy feature: the system
   refuses quietly-bad inputs instead of asking a human to diagnose
   them later.
3. Procurement guidance for the first qualifying-footage study — the
   acceptance test for "we beat it" (below) runs on that study.

## The acceptance test for "WE BEAT IT"

A qualifying-footage site, processed blind, queue worked by an operator
using the 3a–3e surfaces, scored against GT withheld until after
export: **100% cell-bin 5/95 compliance on the deliverable, at a human
labor budget an order of magnitude under a manual count.** Interim gate
on current footage: post-review compliance ≥99% on a corridor
dev-rehearsal with a simulated-perfect reviewer (measurable now), then
a real-operator rehearsal.

## Sequencing

W1 (scorer/gates, days) → 3a+3e (labor levers, measurable via card
counts + recall) → W4.2 (star rating at ingest — reuses built censuses)
→ 3b/3c/3d UX passes → W2.1/2.2 (cheap raw wins) → W4.3 procurement →
the qualifying-footage acceptance test, with W2.3/2.4 as authorized
cycles alongside. Every stage keeps the paid-for discipline: plan →
measure → pre-declared gate → ship-or-retire with numbers.
