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

---

## EXECUTION CHECKLIST (2026-07-28 — the steps, dependency-ordered;
[OP] = operator action, everything else is build work)

### Stage 1 — the standard into the machinery (~1-2 sessions)
1.1 Productize the 5/95 scorer: movement x class cells, per-camera
    compliance report served beside every export. GATE: re-baselined
    wall chart, one commit.
1.2 Acceptance-gate alignment: spot verdicts + approach rows adopt the
    +/-5-absolute grace; Sec-3-B matrix re-run. GATE: zero false-pass
    held AND the small-cell eternal-review dissolves (cam1/cam4 certify
    honestly).
1.3 Bin-edge audit: are window-edge bins (the 17:45-class worst rows)
    manufactured by binning/truncation? GATE: measured verdict; if
    real, fix + re-score.

### Stage 2 — the labor levers (~2-3 sessions)
2.1 Queue PRECISION measurement (the recall study inverted): noise rate
    per flag subtype on compliant cells. GATE: precision table.
2.2 Auto-resolution rules per subtype (zero-volume holes post-census,
    exact duplicates, cells already inside the +/-5 grace). PRE-DECLARED
    GATE: open cards drop to TENS per camera while BIG-failure recall
    stays >= 94.3% — recall may not drop.
2.3 Cards re-keyed to the 5/95 frame: one card = one failing cell-bin
    ("fix this bin"), not per-event floods. GATE: card counts + a
    scripted dry-run of the flow.

### Stage 3 — the star rating at ingest (~1-2 sessions)
3.1 Census-at-ingest service: the built blind censuses (stub share,
    flip share, coverage, offset bimodality) computed on the pass-1
    dump; thresholds anchored to the measured corpus (FM51-class high,
    cam5-class low). GATE: the rating separates the known sites
    correctly from their on-file census values.
3.2 Ingest UI: stars + plain-language guarantee statement per camera
    ("2-star: totals only — per-movement guarantee needs better
    footage"). Child-test language.

### Stage 4 — child-test UX passes (~3-5 sessions; parallelizable
with Stage 3/5)
4.1 Tally spot-count screen + live certification meter (independence
    preserved: no AI overlay while counting).
4.2 Review-card one-question redesign (giant guarded buttons,
    single-key answers, undo, stopping rule).
4.3 Cardinal wizard ("tap where north is") + auto-trims proposal with
    one-click accept.
4.4 Traffic-light export screen language pass.
    GATES: scripted dry-runs each; the REAL gate for all four is 6.4.

### Stage 5 — raw-compliance cycles (parallel; full gate discipline)
5.1 Phantom-small-cell treatment corridor-wide (the proven
    C-proper/geometric-guard family) — own plan + pre-declared gates.
5.2 [OP authorizes] Census-gated LEC2 activation cycle — own plan +
    budget per the standing rule.

### Stage 6 — footage + the acceptance test
6.1 Qualifying-footage spec into the runbook (resolution, height/angle,
    daylight — our 5-star analog + procurement guidance).
6.2 [OP] Procure one qualifying study (camera or video source). LONG
    LEAD — start now, everything else proceeds meanwhile.
6.3 Interim rehearsal: corridor post-review compliance with a
    simulated-perfect reviewer. GATE: >=99%.
6.4 [OP] Real-operator rehearsal on the new surfaces (also closes the
    F2/F3 first-human-use gap). GATE: rehearsal findings worked off.
6.5 THE ACCEPTANCE TEST: blind qualifying-footage study, worked queue,
    GT withheld until after export. GATE: 100% cell-bin 5/95 compliance
    on the deliverable. That is "we beat it."

Estimated build effort: ~8-13 focused sessions + the three [OP] moments
(5.2 authorization, 6.2 procurement, 6.4 rehearsal). First moves on
"go": 1.1 -> 1.2 -> 1.3 in one block.

---

## STAGE-1 RECORD (2026-07-28 — steps 1.1 core + 1.2 + 1.3 DONE)

- **1.3 bin-edge audit: REAL variance, no fix** (runs/3b_validation/
  rule595_edge_audit.json): shift-sweep gains <= 2.6 pts at INCONSISTENT
  optima (0..-90 s) — not a uniform clock artifact; the weak negative
  tendency (4/5 cams prefer -15..-30 s) is plausibly the box-crossing
  vs Mio-crossing definition gap, recorded; per-camera shift fitting
  against GT would be the Sec-0 overfit trap — refused.
- **1.2 gate re-shaped to the customer standard**
  (backend/services/spot_check.py): approach rows now bind by the 5/95
  TOLERANCE (±5/15-min-equivalent small, 5% large) with the Katz-CI
  statistical guard; the ±5%-band + 30-manual floor superseded (the
  absolute grace IS the small-cell floor). **Matrix re-run: ZERO
  false-pass — cam5 caught 5/5 seeds (was 4/5 under the old band)**;
  cam1/cam4 still certify honestly; cam3's scope refusal stands.
- **1.1 core: the rule is a service** (backend/services/rule595.py,
  4 boundary tests; the dev scorer refactored onto it — re-baseline
  numbers byte-identical: 65.3/46.7/77.3/76.4/70.9/70.3). OWED from
  1.1: movement x class cells (parse_by_class + fhwa buckets) and the
  export-side compliance report surface — next block.

**1.1 CLOSED (2026-07-29):** movement x class cells measured
(parse_by_class + FHWA->L/M/A; corridor class-cell compliance: cam1
68.1 / cam2 62.4 / cam4 72.8 / cam5 79.2% — class splitting moves more
cells under the +/-5 grace). Report surfaces scoped: BLIND sites get
the gate's 5/95 spot rows (live since 1.2 — tolerance_595 + binding +
plain-language note); DEV projects get the wall chart
(rule595_compliance.py, both cuts). The export-page compliance panel is
Stage-4 3e work by design (the child-language traffic-light pass), not
a 1.1 item. STAGE 1 COMPLETE.
