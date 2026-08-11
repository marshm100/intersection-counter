# Pipeline-V2 Week-1 verdict (2026-08-04)

> **AMENDMENT 2026-08-11 — read `plan_v2_confound_split_2026-08-11.md`
> before trusting any per-window number in this file or in the G-A3 block.**
> The control-vs-treatment comparison this campaign used ("base dump, flags
> OFF" vs "v2c dump, flags ON") moved FOUR variables at once. The fourth was
> never declared: extension lifts blind gate coverage past
> `EVIDENCE_ACTIVATION_COVERAGE = 0.45`, so the treatment arm ALSO switched
> on the gate+posterior attribution pair at every camera that had been
> standing down. All 12 corridor windows were re-run with the pair forced
> off. Headline: **cam3's +8.5 — the largest win in the campaign, applied to
> production — is extension -3.0 and evidence pair +11.5.** Extension is
> positive only at cam2 and cam5 study_1600. Directional conclusions and the
> shipping decisions survive; the attributions do not. The 2026-08-05 stack
> and demotion results in this file were measured at cam2, whose activation
> state never varied, so they are NOT affected.

## DAY-7 (2026-08-05) — DEMOTION MECHANISM PASSES BLIND HELD-OUTS; FIRST 5/95 GAINS

**Census-ratio demotion, final form (all in-chain, V2_DEMOTION flag,
default OFF; 896 tests green):** entangled-origin condition (own-fulls
majority-read rival lanes: cam2 W = .96-.99, clean origins .00-.47,
threshold .5) x census-ratio flood flag x DERIVED DOSE (clean-origins'
direct/strict ratio = the window's recall-inflation; demote only the
excess) x supports-only sampled allocation (deterministic per-track
hash; scorer-admitted pools re-elect the flood — bank-paths-into-dest
pool per the rescue_supports precedent).

RESULTS (dev + BOTH blind held-outs): 5/95 53.4->54.4, 42.9->45.7,
44.0->46.8 — the FIRST bin-level gains of the campaign, zero
non-target-cell movement, zero regressions. EB-right |err| 142->55,
65->7, 85->118 (PM overshoot = the honest blemish); SB-thru 102->15,
7->65 (swap), 181->22. Bug ledger: tid was a function param not a
vehicle key (degenerate hash silently full-dosed — caught by
byte-identical-outcome comparison; the accidental experiment ALSO
proved allocation robustness).

CAM1 TRANSFER VERDICT (same day): treatment == control byte-identical on
both windows — two findings: (a) the demotion hook covers only the
JOINT-SCORER path; cam1 attribution rides the fallback chain -> inert by
code-path (acceptable scope: the mechanism is cam2-class), and (b) THE
CONFUSION MEASURE SATURATES on oblique geometry (cam1: origins 22/23/25
read 0.73-1.0 — the ceiling, not selectivity; cam2's true signature =
one origin 0.98 vs median 0.08). CONTRAST GUARD added (demotion needs
lower-median other-origin confusion < 0.25): cam2 passes untouched
(0.079-0.119, verified by arithmetic against all 3 windows' recorded
values), cam1 becomes a PRINCIPLED STAND-DOWN (0.73/0.78). The guard
protects any future fallback-path hook from saturated mis-fire.

STACK VERDICT (extension + demotion, same day): held-out 5/95
42.9->50.9 (+8.0 — best midday EVER) and 44.0->46.7 (+2.7); dev
53.4->51.3 (-2.1). INTERACTION BUG FOUND: extension COMPLETES the
flood's false-origin tracks into legitimate-looking fulls -> inflates
the flooded cell's strict census -> dose under-fires or un-flags
(dev 28->29 un-flagged; held-out doses 0.40-0.48 vs 0.73 standalone).
FIX SPEC (next iteration): demotion's census/confusion/dose must be
computed from the UNEXTENDED base dump (extension cannot poison it)
while the replay runs on the extended dump — one patch in run_pass2
(base-variant census rows for v2c_ variants). Then re-measure the
stack on all three windows.

**STACK v2 — BASE-CENSUS PATCH: ALL THREE WINDOWS CLEAR CONTROL (the
block's closing result).** 5/95: 53.4->54.9 dev, 42.9->50.0 and
44.0->47.5 blind. Doses restored (28->29: .77/.71/.85), NB-left AT
TRUTH (413/338/407 vs 411/450/420), recall cells all toward Mio.
Residuals for next block: EB-right overcount remainder (320 dev vs
demotion-standalone 222 — dose-vs-recall trade), SB-thru merge
interaction (UNDIAGNOSED), 60 s queue-order stitching, time-local
allocation sampling (bins upside).

**OPERATOR DECISIONS NOW ON THE TABLE:** (1) commit the campaign's
working tree (7 days: v2_* scripts, flag-gated chain changes, docs —
896 tests green, all flags default-OFF, production tables untouched);
(2) V2_DEMOTION promotion path (needs the apply-gate/dispositions
product work from plan_miovision_replacement Phase 1 before any
default-ON); (3) blind-run rollback decision STILL PENDING from
2026-08-01 (backups intact).

## DAY-5 ADDENDUM (2026-08-05) — B1 endpoint extension: half a win

- v2b (replacement tracker): association too weak — floods (30-32%);
  RETIRED. Lesson: BoT-SORT association quality is load-bearing.
- **v2c (ENDPOINT EXTENSION of the production dump through the raw
  low-conf stream, ids untouched): fulls 3459 -> 4162 (+20%), and
  NB-LEFT CLOSED DEAD-ON (348 -> 413 vs Mio 411 — a named recall wall).**
  EB-left closed (234 vs 229). Costs: EB-right twin flood AMPLIFIED
  (309 -> 406; extension completes BOTH twins), NB-thru +143 follower
  overshoot, SB-thru -104 (merge-stage interaction, merged_away 237->342,
  UNDIAGNOSED). Net 51.3 vs control 53.4 — composition transformed.
- Journey-level dedup v1 (same gate-pair + co-temporal + <=20 px
  common-frame): only 26-37 pairs, EB unmoved — the EB duplicates are
  NOT tight-riding twins as full journeys; their pairwise geometry is
  UNMEASURED (next probe: distance distribution of same-cell co-temporal
  fulls on the v2c dump — set the criterion from measured bimodality,
  or find the true signature: offset split-boxes / cab-trailer class).
- Scripts: v2_tubelet.py (retired path), v2_extend_dump.py (the keeper),
  v2_journey_dedup.py (criterion open). All measured via scratch pass-2;
  production untouched throughout.

NEXT (in order): (1) measure the EB duplicate-pair geometry on v2c —
one diagnostic, criterion from data; (2) SB-thru merge-interaction
diagnosis (corpus expecteds shifted with the extended bank); (3) full
stack (v2c + measured dedup) on dev, then BLIND HELD-OUTS; (4) cam1
transfer (G-A2).

## DAY-6 — origin-lane probe verdict + THE NEXT MEASUREMENT (spec)

- v2_origin_lane_probe.py on control: EB-right 220 direct = 59 own-lane
  + 151 SB-lane. BUT the sibling control caught the confound: EB-left
  (HEALTHY, 215 vs 229) also shows 105/121 "SB-lane" — EB entry geometry
  legitimately hugs SB lanes (the 21 px collinearity). Closest-channel-
  at-entry = the BEV-dead information channel re-measured at event
  level. LANE FILTER DEAD as a direct mechanism (sibling-cell control
  is now a REQUIRED part of any origin-filter evaluation).
- SURVIVING CANDIDATE — ENTANGLEMENT-CONDITIONED CLAIM DEMOTION: where
  a camera's own geometry says origins are inseparable (EB/SB channel
  separation < gate tolerance — DERIVED per camera, not a constant),
  direct origin claims in that region may not assert; they route to the
  item-8 posterior/branch1 (corpus-support allocation — proven, in the
  chain). Zeroth-order stakes: EB-right err +142 -> approx -9 and
  SB-thru -102 -> +49 IF the 151 demote to SB; the open question is
  whether EB-left's healthy 105 SURVIVE via support-proportional
  allocation — only branch1's real logic answers it.
- **NEXT MEASUREMENT (first action next session): the POSTERIOR
  COUNTERFACTUAL.** Replicate backend/services/posterior.py branch1
  allocation offline for the demotion-candidate set (all entangled-
  region directs, EB-right AND EB-left AND EB-thru), produce
  counterfactual per-cell counts, score vs Mio incl. sibling cells.
  Artifacts: control working DB + tracklets npz + corpus bank JSON in
  _replay_scratch/v2_week1 — no new runs needed. If counterfactual
  passes (EB-right fixed, EB-left intact), implement demotion in the
  chain behind a flag, then full stack (extension + demotion) -> dev ->
  BLIND HELD-OUTS (G-A1 re-attempt).

## DAY-6b — COUNTERFACTUAL VERDICT: census-ratio-conditioned demotion

v2_demotion_counterfactual.py (support-proportional branch1 brackets,
shape excluded): BLANKET W-demotion = LEC2-shaped failure (EB-right 309
-> 164 vs Mio 167 BUT EB-left 215 -> 102 vs 229 destroyed). The GT-FREE
selector that spares the healthy cell: GATE-EVIDENCE CENSUS RATIO —
direct-attributed mass / full-journey evidence per cell: EB-left 121/149
= 0.8 healthy, EB-right 220/54 = 4.1 FLOOD, EB-thru 34/2 = 17 flood.
Selective demotion (ratio > ~2, derived not frozen) hand-computes to
EB-right err +142 -> ~-30, SB-thru -102 -> ~+62, EB-left untouched;
real branch1 shape lands between brackets.

**NEXT SESSION: implement CENSUS-RATIO-CONDITIONED DEMOTION in the
chain** (flag-gated; ingredients all exist: entry_gates.cell_census +
partial_evidence.origin_posterior + branch1 write path; new wiring =
the conditional). Then: real-branch1 dev measurement -> full stack
(extension + demotion) -> BLIND HELD-OUTS (G-A1 re-attempt) -> cam1
(G-A2). Scripts through v2_demotion_counterfactual.py all live.

## DAY-5 LATE ADDENDUM — the EB flood is NOT twins; it is GATE GEOMETRY

- Pair-geometry probe (v2_pair_geometry.py): cell 28->29 (EB-right) has
  NO tight co-temporal pair population (2/92 under 40 px, entry gap
  median 9.8 s) — journey dedup CANNOT fix it; criterion question closed.
- Direction split (v2_extend_dump --directions): NB-left win is ~half
  backward extension (348 -> 380 fwd-only -> 413 both); EB-right
  amplifies EVEN FORWARD-ONLY (309 -> 392 -> 406) — forward never
  touches origins, so the flood = tracks ALREADY carrying false EB entry
  evidence in the PRODUCTION dump (control 309 vs Mio 167 — the class
  predates V2; extension only completes those journeys so they count).
- Evidence gate is ACTIVE everywhere (coverage .49-.62 > .45) — the
  flood passes THROUGH it: false origins are gate-crossing-real. The
  BEV-era geometry note (EB entry entangled with SB thru lanes, ~21 px)
  names the suspect: SB vehicles grazing the EB gate inward.
- NEXT PROBE (first action next session): histogram WHERE along the EB
  gate span the counted EB-right tracks cross vs true-EB (28->26/27)
  tracks (classify's origin_pos projected on the gate axis). If false
  crossings cluster at the SB-lane end: restrict origin claims by
  gate_lane_clusters (production machinery, today only used by the
  u-turn guard) — fixes CONTROL and V2 alike, and transfers to every
  entangled-gate camera. This would be the first V2 finding that
  improves the SHIPPED chain directly.

Block: plan_v2_week1_derisk_2026-08-03. Gates G-A1/G-A2 pre-declared.
Everything ran in scratch (_replay_scratch/v2_week1); production untouched.

## DELIVERED (all live, reusable)

- The V2 harness end-to-end: dump reader/tracklet tables (5 dev windows),
  synthetic-fragmentation instrument (recall + cut-precision + rank diag),
  greedy/assignment/MCF stitchers, dump re-ID pass, production-pass-2
  scratch driver, dev scorer. REPLAY PARITY PROVEN: control (original
  dump through today's pass-2 in scratch) == production table
  CELL-FOR-CELL on all 3 cam2 windows — the A/B basis is exact.
- Frozen by measurement: bidirectional-mean position cost (transfers
  cam2+cam1); turn-aware no-backward gate (clamped 90–150 deg by dt);
  motion-state-conditioned calibration (queued anchors poisoned the
  first fit); mutual-best structure.

## GATE VERDICTS

- **G-A1: FAIL (held-outs).** Fixed-threshold assembly: dev +4.9 pts,
  EB flood −43% — but 11:00 −2.9 pts (EB overshot to −60) and 16:00
  −0.9 (EB overshot to −225): a fixed accept threshold over-links at PM
  density. Ratio-mode (R=0.7 mutual-best): instrument precision 0.91–
  0.98 but assembly volume too small to move counting (dev == control).
  Pre-merge (co-life IoU): engages (353 groups) but catches only ~1/4
  of the EB twin mass while deepening NB-left/SB-right/SB-thru
  undercounts — false twin-merges of distinct far-band vehicles.
- **G-A2: not reached** (blocked on G-A1).

## LEDGER ADDITIONS (measured dead, do not re-spike)

- Velocity-continuity link term at 640×480 (8-pt fits: noise; cost 12
  rank-1 places, pruned long-gap true links).
- Chain-economics MCF with evidence bounties (arbitrage: solver trades
  correct pairings for "explained fragments").
- Structural birth/death pricing in bipartite assignment (raises
  acceptance faster than discrimination at every scale tested).
- Co-life IoU pre-merge for far-band concurrent twins — the FOURTH dead
  channel on the twin class (geometry x2, appearance x1, co-life IoU x1):
  at 10–30 px, split-twin boxes diverge (low IoU) while distinct
  same-lane neighbors overlap (high IoU). Image-space pairwise signals
  on this class are EXHAUSTED.

## WHAT THE WEEK PROVED (positive)

1. Assembly-as-input to the UNTOUCHED production pass-2 works
   mechanically and moves counting (+4.9 dev) — the architecture is
   sound; the acceptance policy is the unsolved part.
2. The EB split-flood is genuinely mergeable (direction correct on all
   3 windows) — but its core is CONCURRENT twins, unreachable by
   sequential links and by all four pairwise channels.
3. cam2's remaining big cells are RECALL walls (SB-right −165, NB-left
   −63, EB-thru −85 on the dev window): journeys absent from the dump.
   No assembly policy can count what was never tracked.

## NEXT (re-ordered by this evidence)

1. **Structural twin test — the one untried channel**: co-temporal
   tracklets COMPETING FOR THE SAME CONTINUATION (mutual-best successor
   collision on the existing graph) = one vehicle. No thresholds, pure
   structure. Cheap to implement; instrument first.
2. **Workstream B moves UP (ahead of more assembly policy)**: REPP-class
   tubelet stabilization + far-ROI detection feed BOTH failure classes —
   fewer fragments (less link ambiguity, ratio test keeps more) and new
   journeys for the recall walls. The week-1 evidence says input quality,
   not assembly cleverness, is the binding constraint on cam2.
3. Queue-order constraints for the 60 s red-light class (still ~0.16
   stitch recall) — after 1+2.
4. G-A1 re-attempt only after 1 (and possibly 2) land; same blind
   held-out protocol, unchanged gate.

Dep-hygiene note: ortools is DEV-ONLY (its install dragged numpy to 2.5
and broke the production scipy import — caught and rolled back to
numpy 1.26.4 same session; never add ortools to requirements.txt).
