# Handoff — 2026-07-29 Stage-4 block (4.1 tally screen; 6.3 recorded)

Same session as the Stage-2/3/5 blocks. Everything on
`claude/accuracy-impl-2026-05-27`, committed + pushed. 877 tests green
(+3). Plan doc: `plan_stage4_childtest_ux_2026-07-29.md` (all four
passes pre-declared; 4.1 shipped). No server running; production data
untouched this block.

## What shipped — 4.1 the tally spot-count screen

Count-as-you-watch replaces grid-from-memory: the proposed stratified
window plays (F3 range-served stream) beside big per-movement buttons;
↑↓ selects the approach row, 1–4 count through/left/right/u-turn, Z
undoes anything, Space plays/pauses; every tap flashes its button.
- **Independence enforced by payload shape**: before save, the screen
  can only render the spot-windows payload — window bounds + the
  STATIC ~850 volume floor (the live meter is volume-only and never
  judges agreement). The dynamic extend-to-certify number depends on
  system-vs-manual agreement (leaks), so it appears only in the
  POST-SAVE report — which then shows verdict + per-approach 5/95
  rows in full.
- **The extend loop is real**: "Keep counting this window" lets the
  footage run past the original end; the saved duration grows with
  the playhead, and save is UPSERT-BY-OVERLAP (an extended window
  replaces its shorter row — no double-covered segments in the gate).
- The classic number grid stays as "Enter a paper count" (clipboard
  counts are a real use-case).
- Scripted dry-run green (propose → save → review-with-extend-note →
  extended re-save replaces → certify PASS on the synthetic site).

## Also recorded — 6.3 IS MEASURED

The interim-rehearsal gate equals the post-review ceiling the 5.1
inventory computes. Verdict on record (plan doc + MASTER_PLAN):
97.6 / 99.4 / 100.0 / 98.8 / 95.9 — PASS cam2+cam3, FAIL cam1/cam4/
cam5, residuals named footage-gated. Stage 4 does not move this
number; procured footage does.

## NEXT

4.3 cardinal wizard + auto-trims (small; retires the cams-3/4/5 trims
nag), then 4.2 one-question cards, then 4.4 traffic-light export
language. The REAL gate for all of Stage 4 = the [OP] 6.4 rehearsal —
which now has three new surfaces to exercise (bin-card worklist,
footage-rating panel, tally screen).

## The operator's court (unchanged)

**6.2 qualifying-footage procurement (URGENT; spec in runbook §0b)**;
6.4 rehearsal scheduling; the cam2 echo-card bar exception (standing
offer to revert); trims for cams 3/4/5 (or wait for 4.3's auto-trims).
