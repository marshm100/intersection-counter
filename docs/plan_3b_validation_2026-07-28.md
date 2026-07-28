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

---

## PHASE-0 FINDINGS (2026-07-28 — evidence runs/3b_validation/phase0_matrix.json;
harness scripts/gate3b_phase0.py; 30-min simulated-perfect spot counts x 5 seeds)

The spot-layer matrix names phase 1 precisely:

1. **cam5 FALSE-PASSES at 1/5 seeds** — the dangerous cell is real: three
   lucky 30-min windows certify a GT-FAIL camera (total 7.2, EB 16.1 /
   NB 17.3). The mechanism is measured in the same row: the false-pass
   seed's windows carry a **-18.5% EB approach error inside a passing
   TOTAL** (and other seeds see EB -23..-35% while totals hover in the
   passable range). Per-approach blindness (phase-1 candidate c) IS the
   false-pass mechanism -> the spot verdict must gate approach rows, not
   just the total.
2. **cam3 blind-FAILS all seeds** (GT 3.2 peak-window PASS, the
   corridor's best camera): its 24-h run stratifies into 10 segments and
   the night windows fail at rel_err ~ -1.0 (system ~0 vs real GT
   volume). Not a gate defect - a CLAIM-SCOPE mismatch: the gate
   certifies ALL processed footage; the deliverable claims the study
   windows. Phase-1 candidate (new, d): segment stratification must be
   scoped to the DELIVERABLE's reporting windows (trims), with
   out-of-scope footage excluded from certification (and said so in the
   claim language).
3. **cam1/2/4 never certify** (review at every seed; GT passes all
   three). The eternal-review cell - phase 1 diagnoses per window
   whether CI width or marginal point error dominates (the JSON carries
   both), then fixes guidance (longer windows) or verdict semantics.

Still owed in phase 0: the FM51 retrospective (stock-era PM sag - does
stratification catch the historical false-pass?), and the
acceptance-layer composition (queue/consistency items) on a scratch DB
copy with simulated spot rows.

**Eternal-review DIAGNOSED (same day):** cam1/cam4 = pure CI-width (points
-4..+3%; 30-min windows at 850-1,400 vehicles spill the +/-10% CI once
any point offset spends budget) -> protocol fix: extend-to-certify (the
service already prints "extend to ~N"; simulate the operator following
it; runbook prescribes it). cam2 = genuine marginal point error
(-5..-11% net across windows/seeds) -> **the gate is CORRECTLY refusing
certification**: cam2's honest net is ~-8.8% even though its interval
MAE is 4.8. This exposes the CLAIM-BASIS split the claim doc must
reconcile: the spot gate certifies NET-window accuracy; the Sec-1b bar is
interval MAE. A camera can pass one and fail the other (cam2 does). For
cam2-class cameras the blind verdict is honestly "review + flag queue",
never "pass" - phase-2 claim language item (f).

---

## PHASE 1-2 VERDICT + THE CLAIM STRUCTURE (2026-07-28 — evidence
runs/3b_validation/{phase0_matrix,fm51_retrospective}.json; gate changes
shipped in backend/services/spot_check.py, 824 tests green)

**Shipped gate hardening:** (c) per-approach binding rows (CI wholly
outside +/-5% with >=30 manual demotes pass->review; first catch was
crossed N/S labels in our own 5-week-old test fixture); (d) trim-scoped
stratification (certification = the declared reporting windows; no
trims -> footage-wide, so cam3's night refusal is an honest refusal of
an over-broad claim, remedied by declaring trims); (e) extend-to-certify
protocol (the simulation follows the service's own guidance; cam1/cam4
certify honestly).

**Matrix after hardening (5 seeds):** cam5 false-pass caught 4/5 by
approach binding; residual 1/5 — and cam4 3/5 — are STRUCTURAL: their
net totals genuinely cancel to ~0 and a 9-18% approach error at
feasible spot volumes has a CI straddling the target. cam2 = correct
refusal (net -8.8% real). **FM51 retrospective: stratified certification
0/5 with the PM window failing by name 4/5 (the founding case caught
end-to-end); old single-window flow 0/20 under the hardened logic (the
historical false-pass needed the era's looser practice) — stratification's
distinct contribution is that the hardest segment is ALWAYS examined.**

**THE CLAIM STRUCTURE (what the product may say at a GT-free site):**
1. **Net-total accuracy (+/-5%) is spot-CERTIFIABLE** — stratified across
   the declared reporting windows, CI-disciplined, extend-to-certify,
   with per-approach tripwires that withhold certification when a
   sampled window can resolve an approach outside the band.
2. **The per-approach bar is NOT blind-certifiable by spot counts** — a
   measured structural limit (S2-honesty tradition): feasible manual
   windows cannot resolve a 9-18% approach error, and cancellation can
   zero the net while approaches fail. Per-approach assurance rides the
   FLAG QUEUE (S1/S4/S5 feeders + the new approach rows as opportunistic
   tripwires) and is a surveillance claim, not a certification.
3. **Scope is explicit**: certification covers the declared trims only;
   footage outside them is uncertified and the claim language says so.

**Residuals (named, not hidden):** acceptance-layer composition with
simulated spot rows (the composition logic is unit-tested;
end-to-end-with-simulation still owed); S1 threshold sweep vs the cam2
SB-thru miss (superseded in priority by the claim structure — the queue
surveils, S1 tuning is now an alarm-quality item, not a claim item).

**Acceptance-composition sim (the owed item — CLOSED 2026-07-28;
evidence runs/3b_validation/acceptance_sim.json, harness
scripts/gate3b_acceptance_sim.py):** full `acceptance()` composed on a
scratch copy with simulated-perfect stratified spot counts (seed 97,
extend-to-certify). **Zero false-ship: all five intersections compose
to overall=fail** — the gate is conservative end-to-end on the corridor
as it stands. FINDING for a future block: `reverse_balance` fails on
ALL five intersections — over peak-window claims the item is
universally red (real directional peaking, exactly the case its
docstring warns about), so it currently adds no discrimination and
solely determines several compositions. A peak-aware reverse-balance
(or trims-scoped applicability) is the named fix; measured change,
own block.
