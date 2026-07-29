# Handoff — 2026-07-29 Stage-5/6.1 block (phantom class + the authorized
LEC2 judgment; 5.1 COMPLETE, 5.2 ANSWERED NEGATIVE, 6.1 DONE)

Same session as the Stage-2/3 blocks (handoffs of the same date).
Everything on `claude/accuracy-impl-2026-05-27`, committed + pushed.
874 tests green (+2). Plan docs: `plan_stage5_phantom_2026-07-29.md`
(the block's full record), runbook §0b (6.1). Production queue GREW by
17 echo_suspect flags (743 open; reversible: `python
scripts/echo_suspect_backfill.py --revert`). No replays re-derived; no
server left running; production counts untouched.

## What happened, in order

1. **6.1**: qualifying-footage spec in the runbook (§0b) — five hard
   requirements, each traced to a measured wall; procurement guidance
   for the URGENT [OP] 6.2; the star rating named as the automated
   check.
2. **5.1 supersession recorded**: the checklist's blanket item predated
   the LEC2 deliverable sweep by hours; blanket = measured dead,
   refused re-litigation.
3. **5.1A/B inventory** (production basis): post-review CEILINGS
   97.6/96.5/100.0/91.3/92.8 — recall, not labor, binds the claim;
   cam4 = one cell (SB-right phantom, under-caught because phantoms
   are high-confidence). LEC2 improves/closes every phantom CELL in
   the sweep evidence (replay basis, named).
4. **5.1C echo_suspect feeder** (operator "go"): census per-cell echo
   detail (CENSUS_VERSION 3) + tier-C-only S6 feeder + production
   backfill (17 flags; cam4/cam5 rows from the phase-0 replay census,
   basis recorded). **Ceilings now 97.6 / 99.4 / 100.0 / 98.8 / 95.9**
   — cam4 gate PASS (98.8 ≥ 96.5), cam2 clears the ≥99 interim bar.
   ONE breached-with-cause gate component on record: cam2 +6 cards vs
   the declared ≤3 — its three smallest pools ARE its three missed-BIG
   cells; the trim was measured at −2.9 ceiling and refused; operator
   may revert (delete cam2 echo flags with impact < 25).
   Mapping corrections on record: cam3's pools are SB/NB-thru (not
   EB-thru); cam4's 35>33 = the STAT signature (flag's expected review
   verdict: "real vehicles, dismiss").
5. **5.2 the authorized LEC2-under-5/95 judgment** (replayed-minutes
   basis, frozen constants, pre-declared gates): **SHIP SET EMPTY —
   6/6 sites FAIL the customer bar, including FM51** (its MAE 5.4→1.8
   aggregate win breaks bins: 65.4→62.9, real vehicles removed). The
   eaten-vehicle detector measured cam4's STAT trap at +1,048
   undercount exactly. cam5 = the one near-miss (63.0→76.1, failing
   only 6 new BIG bins — named future candidate, own plan if ever).
   LEC2 dead at BOTH bars; census-gated activation MOOT; the
   retirements ledger updated. Raw compliance on current footage is
   exhausted at measured-safe mechanisms.

## Where the claim machinery stands after this block

Corridor post-review ceilings: **97.6 / 99.4 / 100.0 / 98.8 / 95.9**
(cam3+cam2 clear the 6.3 ≥99 interim bar; cam1/cam4 within 1.2 pts;
cam5's residual = footage-gated undercount walls). The remaining
levers, in order of leverage: **qualifying footage (Stage 6 — operator
procurement, spec now in the runbook)**, Stage-4 UX passes (need the
operator in the loop), and the 6.3 interim rehearsal (re-run the
simulated-perfect-reviewer measurement when any of the above land).

## The operator's court

- **6.2 QUALIFYING FOOTAGE procurement — URGENT** (spec in runbook
  §0b; the star rating shows every current camera capped at ★★★★ on
  resolution alone).
- The cam2 card-bound exception: keep the 3 extra echo cards (my
  recommendation — they carry the 6.3 bar at cam2) or revert to the
  letter of the ≤3 bound.
- Studio dry-run (now: bin-card worklist + footage-rating panel +
  the new echo cards; F2/F3 first human use; screenshot owed).
- Trims for cams 3/4/5; Stage-4 scheduling when you can rehearse.

## Standing discipline (unchanged; twice more vindicated this block)

Pre-declared gates killed a wrong rule before ship (R1, Stage 2), caught
a measurement bug (Stage 3), and re-judged a celebrated win into an
honest retirement (5.2 — FM51's aggregate pass was bin-broken). Plan doc
before mechanism; negatives are deliverables; name the scoring basis
(production vs replayed-minutes vs phase-0 census bases all named,
never mixed); FM51 held-out; detached jobs via Start-Process; port-5000
discipline; replay scratch in _replay_scratch.
