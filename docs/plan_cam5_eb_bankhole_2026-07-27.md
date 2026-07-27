# Plan — cam5 EB/NB wall: corpus-path PROMOTION (the bank-hole fix, 2026-07-27)

Operator-selected next wall (handoff 2026-07-27, option B). cam5 stock-basis
production: **total 7.2%, EB 16.1 / NB 17.3 / SB 5.1** (replayed-minutes
basis, `runs/finetune_v2/corridor_ft2_rebaseline.json` — aggregate over the
three 120-min study windows 0700/1100/1600; no per-window splits survive).
Named mechanism: the applied bank has NO EB-thru (38→36) path — the only
missing through of four (verified live in `project.db` 2026-07-27; the
applied 9-path set == `evaluations/shipped_bank_cam5.json`).

## The record, reconciled (why this plan is decomposition-first)

Three prior findings must be held together honestly:

1. **The bank-coverage audit (2026-07-09)** measured the three hole cells
   (EB-thru 38→36, NB-right 39→36, WB-left 36→39) at ~13 real vehicles per
   30 min at 07:00 (EB-thru = 2), found drawn-template fills create phantoms
   (arm C: +10 phantoms / 2 real), and named **EB-right (38→39) undercount
   −41%** (23 vs 39, banked, detection healthy) as the real EB residual —
   retrospective target T3, still uncaught (S3 blocked).
2. **The ft2 re-baseline (2026-07-24)** attributed cam5-EB to the bank hole
   on the FT2 basis (EB 16.1→63.9 — new far-field EB traffic hitting the
   missing path in volume). Production stays stock; the stock-basis EB 16.1
   was never decomposed per-cell over the full windows.
3. **NB 17.3 is WORSE than EB 16.1** and has no ledger anywhere in the
   record. NB-right (39→36) is a hole cell. The applied bank's supports are
   asymmetric in a way that wants explaining: NB-thru 79 vs SB-thru 341,
   and NB-left 101 > NB-thru 79.

**The reframe that motivates the mechanism (found regrounding, 2026-07-27):
pass-2 corpus discovery ALREADY FINDS the EB-thru path every run** — support
58 in `two_pass/twopass_bank_cam5_study_0700.json` (full-window pooled
build), 44 in the regenerated `evaluations/gtfree_bank_cam5.json` — and
discards it by design: `two_pass.py`'s standing rule feeds the corpus bank
to expecteds/QA only, never the applied attribution path-set
(`run_pass2`/`_finish_apply`, "the applied bank stays"). The defect is
non-promotion, not discovery. The S4 bank_coverage_hole cards surface the
holes to the operator (designed outcome, July-9 standing conclusion #1) —
but that conclusion was drawn from DRAWN-template fills. A FITTED path,
built from the corpus tracks that actually lie where cam5's traffic lies,
is materially different evidence and re-tests it.

This is exactly the mechanism the bank-D verdict (2026-07-10) said would
need its own plan: "a refit-mode variant would be a NEW mechanism." This is
that plan. Standing rule 1 is untouched: drawn channels still never enter
the applied path-set — promotion sources are FITTED corpus paths only.

## The mechanism candidate (frozen shape; constants frozen after phase 0)

    PROMOTE(cam, cell) iff:
      - the applied bank has NO path for (origin, dest) cell, AND
      - the full-corpus pooled discovery (build_gtfree_bank(tracks=all
        study dumps), builder constants AT DEFAULTS: min_support=5,
        min_share=0.01, bearing_tol=55°, ...) yields a non-uturn fitted
        path for the cell with support ≥ K
    → the fitted path joins the REPLAY attribution path-set for that
      camera (via the existing replay_camera(bank=...) injection — the
      applied bank in project.db is never edited by the mechanism; apply
      remains the operator-gated measure-then-apply step).

K is the one new constant; it gets frozen from phase-0/1 evidence BEFORE
the blind sweep. Everything else runs at existing defaults. GT-free by
construction (§0 litmus: a new site pools its own dumps, discovers, and
fills its own holes blind; the S4 card dissolves itself when the hole
closes — surfacing upgraded to auto-fix + operator visibility).

Named hazards the gates must catch (each measured before, on record):
- **Phantom magnet** (July-9 arm C, drawn): added cell's events must track
  Mio cell volume, not neighbor streams. Per-cell phantom check.
- **Claim-corridor contamination** (July-9 fresh drawn-direct build B,
  38.9% MAE): a promoted path stealing from banked collinear neighbors
  (38→36 thru vs 38→39 right share origin; 39→36 right vs 39→37 thru).
  Whole-camera per-cell scoring, never the added cell alone.
- **Cancellation masquerading as improvement** (bank-D lesson): report
  per-cell AND per-approach cuts; a per-approach win via offsetting cell
  errors is not a pass.

## Phase 0 — decomposition (replay-only, stock basis; no mechanism code)

OFF-parity FIRST (scoring-basis discipline): the committed harness must
reproduce the rebaseline stock row — total 7.2, EB 16.1 / NB 17.3 / SB 5.1
— from the stock dumps before any other number is read. (Re-commit the
scorer: the producer `corridor_ft2_rebaseline.py` survives only in the
prior session's scratchpad — the phase-1-drivers lesson, never again.)

Then, over the three stock windows (replay out_dbs + dumps + Mio XML via
`parse_miovision_xml.py` / `interval_metric.py`):

1. **Full-window Mio per-cell volumes** — all 12 cells × 3 windows. Sizes
   the real prize in each hole cell (the July-9 numbers were one 30-min
   sample) and answers why the rebaseline aggregate carries no WB approach
   (ref-floor filter? approach mapping?) — if WB exists in GT with real
   volume, the honest per-approach table gains a column.
2. **Ours-vs-Mio per-cell table** (replay basis) — which cells drive
   EB 16.1 and NB 17.3 per window. Confirm EB-right's −41% class holds
   full-day; get NB's first-ever cell split.
3. **Origin-38 and origin-39 fate ledgers** (diagnose_ebright_loss
   pattern re-pointed; dumps + box-crossing census): for each track —
   complete journey? claimed which path? dropped at no-origin /
   insufficient-data (the no-path signature)? Quantifies: real EB-thru /
   NB-right vehicles present in the dumps that a promoted path could
   recover, vs vehicles that never journey (capability class, not
   bank-recoverable).
4. **Magnet-risk read on the discovered paths**: corpus-bank claimed
   supports (EB-thru 58/window-0700) vs Mio cell volume same window — a
   support≫volume ratio flags the phantom hazard before any replay.
5. **S4 card impacts** for cam5's holes (production queue) — the GT-free
   volume signal on record, checked against Mio.

### Decision checkpoint (pre-declared branches)

- **A. Holes carry real, recoverable volume** (Mio cell volume material to
  the approach error AND fate ledger shows recoverable journeys) →
  phase 1 as specified.
- **B. July-9 story holds full-day** (holes tiny; EB driven by EB-right
  undercount, NB by non-hole cells) → the promotion A/B still runs ONCE
  (cheap, bank-content only) for the record + the ft2-future-proofing
  argument, but the wall re-aims: the phase-0 ledgers become the plan
  input for the EB-right/NB mechanism doc, and a negative here is the
  deliverable.
- **C. Ledger surprises** (e.g. NB 17.3 is an approach-mapping or
  merge-gate artifact, not attribution) → stop, write it up, re-plan.

## Phase 1 — bank-content A/B (injection hook; project.db untouched)

Arms, all three stock windows, identical replay+merge, whole-camera scored:
- **BASE** = applied 9-path bank (the OFF-parity arm).
- **P** = applied ∪ promoted fitted paths for the hole cells that phase 0
  supports (at minimum 38→36; 39→36 and 36→39 iff their ledgers say real
  volume) from the FULL-corpus pooled build.

Gates (pre-declared): (a) cam5 per-approach MAE improves aggregate and on
≥2 of 3 windows, touched approaches (EB, NB if promoted) each improve;
(b) added cells' event counts land within ~1.5× their Mio volume per
window (phantom check — the July-9 drawn fill was 5×); (c) no untouched
cell regresses beyond ±2/window (the parity noise bar); (d) per-cell abs
total improves (anti-cancellation). PASS → freeze K from the evidence,
phase 2. FAIL → verdict + retirement entry with numbers; branch-B re-aim.

## Phase 2 — wire + frozen-constant blind sweep

Wire PROMOTE into `run_pass2` behind `CORPUS_PATH_PROMOTION_ENABLED`
(default OFF), measure-then-apply unchanged; promoted paths land in the
replay/out_db path-set with `source='corpus-promoted'` (auditable,
distinguishable from operator-applied rows forever).

Blind sweep at frozen constants, promotion rule applied blindly wherever
it fires: cams 1/2/4 stock (their own hole cells — cam2 has three, incl.
its EB-thru 28→26 with real volume 31/30min; the rule promotes FITTED
paths where discovery finds them, which is the fitted analogue of retired
bank-D — the sweep decides it, and a cam2 regression fails the rule),
cam3 (tripwire 3.2 — regression is a hard stop), FM51 both window-DBs
(held-out: no GT enters the rule; scored only). Production cam2 4.8
(interval-scorer basis) must not regress on its applied windows. PASS →
default-ON proposal to operator with numbers; FAIL → flag stays OFF,
verdict + numbers, negatives are deliverables.

## Costs

Phase 0–1: replays only (~1–4 min/window × 3 windows × arms) + XML parses;
no detection, no training. Phase 2 sweep: ~9 corridor windows + FM51
replays. All CPU-bound sqlite/replay work; no iGPU.

## Scoring bases (named once, used throughout)

- **replayed-minutes basis** — per-approach AVG|err|% per 15-min vs Mio
  over a replay out_db's covered minutes (the rebaseline's basis; phase
  0/1/2 measurement basis). OFF-parity to the rebaseline row proves it.
- **production interval-scorer basis** — the applied project.db scored by
  `interval_metric.report_camera` (the 4.8 cam2 number; only used at
  apply time).
Numbers from the two are never compared directly.

---

## PHASE-0 FINDINGS (2026-07-27 — evidence runs/cam5_wall/phase0.json,
fate_study_0700.json; harnesses scripts/cam5_wall_phase0.py, cam5_wall_fate.py)

**OFF-PARITY: EXACT PASS.** Plain replays of the three stock windows on
today's chain reproduce the rebaseline stock row to the decimal — pooled
total 7.2, EB 16.1 / NB 17.3 / SB 5.1 (replayed-minutes basis). First
per-window splits on record: 0700 total 6.3 (EB 12.7, NB 10.9), 1100
total 9.7 (**NB 23.8**), 1600 total 5.5 (**EB 22.7**).

**The bank-hole hypothesis is DEAD as the ≤5% lever (checkpoint branch B,
decisively).** Full-day Mio volumes in the hole cells: EB-thru 38→36 =
**45** (4/12/29 per window), NB-right 39→36 = **82**, WB-left 36→39 = 65 —
against per-cell walls of 200–650. Best-case hole recovery (+73 NB-right)
is ~6% of the NB error mass and ~0% of EB's. Production fallback tiers
already roughly cover the holes (54 EB-thru events all-day vs 45 real).
The July-9 audit's 30-min extrapolation holds full-day.

**What actually drives cam5 (pooled per-cell, ours vs Mio):**

| cell | ours | Mio | ratio | driver |
|---|---|---|---|---|
| NB-left 39→38 | 1406 | 760 | **1.85** | +646 — the biggest wall |
| NB-thru 39→37 | 6447 | 5926 | 1.09 | +521 ┐ one ~500-veh |
| SB-thru 37→39 | 5766 | 6183 | 0.93 | −417 ┘ N↔S see-saw |
| EB-right 38→39 | 387 | 594 | **0.65** | −207 (T3, stable 0.66/0.72/0.60) |
| NB-right 39→36 | 9 | 82 | 0.11 | −73 (the hole, small) |
| WB cells (all) | ~552 | ~210 | 1.7–3.6× | phantoms, but WB never clears
REF_FLOOR=20/bin — invisible to the approach metric (answers the missing-
WB-column question) |

**The fate ledger names the mechanism (0700; class-level finalize wrap +
vehicle_track_id event join).** Same-anchor STUBS — tracks born and dying
near one leg mouth — are **45% of all ≥4-pt tracks** (3,597/7,946). The
S-mouth far-field stub population (geo 39>39, n=3,032) alone emits 1,051
events: 392 SB-thru + 318 NB-thru + **229 NB-left (≈ the entire +222
NB-left phantom at 0700)** + 104 EB-right. Meanwhile:
- **EB-right is a journey-formation hole, not attribution**: only 13
  tracks all window have real EB-right geometry; 104 of its 124 events
  are 39-stubs. Recall 0.65 is stub-matching luck over a near-field turn
  the tracker rarely survives.
- **NB-thru is CORRECT by fragments**: 1,839 of 2,468 events are far-band
  fragments (born top-right, dying mid-band) correctly claimed because
  the fitted NB-thru path covers the far band. The same unevidenced
  population that phantoms NB-left CARRIES NB-thru — which is why the
  evidence gate (coverage 0.387 < 0.45, stands down) is RIGHT to refuse
  cam5: filter-only would collapse the main stream. The stub
  discriminator must be WHICH PATH SEGMENT a stub covers (past the
  divergence or not — the (s,d)/coverage machinery), not entry evidence.
- **SB-thru leaks 21% to insufficient-data** (257/1,222 real-geometry
  journeys dropped) — the −417 deficit's core.
- geo 38>36 (n=62) ≈ truncated EB-LEFTS + the ~4 real EB-thrus (Mio:
  EB-left 96 vs only 26 full journeys) — attributed 38→37, largely
  CORRECTLY. Nearest-anchor geometry cannot split EB-thru from truncated
  EB-left here, which is exactly why any 38→36 path magnets (July-9 arm
  C re-explained).

**The 1600 ledger replicates the mechanism at PM scale**
(fate_study_1600.json — EB's worst window, 22.7): NB-left +199 over ≈ its
194 stub-fed events (mechanism stable both windows); EB-right has 21
real-geometry tracks ALL WINDOW with 2 kept (112 of its 147 events are
39-stubs; recall 0.60); SB-thru insuf leak 430/2,444 (18%) — scales with
volume; NB-thru real full journeys are 13% of its events (326/2,440), the
rest correctly-claimed fragments. The PM is also where the EB-thru hole
actually bites: 13 recovered vs 29 real (−16) — still a fraction of
EB-right's −97 in the same window.

**Corpus-discovery claim distortion, quantified (stage D):** the corpus
build's hole-cell "discoveries" are fragment artifacts — 36→39 support
1238 vs 26 real (48×), 39→36 support 814 vs 21 (39×), u-turn 39→39
support 461 vs ~1 — both big ones geometrically PROVEN misfits (polyline
mean-nearest 22 px / 15 px to the applied SB-/NB-thru corridors =
near-subsegments), while the true streams under-claim (SB-thru 0.31×,
NB-thru 0.65×). **The regrounding reframe ("non-promotion is the defect")
is OVERTURNED by this phase's own evidence: non-promotion was protecting
production. The July-9 standing conclusion (holes are a QA-queue item,
not an auto-fix) is RE-CONFIRMED on the corpus-fitted source.** A GT-free
geometric promotion guard (reject candidates whose polyline is a
near-subsegment of an existing banked path of a different cell) falls out
of the evidence and kills 2 of 3 candidates blind; the surviving 38→36
still claim-inflates 15× (58 vs 4). The one-path promotion A/B runs for
the record (verdict below).

---

## CHECKPOINT DECISION + PHASE-1 A/B VERDICT (2026-07-27 — evidence
runs/cam5_wall/promo_ab.json; harness scripts/cam5_wall_promoAB.py)

**Checkpoint: BRANCH B, decisively.** The holes are tiny, the walls are
elsewhere; the A/B ran once for the record with the one guard-surviving
candidate (applied 9 + corpus 38→36 sc58).

**A/B VERDICT: FAIL — the pre-declared gates catch a cancellation
masquerade.** Replay-only basis, all three stock windows:

| cut | BASE | P (promoted) |
|---|---|---|
| pooled total / EB | 7.2 / 16.1 | 7.4 / **13.5** |
| per-window EB | 12.7 / 13.0 / 22.7 | **8.6** / 14.3 / **17.6** |
| EB-thru cell vs Mio | 17/43 · 24/47 · 13/43 | **43 vs 4 · 47 vs 12 · 43 vs 29** |

Gate (a) technically passes (EB aggregate + 2/3 windows improve). Gates
(b)+(c) FAIL: the promoted path pulls the 4–29-vehicle EB-thru cell to a
flat ~43–47 events every window (10.75× real at 0700), sourced from
re-magneted truncated EB-LEFTS (38→37 −13/−5/−7) and far-band NB-THRU
fragments (39→37 −11/−10/−12) — the same far-band reach the geometric
guard caught in the other two candidates, in miniature. Per-cell abs
error is flat (2399→2394): the EB approach "improvement" is phantom
EB-thru fill offsetting the EB-right deficit INSIDE the approach total —
per-approach flattered, per-cell corrupted. **Bank-hole path-fill retires
at cam5 a THIRD time (drawn ×2 July-9/July-10, fitted ×1 today), now
with the mechanism named: at a fragment-heavy camera, any path through
the far band claims fragment mass ~10:1 against the target cell's real
volume.** Phase 2 (wiring + blind sweep) is NOT RUN — nothing ships.
project.db untouched throughout; the S4 cards remain the designed
surfacing for the holes.

## THE RE-AIMED WALL (the block's forward deliverable)

cam5's per-approach failure is one family + two independents, each now
sized and evidence-anchored (phase0.json, fate_*.json):

1. **Far-field stub-claim discipline** (the family; NEW mechanism, own
   plan + gates before any code): same-anchor stubs (45% of tracks) may
   currently claim any path whose FAR-BAND SEGMENT they cover. Targets:
   NB-left phantom +646 (stub-fed 229/194 per window), EB-right's
   104/112 stub events, the WB phantom mass. HARD CONSTRAINT the ledger
   proves: the same stub/fragment population correctly CARRIES NB-thru
   (1839/1663 events) — so the discriminator must be segment-coverage
   past the movement divergence (the §2b (s,d)/coverage direction),
   NEVER entry-evidence (the activation census already refuses cam5,
   coverage 0.387) and never stub-ness alone.
2. **SB-thru insufficient-data leak** −417: 21%/18% of real-geometry SB
   journeys drop as insufficient. Cheapest candidate on the new board —
   one diagnosis session (why insufficient? min-points/short-arc gate vs
   far-band fragment shape) before any mechanism.
3. **EB-right journey formation** −207: 13/21 real-geometry tracks per
   window; the near-field turn rarely survives tracking. Capability
   class (birth/association at the turn), routes beside the cam2
   SB-right recall wall, NOT matcher work.

Order: 2 (diagnosis, cheap) → 1 (the family, biggest mass) → 3
(capability track). Each inherits full gate discipline.
