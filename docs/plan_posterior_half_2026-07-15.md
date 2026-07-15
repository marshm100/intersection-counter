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
