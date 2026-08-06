# Plan — close the gap to "replaces Miovision" (2026-08-03)

**[PARTIALLY SUPERSEDED same day — operator directive: NO footage
upgrade exists. Phase 2 (procurement) is DEAD. Phases 0/1 survive.
The operating plan of record is `plan_no_footage_regrounding_2026-08-03.md`.]**

Written off the 2026-07-31/08-01 blind product test (all 5 Sunnyvale cams,
declared trims, product UI only, zero hand-holding). That test is the
ground truth about the PRODUCT, distinct from the pipeline: the pipeline's
curated best is 65.3/46.7/77.3/76.4/70.9 %-of-bins on the 5/95 customer
standard; the product run cold produced 57.4/–/64.1/73.8/67.1 and
overwrote better tables while doing it. The gap to "replace Miovision"
is therefore FOUR gaps, each with its own closure:

  G1. The product does not hold the accuracy campaign's judgment
      (dispositions live in docs, not the product) — NEW, from the test.
  G2. Raw compliance on current footage is at its measured walls
      (640×480; LEC2 + cam5 near-gap cycles closed negative) —
      qualifying footage is the ONLY remaining raw lever (runbook §0b).
  G3. Post-review ceilings: 97.6/99.4/100.0/98.8/95.9 — cam1/4/5 below
      the ≥99 interim bar, every residual footage-gated; queue misses
      5.7% of BIG failures on three NAMED walls.
  G4. The claim is unproven as a WORKFLOW: no operator has run
      site→queue→export unassisted; labor is unmeasured against the
      ~10× target; 6.5 blind study not yet run.

The customer bar (fixed): per movement cell per 15-min bin, ±5 veh at
ref≤100 / ≥95% at ref>100, on qualifying (5-star-class) footage,
daylight, backed by human QA. Deployable claim: 100% cell-bin
compliance POST-REVIEW at ~10× less labor than manual.

---

## Phase 0 — Restore & stabilize (days) [mixed]

0.1 [OP DECISION — PENDING] Roll production back to the curated tables
    (per-camera backups from the blind run exist: cam1 20260731_173136,
    cam3 20260801_093658, cam4/cam5 evening 07-31). Recommendation:
    RESTORE — production should hold the best-known state; the blind-run
    tables stay preserved in two_pass/ + rule595.json for reference.
0.2 Fix the schema-drift bug: pass2:'current' must fingerprint schema
    version (or any migration invalidates cached working DBs). Clears
    int2's Error card. Regression test: cached re-apply across a
    migration. (Bug evidence: screenshots/blindrun_int2_schema_error.)
0.3 Error-card language: child-test the failure surface ("This
    intersection needs a fresh count — a data upgrade made the saved
    result unusable. Reprocess to fix.") — same fact, operator words.

## Phase 1 — The product holds the judgment (1–2 weeks) [agent, gated]

The blind test's core lesson: uniform two-pass apply DESTROYED curated
accuracy (cam4 HOLD ignored, cam1 PM live-table ignored, cam3 re-detected
onto the ft basis against the 07-24 disposition). Encode the judgment:

1.1 Dispositions as product state: per camera-window, which table is
    authoritative (live vs two-pass) + the measured basis recorded.
    "Confirm & process" honors it; the card explains it in plain words.
1.2 The apply gate (the litmus made mechanical): before any table swap,
    the candidate must pass the BLIND guards vs the incumbent —
    conservation/volume flood check, reverse-balance applicability,
    star-rating echo composition. Regression signals → apply refused,
    card explains, operator can override on the record. No GT anywhere
    in the gate (prime directive).
1.3 Detection-basis governance: a camera's applied basis is pinned;
    detect-at-ingest on a NEW basis routes through the same apply gate
    (formalizes the ft2-rebaseline disposition — the cam3 −13.2
    regression was this exact failure).
1.4 GATE (pre-declared): re-run the 07-31 blind product test verbatim.
    PASS = product reproduces ≥ curated scores on every camera with
    zero hand-holding. This gate is the definition of G1 closed.

## Phase 2 — Qualifying footage (THE LONG POLE) [OP — start now]

2.1 [OP] 6.2 procurement per runbook §0b (1080p-class; five hard
    requirements each traced to a measured wall). Long lead — every
    week it slips, the finish slips a week. Star rating ★★★★★ is the
    automated acceptance check at ingest.
2.2 On arrival: ingest through the product AS-IS (post-Phase-1 build),
    blind. Measure raw 5/95 + ceilings on the new footage. Expectation
    on record: the 640×480 walls (cam1 far-field fragments, cam5
    formation/undercount family, cam4 phantom class) shrink materially;
    FM51 blind-generalization (3.0% MAE) says the stack transfers.

## Phase 3 — Review layer to post-review 100% (parallel w/ Phase 2 tail)

3.1 Close the three NAMED queue-recall gaps (the 5.7% of BIG failures
    not flagged): cam2 S3-blocked classes, cam4 SB-right high-confidence
    phantom, cam5 EB-right formation / NB-left. Target: 100% of BIG
    failures flagged (small-bin recall rides the ±5 grace).
3.2 [OP] The owed Stage-4 human pass: real tally counts, F2 accept on a
    camera that matters, clip judgment on ~20 real cards, language feel.
    MEASURE labor: minutes/camera-day from open-queue to export-green.
    The ~10× claim gets a number or gets revised.
3.3 GATE: 6.3 rehearsal re-run on qualifying footage — post-review
    ceiling ≥99% EVERY camera (today only cam2/cam3 clear it).

## Phase 4 — The acceptance test (6.5) — "we beat it"

Blind study on qualifying footage the system has never seen. Operator
runs site→calibrate→process→work queue→export with NO agent in the
loop. Simultaneously order the same footage from Miovision. Score both
against the reference count:
  PASS = 100% cell-bin compliance post-review, labor within the
  measured Phase-3 budget, turnaround + cost beside Miovision's.
Ship decision sits on this gate and nothing else.

## Scope decisions to name now [OP]

- Pedestrians/bikes: v2 scope excludes them; many Miovision TMC
  deliverables include them. If replacement requires peds, that is a
  NEW workstream to schedule — decide before promising replacement.
- Night: match Miovision's own exclusion (daylight guarantee only) —
  current trims already align.
- Throughput: 14 h footage ≈ 10.4 h detect on the iGPU. A 5-cam corridor
  is ~2–3 days serial. Name the production hardware plan (discrete GPU
  or parallel boxes) before the first paying study.

## Why this is winnable (evidence on file)

- cam1 vs independent hand count: −1.5/+2.2% net (the stack passes the
  TxDOT bar when detection holds).
- FM51 held-out blind: 3.0% MAE — the method generalizes to an unseen
  site without tuning.
- Post-review ceilings already 95.9–100% on 640×480 footage; the
  residuals are footage walls, and footage is purchasable.
- The review layer already machine-closes 83.4% of queue labor with
  recall byte-flat — the labor math is close to the 10× shape.

Sequencing truth: Phase 2 is the calendar. Phases 0–1 fit inside its
lead time; Phase 3 fits inside its tail. If procurement starts this
week, the 6.5 acceptance test is realistic within ~6–8 weeks.
