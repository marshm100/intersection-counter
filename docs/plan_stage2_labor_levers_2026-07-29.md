# PLAN — STAGE 2: THE LABOR LEVERS (2026-07-29)

Parent: `plan_595_standard_2026-07-28.md` execution checklist Stage 2
(2.1 queue precision → 2.2 auto-resolution → 2.3 cards re-keyed to the
5/95 frame). Written BEFORE any mechanism, gates pre-declared here
before any ablation number exists.

Objective: the deliverable claim is POST-REVIEW 100% cell-bin
compliance; the review layer's recall is measured (88.5% / 94.3% BIG).
The remaining problem is LABOR: 123–1,740 open flags per camera. This
block measures the queue's precision, auto-resolves the noise under a
hard recall gate, and re-keys the worklist to the customer standard's
own unit ("fix this bin").

## Measured baseline (2026-07-29 recon, production queue as-is)

| camera | open flags | batch cards | failing bins | BIG fails | recall % | BIG recall % |
|---|---|---|---|---|---|---|
| cam1 | 1,115 | 18 | 58 | 18 | 93.1 | 100.0 |
| cam2 | 1,140 | 27 | 169 | 45 | 93.5 | 93.3 |
| cam3 | 1,740 | 13 | 96 (daylight) | 54 | 100.0 | 100.0 |
| cam4 | 123 | 7 | 38 | 13 | 63.2 | 84.6 |
| cam5 | 252 | 21 | 93 | 27 | 75.3 | 85.2 |
| total | 4,370 | 86 | 454 | 157 | 88.5 | 94.3 |

Queue composition: low_det_conf 3,189 / ambiguous_dest 1,134 /
ambiguous_origin 37 / bank_coverage_hole 6 / merge_borderline 4.
Recon facts that shape the rules:
- NO event is flagged twice; NO open flag sits on a rejected/edited
  event (the feeder emits one flag per event and skips worked ones) —
  the "exact duplicates" family is expected ~zero-mass; verify + retire
  with the number (negatives are deliverables).
- All 10 suspected_gap flags are CELL-scoped (no interval, no event) —
  in the recall join each matches EVERY bin of its cell; part of the
  measured recall is that breadth (caveat already on record).
- Trims are declared only for intersections 1 and 2. cams 3/4/5 have
  none — the scope rule below uses the dev scoring windows for the
  ablation and declared-trims∪daylight in the wired version (the
  missing declarations are an operator-court item, raised again).
- cam3 has 186 open flags outside the daylight envelope (guarantee
  excludes night by the customer's own conditions).
- cam1/cam4/cam5 event flags: every one lies INSIDE the scoring
  windows by construction (events only exist where processed); cam3 is
  the only camera with out-of-scope mass.

## Scoring bases (named, per the standing rule)

- 2.1/2.2 measurement basis: production project.db 97a7849a, open
  queue AS-IS on 2026-07-29 (identical to the 2026-07-28 recall run —
  nothing has touched it; statuses all literally 'open'). GT = Miovision
  per-minute XML over the dev scoring windows (CORRIDOR dict; cam3
  daylight cut). This is a DEV measurement — GT names which bins fail.
- The RULES themselves are blind-computable only (§0 litmus): cluster
  sizes, confidence bands, declared trims, daylight clock, census
  volumes — never GT, never per-site fitted thresholds. Constants
  frozen corridor-wide from the ablation; FM51 has no feeder-era queue
  (predates the feeders) so it cannot participate — the true held-out
  validation of the rule set is the Stage-6 acceptance test, stated
  honestly here.

## 2.1 — Queue PRECISION (the recall join inverted)

For every OPEN flag, its match FOOTPRINT = the set of scored (bin,
cell) pairs it matches under the SAME join as the recall script (the
join is refactored to one shared function so recall and precision
cannot drift; parity gate below). Classification per flag:
- TP: footprint contains ≥1 FAILING bin (sub-cut: BIG-TP if |Δ|≥20).
- NOISE: footprint non-empty, all matched bins COMPLIANT.
- OUT_OF_SCOPE: footprint empty (bin outside the scored windows / no
  scored cell) — labor with zero compliance relevance for the claim.

Reported per camera × subtype: n, TP, NOISE, OOS, precision =
TP/(TP+NOISE); event-linked vs cell-scoped (breadth) flags listed
separately (a cell-scoped flag's TP is nearly guaranteed — naming its
breadth is the honest column, not folding it in).

Rule-feeding cuts (the evidence 2.2's thresholds come from):
1. (cell,bin) cluster-size distribution of event flags × compliance of
   the bin (share of flags in clusters ≤T sitting on compliant bins,
   T = 1..8).
2. det-conf band precision for low_det_conf (bands [0.30,0.35), [0.25,
   0.30), <0.25) and margin bands for ambiguous_dest.
3. Night/out-of-window mass per camera.
4. Per caught BIG failure: how many matching open flags, which
   subtypes — the "smallest set whose removal un-catches it" view that
   says how close the recall gate is to the edge.

GATE 2.1 (pre-declared): the precision table exists as
`runs/stage2_labor/precision.json` + printed table; AND the join
refactor re-runs the recall script byte-identical to
`runs/3b_validation/rule595_queue_recall.json` (parity proof — the
queue is untouched, so any diff is a refactor bug).

## 2.2 — Auto-resolution rules (pre-declared families + grids)

Rule families, applied in this order (marginal contribution reported
for each; order matters and is part of the frozen spec):

- **R5 scope**: event flags whose bin lies outside the claim scope →
  auto-resolve "out of claimed windows". Ablation scope = the dev
  scoring windows; wired scope = declared trims where present, else
  the daylight envelope (06:00–20:00, the guarantee's night
  exclusion). Failing bins are inside the scope by construction, so R5
  CANNOT reduce recall. Expected mass: cam3 ~186+.
- **R1 grace-immaterial clusters**: event flags in (cell,bin) clusters
  of size ≤ T_grace. Rationale: resolving ≤5 flags moves a bin ≤5 veh
  — inside the ±5 absolute grace (and the >100-ref branch's tolerance
  is >5 by construction), so the cluster alone cannot flip a verdict.
  Exception (pre-declared): clusters in a cell named by an open
  suspected_gap flag are KEPT — they corroborate a live suspicion.
  Grid: T_grace ∈ {0(off), 2, 3, 5}. Honest cost reported (not gated):
  failing bins at 5<|Δ|<20 whose entire flag match is auto-resolved =
  forfeited marginal fixes.
- **R4 confidence band**: low_det_conf flags with det_conf ≥ T_det
  auto-resolve (equivalently: the emission floor tightens). This is a
  GLOBAL constant retune of a global failure-mode floor — blind-legal;
  justified only if 2.1 shows the band's precision is not better than
  the subtype's average. Grid: T_det ∈ {0.35(off), 0.30, 0.25}.
  Same-shaped option for ambiguous_dest margin held in reserve —
  applied only if the band cut shows structure.
- **R2 zero-volume holes post-census**: bank_coverage_hole flags with
  impact (live fallback events over the processed day) ≤ T0 →
  auto-resolve "hole is real but grace-immaterial" (≤5/day cannot
  exceed ±5 in any bin even if every one is misattributed). Grid:
  T0 ∈ {0(off), 5, 15}. Expected mass ~2–4 flags (cam2 NB-right 5,
  cam5 NB-right 11); kept for principle — the checklist names it.
  The BIG holes (cam2 EB-thru 339, WB-left 70; cam5 WB-left 81,
  EB-thru 54) are real walls and are NEVER auto-resolved.
- **R3 exact duplicates**: collapse duplicate flags on one event /
  flags on rejected-or-edited events. Recon says zero mass; verify in
  2.1, report the zero, retire as no-op.

**THE HARD GATE (pre-declared NOW, before any ablation number):**
- G1 labor: per-camera surviving open flags ≤ 99 (tens), every camera.
- G2 recall: overall BIG recall ≥ 94.3% AND no per-camera BIG-recall
  drop below its baseline row (100 / 93.3 / 100 / 84.6 / 85.2). The
  recall re-join uses the surviving open set through the SAME shared
  join. Auto-resolution only removes flags, so recall can only fall —
  G2 says it may not.
- Overall (non-BIG) recall is a reported diagnostic, not a gate — the
  checklist binds BIG.
- If G1+G2 are jointly unachievable on the grid: ship the best
  gate-passing subset, report the frontier (max labor reduction at
  zero BIG drop), and put the trade to the operator. Ship-or-retire
  with numbers; no silent relaxation.

Ablation protocol: read-only on the production DB (simulate survivors
in memory, re-join, tabulate). NOTHING rebuilds the production queue —
a manual rebuild would destroy the 4 S5 merge_borderline flags (they
only regenerate on pass-2 runs) and corrupt the baseline comparison.
Evidence → `runs/stage2_labor/ablation.json`.

Wiring design (ships only if the gate passes):
- New status `auto_resolved` (machine state): set by the rules with
  the rule id + evidence in evidence_json and a plain-language reason.
  Cleared and re-derived on every rebuild alongside 'open' (self-
  healing: if conditions change, the flag comes back open); NOT in the
  feeder's worked-event exclusion (unlike operator statuses, which
  persist). Excluded from the worklist; counted in flag_summary as its
  own bucket so the operator SEES "the machine closed N — here's why"
  (child-test visibility) and can reopen any of them (undoable; an
  operator terminal action then persists).
- Application to the CURRENT production queue: an idempotent in-place
  sweep (UPDATE matching open flags → auto_resolved) — never a
  rebuild, so S5 survives and the operator's queue drops immediately.
  Full review_flags backup (JSON dump) taken first; a revert script
  flips auto_resolved → open.
- The same rule functions run inside rebuild_flags for all future
  queues. Unit tests on scratch DBs; the production sweep's
  before/after per-camera table is the shipped evidence.

GATE 2.2 = THE HARD GATE above, evidenced by the ablation table + the
post-sweep re-join on the production DB.

## 2.3 — Cards re-keyed to the 5/95 frame

One card = one suspect CELL-BIN ("fix this bin"), events grouped under
it. Blind at a real site: "suspect" = what the feeders flag; the
GT-failing-bin recall/precision of exactly that suspicion is what 2.1
measured. Mechanics:
- Surviving event flags get batch_key = `bin|{cam}|{approach}-{mv}|
  {HH:MM}` (wall-clock bin start via the camera's rec offset — the
  same conversion the join uses). Card impact = the bin's flag-cluster
  mass (suspected max delta), replacing today's flat 1.0-per-flag, so
  the worklist orders by how much a bin can move.
- Cell-scoped gap flags (S1/S4/S5) keep their own cards (they are
  already one-card-per-suspicion; their reasons already name the cell).
- Depends on 2.2 shipping first: re-keying today's 4,370 flags would
  explode into hundreds of bin cards; after auto-resolution the
  surviving mass yields tens.
- The child-language card REWRITE (one question, giant buttons) is
  Stage 4.2 by design — 2.3 delivers the key, the grouping, and the
  ordering.

GATE 2.3 (pre-declared): per-camera card counts ≤ 99 (expect tens) on
the re-keyed queue, AND a scripted dry-run of the operator flow
(list → next → batch-resolve → undo → summary) green against a scratch
copy running the new keys end-to-end.

## 2.1 FINDINGS + PRE-ABLATION AMENDMENT (2026-07-29 — written BEFORE
the 2.2 ablation runs; evidence runs/stage2_labor/precision.json)

Join refactor parity: recall re-run byte-IDENTICAL. GATE 2.1 MET.

| camera | open | TP | noise | OOS | precision | clusters | broad |
|---|---|---|---|---|---|---|---|
| cam1 | 1,115 | 551 | 282 | 282 | 66.1% | 96 | 1 |
| cam2 | 1,140 | 875 | 265 | 0 | 76.8% | 233 | 4 |
| cam3 | 1,740 | 1,012 | 542 | 186 | 65.1% | 208 | 1 |
| cam4 | 123 | 67 | 56 | 0 | 54.5% | 55 | 0 |
| cam5 | 252 | 150 | 102 | 0 | 59.5% | 125 | 4 |

(clusters = distinct flagged (cell,bin) pairs among in-scope event
flags; broad = cell-scoped gap flags.)

1. **R1 (resolve whole small clusters) is KILLED by its own gate,
   pre-ship**: BIG failing bins caught ONLY by a ≤5-event cluster —
   cam2 22, cam5 20, cam4 8, cam3 2. Wholesale small-cluster
   resolution would collapse BIG recall (cam5 would lose up to 20 of
   its 23 caught BIGs). Negative on record; R1 does not ship.
2. **Replacement — R-CAP (recall-invariant by construction):** every
   (cell,bin) cluster keeps its K most-severe members (severity from
   emit-time evidence; ties → lowest flag_id); the excess auto-resolve
   as "redundant — this bin is already surfaced; K exemplars kept".
   ≥1 member survives per cluster and broad flags are untouched, so
   every caught bin STAYS caught — recall provably cannot move. The
   cluster is computed BLIND (flag approach/movement + event wall-bin
   via rec offset), never from GT footprints. Grid: K ∈ {1, 3}.
3. **R4 DROPPED as subsumed**: band precision is flat (≈ subtype
   average everywhere; cam3's lowest band is its most precise at
   74.6%), and under R-CAP at K=1 every non-exemplar is already
   resolved — R4 could only touch exemplars, which is exactly what G2
   forbids. The band table ships as a diagnostic.
4. **R5 refined to a TIME-ONLY test**: outside declared trims (int1/
   int2) or outside daylight 06:00–20:00 where no trims are declared
   (cam3). NOT footprint-emptiness — a scored-cell mismatch is a GT
   artifact and means nothing blind. cam1's 282 OOS are its 11:00–13:00
   processed-but-unclaimed window; cam3's 186 are night.
5. **R3 CONFIRMED zero-mass**: 0 duplicate-event flags, 0 flags on
   worked events, all cameras. Retired as a no-op (deliverable: this
   number).
6. **R2 stands** with T0 grid {0, 5, 15}; per-config recall delta
   measured — any BIG-recall drop fails that config (G2 binds; the
   cell-broad hole flags can be a failing bin's only matcher, so this
   is not assumed safe).

**Pre-registered prediction (before the ablation runs):** survivors ≈
clusters + broad + in-window cell-mismatch flags → cam1 ~97 / cam2
~237 / cam3 ~209+ / cam4 ~55 / cam5 ~129 at K=1, with recall and BIG
recall EXACTLY at baseline. G1 (≤99) is predicted to PASS at cam1/cam4,
FAIL at cam2/cam3/cam5 — the per-camera floor is the flagged-bin count
itself, and at cam2 the 169 GT-failing bins alone exceed 99. If the
ablation confirms, the pre-declared fallback applies: ship the
gate-passing rule set (it is strictly labor-positive at zero recall
cost), report the frontier, and put the residual to the operator — the
honest statement is that cam2/cam3/cam5's card floors are their raw
5/95 failure counts, which is Stage-5 (raw compliance) and Stage-6
(qualifying footage) work, not resolvable by queue hygiene.

## Sequencing + commits

1. Join refactor + parity re-run (recall byte-identical) — part of the
   2.1 commit.
2. 2.1 precision script + evidence + findings appended here. COMMIT
   "Step 2.1 — queue precision table (join parity held)".
3. 2.2 ablation offline → frozen constants appended here → wiring +
   tests → backup → production sweep → post-sweep re-join. COMMIT
   "Step 2.2 — auto-resolution under the hard gate" with the numbers.
4. 2.3 re-key + dry-run + card table. COMMIT "Step 2.3 — cards re-keyed
   to failing cell-bins".
Each step's verdict (including any FAIL) is appended to this doc;
MASTER_PLAN §1c stage line updates at block close.
