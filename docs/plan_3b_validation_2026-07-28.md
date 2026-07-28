# Plan — §3-B BLIND-GATE VALIDATION (2026-07-28)

The claim machinery. Every accuracy number this project ships blind rests
on the §3-B acceptance gate (spot-count + flag queue) TRACKING the
dev-validation metric (AVG|err| ≤ 5%/15-min, §1b) — "we validate that
the gate tracks this metric, then trust it blind." That validation has
never been run end-to-end. It is the last §3 item between the corridor's
numbers and a defensible blind-deployment claim (handoff wall C; spike
gate 2026-07-28 routed here).

## What exists (inventoried 2026-07-28 — more than the wall implied)

- `spot_check.propose_windows` + SEG_* stratification (gap >20 min
  splits blocks; ≤3 h segments; ≤4/block) — the §5 "hardest conditions"
  rule is BUILT, citing the FM51 AM-pass/PM-bad case verbatim.
- `spot_check.spot_result` verdicts (Katz CI; pass needs point ≤5% AND
  CI within 10%; wide CI can only "review", never pass by vagueness).
- `spot_check.acceptance` — composed verdict: spot verdicts ×
  corridor-consistency × reverse-balance → ship/review/fail.
- S1 interval_corridor (bin-level corridor mismatch; thresholds
  CORRIDOR_WARN/MIN_LINK_VOLUME) — the known miss: cam2 SB-thru −15%
  under threshold. S2 interval_anomaly — smooth-sag limit DOCUMENTED as
  delegated to the spot layer ("we do not fabricate a catch we cannot
  make").

## The validation (dev-only study; production project.db basis, named)

**Simulated operator = perfect counter**: for any proposed spot window W,
the "manual" count is GT (Miovision per-minute) restricted to W. This
isolates the GATE's design — window selection, statistics, composition —
from operator skill, which is the thing being certified.

### Phase 0 — the confusion matrix

For every intersection-day with GT (corridor cams 1–5 + FM51):
1. Run `propose_windows` (stratified, seeded) → the blind window set.
2. Simulate each spot count (ours-from-production-events vs GT per W) →
   `spot_result` verdicts.
3. Compose `acceptance` (with the real flag-queue/consistency state).
4. GT verdict per camera = the §1b per-approach/interval table (all on
   file: cam1 4.0, cam2 4.8 production, cam3 3.2, cam4 4.7, cam5 7.2,
   FM51 3.0 — plus their per-approach FAIL cells).
5. Tabulate blind vs GT. The DANGEROUS cell is FALSE-PASS (gate ships a
   camera GT fails). Known candidates it must catch: FM51-PM (the
   stratification's raison d'être — this is its first end-to-end test),
   cam5 (7.2 total, EB/NB walls), cam2's EB 17.2.
   The ANNOYANCE cell is false-fail/eternal-review on passing cameras.

### Phase 1 — fix what the matrix names (each fix blind-computable)

Anticipated from the record (confirm, then fix): (a) S1 threshold vs the
cam2 SB-thru −15% miss — a corridor-link threshold sweep against GT
labels, alarm precision/recall reported, constants frozen; (b) any
stratification hole phase 0 exposes (e.g. windows sampled inside a
segment can still miss its hardest 15 min — candidate: bias the window
INSIDE each segment toward the run's own lowest detection-confidence
interval, which is blind); (c) per-approach blindness: the spot TOTAL
can pass while an approach fails (cancellation, §1b) — candidate: the
gate's spot verdict gains per-approach rows with wider CI bars (small
cells), review-not-fail semantics.

### Phase 2 — re-run the matrix at frozen constants + the claim doc

Zero false-PASS across corridor + FM51, alarm load acceptable (queues in
the tens, not hundreds), then: runbook §update writing the OPERATOR
procedure ("what you must count, when the tool may be trusted, what a
review verdict obligates"), and the blind-deployment claim language the
product is allowed to make. Negatives are deliverables: any GT-fail the
gate structurally cannot catch gets DOCUMENTED as a known limit (the
S2 precedent), never papered over.

## Scoring bases

Production project.db tables (live-legacy + applied two-pass mixture —
the shipping config), GT = Miovision XML / manual sheets. Replay bases
appear nowhere: the gate certifies what ships.

## Costs

No detection, no replays, no training. SQL + XML + the existing services;
CPU-minutes per camera. The whole study is offline-recomputable.
