# Bank-coverage audit + surgical-fill A/B/C/D (2026-07-09)

Follow-up to the detector spike's cam5 lead (live bank missing EB-thru). Corridor-wide
audit of `channels` (drawn) vs `intersection_paths` (applied bank), then measured
bank-swap experiments on cams 5 and 2. Miovision = scorer only; banks are GT-free.

## Audit (all 5 cams)

| cam | missing bank cells | drawn channel exists? | real volume in cells (Mio, 07:00–07:30) |
|---|---|---|---|
| 1 | driveway leg 25 unbanked | no channels drawn | ~0 (known zero-traffic leg) |
| 2 | WB-left 26→29, **EB-thru 28→26**, NB-right 29→26 | yes (all 16 drawn) | 14 / **31** / 2 |
| 3 | 2 side-street turn-ins | no channels drawn | (passing cam, not measured) |
| 4 | 2 side-street turn-ins | no channels drawn | (passing cam, not measured) |
| 5 | WB-left 36→39, EB-thru 38→36, NB-right 39→36 | yes (all 16 drawn) | 6 / 2 / 5 |

Both failing cameras' applied banks predate drawn-direct (2026-07-07): a fresh
drawn-direct build fills every cell. But cam5's fresh build shows the claim-corridor
contamination immediately: WB-left "support 288" + SB-thru 142 ≈ the real SB-thru
425 at neighboring cam1 — the drawn WB-left corridor claims ~⅔ of the SB-thru
stream; NB-right claims 182; a u-turn passes the reversal gate with "81/118
reversals" that Miovision says don't exist (0 u-turns).

## cam5 A/B/C (BoT retrack harness, 07:00–07:30, same window scored)

| arm | bank | total net | per-approach MAE | tell-tale |
|---|---|---|---|---|
| live project.db (context) | applied | +1.3% | 7.3% (EB 15.9 FAIL) | EB-right −16 (23 vs 39) |
| A | live applied | +11.8% | 9.4% | NB-left +96 — the harness has no turn-merge; A/B/C internal compare only |
| B | fresh full drawn-direct | −0.6% (cancellation) | **38.9%** | NB-right +161, NB-uturn +134 phantoms |
| C | live + 3 missing drawn cells | +11.7% | 10.2% | added EB-thru template = +10 phantoms (2 real) |

**cam5 verdict: NEGATIVE — live bank stays.** The missing cells hold ~13 real
vehicles total (EB-thru = 2); filling them with drawn templates only creates
phantoms. B re-confirms the Gate-B drawn-direct collapse on a second camera with
per-cell forensics. **The real cam5-EB residual is now cell-precise: EB-right
(38→39, already banked, support 43) undercounts −41% (23 vs 39)** — detection
healthy per the detector spike ⇒ downstream (tracking/attribution), new target.

## cam2 A/C/D (same harness; B skipped — §2c already measured drawn-direct at −20.8%)

Arm A reproduces the live project.db table EXACTLY (−63 net, 9.8% MAE, identical
cells) — the retrack harness is faithful on cam2, so A/C/D read directly against live.

| cell (Mio) | A = live bank | C = +3 cells | D = +EB-thru only |
|---|---|---|---|
| EB-thru (31) | −27 | −14 | **−12** |
| EB-right (50) | +31 | +26 | +26 |
| SB-left (19) | +12 | −7 | +7 |
| NB-right (2) | −2 | **+12 phantoms** | −2 |
| WB-left (14) | −13 | −12 | −13 |
| SB-thru (310) | −43 | −47 | −48 |
| **per-cell abs total (deliverable cut)** | **243 (17.5%)** | 233 | **223 (16.1%)** |
| per-approach MAE (codified bar) | 9.8% | 10.4% | 11.4% |

Mechanics: the drawn EB-thru template lets truncated EB-thru tracks claim their
real cell (+15), pulling 5 mislabeled events off EB-right's overcount and 5 off
SB-left's (both good — shared legs); cost = 5 real SB-thru relabeled EB-thru. The
NB-right template (arm C) magnets +12 phantoms from the 626-strong NB-thru stream
— dropped in D. WB-left recovers nothing under any bank: those 13 vehicles never
produce claimable tracks (a tracking miss, not a bank miss).

## The metric tension D exposes (decision: HELD 2026-07-09)

Engineer decision: hold D, pair it with the diagnosed EB ID-split dedup and
re-test jointly. **The dedup then FAILED its dev ablation same-day**
(`docs/plan_concurrent_dedup_2026-07-09.md` — the live event stream no longer
carries concurrent duplicates; the pass eats real NB-thru vehicles at every
setting), so D stays held indefinitely: its per-approach regression has no
pending offset. The EB-right/SB-right overcounts are collinear-attribution
shaped — §2c two-pass territory, or §3-B flag-queue material.

D is better on the PER-CELL cut — which is what the TMC Excel actually delivers —
but WORSE on the codified per-approach MAE (9.8→11.4), because EB-thru's undercount
was cancelling EB-right's known ID-split overcount (diagnosis mechanism 2) inside
the EB approach total. Fixing the real cell exposes the other cell's error. Applying
D makes the deliverable more truthful per-movement; holding keeps the flattering
approach-level cancellation. If/when the EB ID-split dedup lands (the diagnosed
cheap lever), D's recovery becomes unambiguously positive on both cuts.

## Standing conclusions

1. **Bank-coverage holes are a QA-QUEUE item, not an auto-fix.** Two cameras,
   three experiments: drawn-template fills trade recovery for phantoms roughly 1:1
   unless the cell has real volume AND no big collinear neighbor stream competing
   (cam2 EB-thru is the one qualifying cell found).
2. The missing-movement flag the bank builder already emits (`build_bank_gtfree`)
   is exactly the right surfacing — route it to the §3-B flag queue with the
   cell's claimed volume, so an operator reviews footage instead of the pipeline
   silently trusting a template.
3. cams 3/4: leave alone (passing; side-street turn-in cells are likely
   cam5-class tiny; drawing channels there is not justified by today's evidence).
4. Artifacts: `evaluations/cam2_live_bank_dump.json` (exact applied bank),
   `evaluations/cam2_live_plus_missing.json` (C), `evaluations/cam2_live_plus_ebthru.json`
   (D), `evaluations/cam5_live_plus_missing.json`, regenerated
   `evaluations/gtfree_bank_cam5.json` (current builder; NOT applied).
