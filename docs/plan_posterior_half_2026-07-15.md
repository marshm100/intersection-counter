# Plan — item-8 phase 1, mechanism ① posterior half: the partial-evidence posterior (2026-07-15)

Parent: `plan_origin_evidence_gate_2026-07-14.md` (filter+fill FROZEN; held-out
MIXED; SB-right autopsy verdict EXPOSED — the gate is truth-improving and the
five-cam sweep waits on THIS work). Same gate discipline: constants fit on
study_0700 only, frozen before held-out; negatives are deliverables; Miovision
in scorer scripts only.

## Why (the measured workload this must clear)

The filter half moves vehicles to the correct ORIGIN but replaces nothing:

- **Unevidenced tracks** (no inward entry crossing) still run the legacy
  joint scorer over ALL paths — the residual flip channel. Measured leakage:
  44/96 unevidenced SB-right events per held-out window, 363 no-crossing
  SB-thrus on 1600, 108 of EB-left's fit-window overshoot.
- **Evidenced-but-truncated tracks** get origin pinned but destination still
  snaps coverage-blind: 279 de-flipped entry-28 EB tracks on 1600, of which
  **217 landed 28→29:right** — simultaneously the SB-thru −195 and the
  EB-right +116. Mio says the EB pool splits ~40/60 thru/right; the snap
  gives ~0/100. This is the item-② pool, pulled forward because the autopsy
  showed it dominates the held-out aggregate damage.
- **De-flip drops**: stolen NB-lefts whose true cell match fails go NO_EVENT
  (39 on 1100) instead of landing 29→28 — the unclaimed-288 class.
- **Merge eats genuine events**: 17/14 box-full EB-lefts per window
  REJECTED(merge) because expecteds were discovered from FLIPPED tracks.

## The mechanism — one design, two conditionings

Both cases are the same move: **when the evidence cannot decide a single
cell, build an explicit posterior over the feasible cells from corpus
supports, count at the posterior max, and record the posterior + margin so
the S-feeder can queue the near-ties.** Nothing is dropped; nothing
hard-claims what it cannot evidence.

1. **Unevidenced branch (no entry crossing).** Candidate cells = paths whose
   sub-curve shape-fits the observed track under the EXISTING joint-scorer
   admission (max_cost / min_coverage — no new geometry constants). Exit-gate
   evidence, when present (`exit_only` tag), filters candidates to that
   destination first. Posterior over survivors ∝ corpus `supporting_count`
   (PROPORTIONS, not absolutes — scale-free, so standing-rule-2's scale-1
   requirement is satisfied by construction) × a shape-residual likelihood
   (the scorer's own cost, softmaxed). Count at posterior max; write
   `origin_posterior_json` + `origin_margin`; margin below the floor →
   `origin_ambiguous` uncertain-event flag (Feeder-1 subtype).
2. **Evidenced-truncated branch (entry crossed, death before divergence).**
   Candidates are already origin-filtered by the frozen half. Ambiguity test:
   ≥2 candidates whose joint-scorer costs over the OBSERVED span sit within a
   tie band (their separating geometry lies past the death point). Tied →
   destination posterior over the tied cells ∝ supporting_count proportions;
   count at max; the EXISTING `destination_posterior_json` +
   `destination_margin` columns and Feeder-1 carry it natively. Untied →
   current behavior byte-identical.

**Evidence extraction:** `pipeline._origin_evidence` currently discards the
classify tuple's destination/tag; widen it to `_gate_evidence(vehicle) →
(origin, dest, tag)` (one call, no second classify pass). Counters extend the
stage-3 set: n_posterior_origin / n_posterior_dest / n_origin_ambiguous.

**New constants — exactly two, both unitless, fit on 0700 then frozen:**
- `ORIGIN_POSTERIOR_MARGIN_FLOOR` — margin below which the event is flagged
  (the parent plan's promised floor).
- `DEST_TIE_BAND` — cost-ratio band declaring truncated-track candidates
  tied. (Reuses the scorer's existing admission constants for everything
  else.)

**Flag:** `ORIGIN_POSTERIOR_ENABLED` (default OFF), separate from
`ORIGIN_EVIDENCE_GATE_ENABLED` — the halves gate and revert independently,
as the parent plan required. OFF = bit-identical legacy (test-gated, the
TWO_PASS_ENABLED pattern). Schema: nullable `origin_posterior_json` +
`origin_margin` on vehicle_events (migration, backfill-free).

## Merge-expecteds re-discovery (stage 3)

`run_pass2` derives `expected_by_cell` from the corpus QA's per-cell n —
computed by the bank builder's own shape assignment, i.e. from FLIPPED
tracks. Replace the source: a per-cell census from the ENTRY-GATE evidence
over the same dump (box-full journeys per cell + evidenced-truncated tracks
allocated by branch 2) — operator geometry only, GT-free, de-flipped by
construction, still scale-1 corpus-window observed n. Acceptance: the 17/14
genuine box-full EB-lefts stop being merge-rejected; cam3/cam4 tripwire
cells byte-stable when the flag is off.

## Build stages (each gated, no big-bang)

1. **Evidence widening + counters.** `_gate_evidence` returns the full
   tuple; unit test = tuple fidelity vs `entry_gates.classify` on a cam2
   dump sample (N=500, the stage-1 pattern).
2. **Posterior module + wiring** behind `ORIGIN_POSTERIOR_ENABLED`:
   `backend/services/partial_evidence.py` (posterior math; pure, unit-
   tested — reuses `posterior.posterior_margin` as the margin source of
   truth), pipeline branches at the two named points, schema migration,
   flag-off bit-identical test, Feeder-1 `origin_ambiguous` subtype.
3. **Expecteds re-discovery** in `run_pass2` + the replay harness (same
   census function both places; one source of truth).
4. **Fit-window ablation (cam2 study_0700, replay + merge):** arms =
   ctrl / frozen-filter+fill / +posterior. Fit the two constants here ONLY.
   Success shape: watch |err| well under the frozen 902 (ctrl 1124); EB
   thru/right split moves toward 119/167; EB-left 304 → toward 229 (the
   108+37 suspects re-allocated); NB-left ≥ the frozen 209 (de-flip drops
   recovered); insufficient/fallback counts do NOT balloon; flag volume
   within flood-control range (queue ≤ ~40 cards).
5. **Held-out 11:00/16:00, frozen constants, full chain.** THE BAR (this is
   where the filter half alone failed): aggregate watch |err| must beat ctrl
   on BOTH windows (ctrl 1054/1284), with SB-right recovering toward its
   evidenced+posterior ceiling and EB-right's 951 overshoot shrinking. Miss
   → the posterior half retires (filter+fill freeze unaffected), findings
   doc, stop.
6. **Five-camera blind sweep** (frozen, replay, baselines cam1 7.6 / cam2
   8.1 / cam3 3.2 / cam4 live 4.6 / cam5 7.1): target cells improve;
   tripwires hold (cam3, cam4-live); cam4's (34→33) mid-block class is a
   named watch cell — its 71 unevidenced-birth events are exactly branch 1's
   input, so Wall C should shed WITHOUT its own mechanism. PASS → apply
   through the product flow (per-window backups) and flip BOTH flag defaults
   in one dedicated commit. FAIL → per-half retirement entries.

## STAGE-4 VERDICT (2026-07-15): PASS — constants frozen

Four arms on cam2 study_0700 (replay + census merge; scripts `stage4_arm.py`
/ `stage4_drive.py`, session scratchpad; DBs in `ic_scratch_97a7849a`):

- **ctrl regression pin (flags off): STRICT PASS** — bit-identical to the
  product control's PRE-merge state on all 8 watch cells (the stage-2
  "legacy unchanged" claim, proven on the corpus; the recorded 1124 was the
  post-merge control, 1166 is its unmerged equivalent).
- **Posterior arm (all bands identical): watch |err| 591 unmerged / 633
  merged** vs ctrl 1166/1124 and the frozen filter+fill's 902 unmerged.
  Every success criterion met: NB-left 146→**347** (recall 0.84 — criterion
  was ≥209; the de-flip drop pool recovered), SB-thru 1082→1267, EB-thru
  23→148 (past Mio 119), EB-right 494→304, EB-left 288 (vs 229), no drop
  ballooning (insufficient 2736→**2412**; 375 rescued, 780 branch-1
  posteriors), flags 23 events → ~5 batch cards (flood-control PASS).
- **Branch 2 is structurally INERT** (posterior_dest = 0 at band 0.10 /
  0.15 / 0.25): the joint scorer matches polyline SUFFIXES, so a
  pre-divergence death cannot produce tied costs — the thru path's suffix
  is forced to align to its far end and its cost blows past any band. The
  EB-thru recovery came from branch 1 + the rescue instead. The band stays
  as a dormant guard at its default; it influenced nothing on the fit
  window (the cleanest possible freeze).
- **Census limitation, named:** cells whose traffic is truncation-dominated
  are under-expected (SB-right 180 vs Mio 379; EB-thru 4.9) because
  truncated evidence is allocated by the full-journey mix those cells
  barely have — so the merge over-rejects SB-right (319→230). Merged 633
  still beats ctrl-merged 1124 by 44%. Candidate refinement (NOT tuned now;
  the freeze line is here): allocate entry-only evidence by the posterior
  arm's own counted mix instead of the full-journey mix — recorded for the
  held-out read, not applied.

**FROZEN: ORIGIN_POSTERIOR_MARGIN_FLOOR = 0.25, DEST_TIE_BAND = 0.15**
(both the config defaults; no fit-window tuning was needed). No re-tuning
past this line.

## STAGE-5 VERDICT (2026-07-15): PASS — both held-out windows beat control

Frozen constants, full chain (gated+posterior replay, fill candidate, census
merge), zero re-tuning (`stage5_heldout.py`, session scratchpad):

- **study_1100: ctrl 1054 → 688 (−35%).** NB-left 105→328 (recall 0.73),
  SB-thru 922→1052 (Mio 1064), EB-thru 47→223, EB-right 495→286,
  EB-left 151→372. Counters: 722 branch-1 posteriors, 491 rescues, 10 flags.
- **study_1600: ctrl 1284 → 812 (−37%)** — the window the filter half alone
  made WORSE (1406). NB-left 164→375 (recall 0.89), EB-thru 109→421 (0.93
  of Mio 454 — the dead cell lives), EB-right 835→470, SB-thru 1979→2046.
  Counters: 1400 posteriors, 499 rescues, 27 flags.
- Residuals, named honestly: SB-right counts its truth (192/242 vs Mio
  388/341) — the exposed truncation deficit, a capability-track wall, not
  an attribution error. EB-right now UNDERSHOOTS on 1600 (470 vs 699,
  |err| 136→229 in that cell) — the redistribution over-corrects there;
  NB-thru/WB-right drift up slightly on both windows. All inside an
  aggregate that beats control by a third.

The posterior half holds its freeze. Next: the stage-6 five-camera blind
sweep (tripwires cam3 / cam4-live; cam4's (34→33) mid-block watch cell).

## STAGE-6 SWEEP, RUN 1 (2026-07-15): FAIL on cam1 — defect diagnosed, fixed, re-gating

Blind sweep (frozen constants, scoreboard metric recomputed for arm AND
baseline over identical minute coverage; `stage6_sweep.py`):

- **cam2: 9.1% → 3.3% TOTAL (PASS, −5.8 pts)** — EB 24.3→17.0, NB 13.9→3.2,
  SB 8.7→9.5 (the honest SB-right deficit), WB 9.8→9.0. The corridor's
  hardest camera lands under the 5% bar.
- **cam1: 4.3% → 5.0% total — but per-approach EB 14.4% → 199.4%** (NB
  5.9→21.1). FAIL. Autopsy (samples + bank query): all 400 sampled
  explosion events had posterior {24: 1.0} — the 24→23 LEFT path (support
  16) was the ONLY admitted candidate. Truncated exit stubs near the shared
  exit fail the long thru path's coverage floor (22→23, support 692) but
  clear the short turn path's — and **branch 1 ran AFTER the origin-rewrite
  gate and resurrected the vetoed family from the raw candidate list**.
  Legacy's winner-only veto had been routing exactly these tracks to the
  fallback (live 22→23 thru 1,821). cam1 exposes it because only 36% of its
  tracks have entry evidence (2,489 of 4,930 events took branch 1).
- cam4/cam5: only study_0700 dumps exist (1100/1600 `.tracks` never dumped)
  — pass-1 backfill launched from the cached detections; windows rerun at
  the re-sweep. cam3 stopped pre-run (no point sweeping the defective build
  for hours).

**FIX (structural, zero new constants):** the rewrite-gate rule applied
PER-CANDIDATE to the branch-1 pool — a straight track (same
ORIGIN_REWRITE_GATE_STRAIGHTNESS test) excludes turn-labeled candidates
whose origin is not its nearest origin zone; an emptied pool stands branch 1
down (legacy fallback proceeds). Counter n_posterior_vetoed instruments it.
Unit tests: veto fires on the straight-track case, curved tracks keep their
turn candidates. **Per gate discipline the fix re-gates stages 4→5→6 from
scratch** (the fill-arm-confound pattern: diagnose → pin → rerun).

## STAGE-6 SWEEP, RUN 2 (2026-07-15, post-veto-fix): FAIL — the verdict is structural

Re-gate chain under the fixed build: stage-4 re-fit 609/650 (bars 902/1124,
held), stage-5 re-held-out 720/813 vs ctrl 1054/1284 (BEATS CTRL both,
freeze held). The sweep:

| cam | baseline (same-cut) | arm | verdict |
|---|---|---|---|
| 2 | 9.1% | **3.5%** | PASS −5.6 (EB 24→17, NB 14→3.4) |
| 1 | 4.3% | 4.4% | holds; EB 199%→21% (veto proven); SB 2.4→5.4 drift |
| 4 | 3.6% | 6.6% | **TRIPWIRE TRIPPED** (+3.0); watch cell (34→33) GREW 111→149 |
| 5 | 2.5% | 12.5% | **FAIL** (+10.0) |
| 3 | — | — | not run (chain stopped once the verdict was determined) |

**The structural finding (the sweep's real deliverable):** the posterior
half's additions are UNCONSERVED. It wins exactly where the live chain
under-counts (every cam2 cell; cam5 SB-thru −417 under → +31 near-exact)
and double-counts where live is already at truth (cam4 35→33: live 6693 ≈
Mio 6698 → arm 7162; cam5 SB-right 352→990 vs Mio 273, NB-left 736→1227 vs
760). Two compounding causes:
1. **The rescue treats every evidenced drop as a missed vehicle.** On cam2
   the drop pool was genuinely missed traffic (phase-0's 288); on
   full-recall cameras it is fragments of already-counted vehicles —
   rescuing them double-counts (no persisted rescue marker exists yet to
   attribute exactly; instrumentation gap noted).
2. **The census cannot police the additions:** its truncated-evidence
   allocation (by full-journey mix) OVER-expects turn cells on cameras
   with fat unevidenced pools (cam5's inflated turn cells sailed through
   the merge) and UNDER-expects truncation-dominated cells (cam2
   SB-right) — the same weak component in both directions.
Blind corroboration: the evidence-coverage ratio predicts the failure —
cam2 (80% evidenced) wins; cam1/4/5 (36–60%) lose. The posterior misfires
precisely where it has the most work and the least signal.

**Disposition: the posterior half as a blanket five-camera default FAILS
the blind sweep and stays OFF (both flags default OFF, as built). The
filter+fill freeze is unaffected. cam2's result stands as evidence of the
mechanism's value where recall is broken (9.1→3.5, the corridor's worst
camera to under-bar), not as a shippable config.** Next mechanism
iteration, if pursued: a CONSERVATION design — additions budgeted against
an expectation the truncated-allocation census cannot currently provide —
which is its own plan-doc + ablation cycle, not a patch on this freeze.

## Risks named

- **Popularity snap:** supports-weighted posteriors could funnel unevidenced
  tracks into high-volume cells wholesale — the shape-residual term and the
  existing admission gates must keep candidates geometric first; watch
  per-cell precision on the fit window, not just |err|.
- **Flag flood:** flat posteriors → origin_ambiguous storms; flood control
  + the stage-4 queue-size check gate it.
- **cam1 botsort+reid birth behavior** differs (parent-plan risk, still
  open) — the sweep decides, not cam2 intuition.
- **cam3's dtw_mean pinned recipe** meets the tie band — tripwire cell,
  byte-stable expected when untied.
- **Circularity guard:** expecteds re-discovery must come from gate
  evidence, never from the posterior's own output (no self-licking loop).

## Out of scope

The never-journeyed 585 (capability track); detector fine-tune lane; any
turn-merge THRESHOLD change (only the expecteds' source moves); Wall C
mechanism ② (watched at the sweep instead — see stage 6).

## Ops

Ablations detached with logs + resume; no repo `.py` edits while a server
job runs; scorers (`measure_cam2_reid_spike`, `triangulate_manual`,
`interval_metric`) remain the only GT readers. Artifacts: reuse
`ic_scratch_97a7849a` naming (`posterior_cam2_<variant>.db`).
