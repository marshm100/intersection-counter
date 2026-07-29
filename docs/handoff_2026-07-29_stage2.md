# Handoff — 2026-07-29 Stage-2 block (the labor levers; STAGE 2 COMPLETE)

Everything on `claude/accuracy-impl-2026-05-27`, committed + pushed.
860 tests green (+14). Plan of record: `plan_595_standard_2026-07-28.md`
(now carries the STAGE-2 RECORD); block detail:
`plan_stage2_labor_levers_2026-07-29.md`. PRODUCTION project.db WAS
modified this block — deliberately, reversibly (below).

## What happened, in order

1. **2.1 queue precision** (the recall join inverted; join refactored
   to ONE shared function, recall re-run byte-identical): precision
   54.5–76.8% per camera — a third to half of the 4,370-flag workload
   sat on compliant bins or outside the claim windows. The decisive
   cut: BIG failing bins caught ONLY by ≤5-event clusters (cam2 22 /
   cam5 20 / cam4 8) — the plan's own R1 family (resolve small
   clusters wholesale) was KILLED by its pre-declared gate before
   shipping. Evidence: runs/stage2_labor/precision.json.
2. **2.2 auto-resolution shipped** (backend/services/queue_autoresolve
   .py; ablation runs/stage2_labor/ablation.json): frozen blind config
   **R5 scope (trims-else-daylight) + R-CAP K=1 (keep the most-severe
   exemplar per cell-bin cluster — recall-invariant BY CONSTRUCTION) +
   R2 holes ≤5 events/day**. Rejected on the grid: T0=15 (cam5 −2.2
   recall), K=3 (2–5× survivors, zero card benefit), R4 det-bands
   (flat precision, subsumed by the cap), R3 duplicates (measured
   zero-mass). New status `auto_resolved` = MACHINE state: cleared +
   re-derived on every rebuild, excluded from worklist/recall credit,
   summary-visible, reopenable; operator terminal statuses persist.
3. **Production sweep applied** (in-place, S5-preserving — 9/10 gap
   flags stay open; full backup runs/stage2_labor/review_flags_backup_
   2026-07-29.json; revert: `python scripts/rule595_queue_sweep.py
   --revert`): **4,370 → 726 open flags (83.4% machine-closed);
   recall 88.5% / BIG 94.3% BYTE-FLAT per camera (G2 PASS exactly).**
4. **2.3 re-key**: one card = one suspect cell-bin (`bin|cam|cell|
   HH:MM`), exemplar impact = the bin's flagged-event mass → the
   worklist now leads with the real walls by name (cam2 head: EB-thru
   hole 339 → WB-left 70 → S5 WB 50 → EB-thru 16:30 bin, 40 events —
   the known occlusion-split wall). Scripted dry-run green; rebuilds
   emit the new shape natively.
5. **The honest partial (pre-registered before the ablation ran):**
   "tens per camera" G1 = 2/5. cam1 97 / cam4 55 PASS; cam2 236 /
   cam3 209 / cam5 129 bottom out at their flagged-bin floors — cam2's
   169 GT-failing bins alone exceed 99. That residual is RAW COMPLIANCE
   (Stage-5 walls, Stage-6 footage), not queue hygiene; queue work
   cannot shrink it without lying about recall.

## NEXT — Stage 3 (census-as-star-rating at ingest)

3.1 Census-at-ingest service: the built blind censuses (stub share,
    flip share, coverage, offset bimodality) on the pass-1 dump;
    thresholds anchored to the measured corpus (FM51-class high,
    cam5-class low). GATE: the rating separates the known sites from
    their on-file census values.
3.2 Ingest UI: stars + plain-language guarantee statement per camera.
    Child-test language.

## The operator's court (unchanged, one URGENT)

- **6.2 QUALIFYING FOOTAGE procurement — the LONG-LEAD item; start
  now** (the acceptance test and the cam2/cam5 walls wait on it).
- 5.2 census-gated LEC2 activation authorization (when wanted).
- Studio dry-run (F2/F3 still await first human use) — could now
  double as the first look at the new bin-card worklist.
- Trims declaration for cams 3/4/5 (only int1/int2 have declared
  trims; R5's daylight fallback covers cam3 meanwhile — declaring
  trims would tighten its claim scope AND its queue further).

## Standing discipline (unchanged)

Plan doc before mechanism; measured ablations; pre-declared gates;
negatives are deliverables; name the scoring basis; FM51 held-out
(NOTE: FM51 has no feeder-era queue, so the auto-resolution constants
are corridor-derived — the Stage-6 acceptance test is their true
held-out validation, stated in the plan doc); detached jobs via
Start-Process + Monitor; kill port-5000 owners before serving; replay
scratch in data/projects/<proj>/_replay_scratch, never %TEMP%.
