# Track Repair scored gate (G-TR-1) — gate doc

Declared BEFORE any scored run (house gate discipline,
MASTER_ACCURACY_ROADMAP "Gate discipline"). Mechanism: the A3 splice
cutter as a dump-level repair (operator identity law, 2026-08-24: gates
cut tracking; a vehicle cannot reverse mouth-to-gate; occlusion does not
end identity, incompatible motion does). Lineage: infrastructure e8ded5a;
blanket-cut negative fd2311b; graze amendment (rev 4) 41104c6; Stage 2
direction gate + collision fix (rev 5), glue negative + default off,
455bebc. This is a DIFFERENT mechanism than the dead conservation family
(ledgered 2026-08-12): that family was subtractive event arbitration
(rejected=1 writes against counted events); this is a dump repair — the
replay simply counts the repaired tracks; no event is arbitrated.

## What is being tested

ARM = env A3_CUT_DUMPS=1, code at commit 455bebc — run_pass2 resolves the
three cam2 study windows to the a3_ CUT dumps (rev 5: graze-amended
Type-1 + pinch cuts, segment namespace 1e6+tid*10+k; CHAIN_GLUE off, so
cut-only). Geometry unchanged (drawn gates + curated paths, the shipped
basis). Supremacy ships ON, so the arm measures cuts ON TOP of supremacy
— the correct composed basis.

CONTROL = shipped production = the gatesup scores (G-GS-1 SHIPPED
2026-08-24). Valid control per the G-GS-1 precedent: the arm is
exclusively a code/flag arm on an unchanged-geometry basis. New score
JSONs self-record this control in production/production_approach.

Offline projection already on record (corrected census, 41104c6 +
455bebc): deficit cells heal (EB_left -229 -> -41 at 1600, SB_right
erased, WB_left ~0, SB_thru partial), overcount cells inflate in the
PROXY — but the proxy has no turn_merge/volume machinery; this replay is
the honest adjudicator.

## G-TR-1 (the ship gate)

- Controls (measured 2026-08-24, score_gatesup_cam2_study_*): pooled
  movement 64.8% (214/330); per-window 67.3 (72/107) / 62.0 (67/108) /
  65.2 (75/115); approach 43.8 / 50.0 / 40.6 (pooled 44.8, 43/96).
- PASS: arm pooled movement > 64.8%, AND no window more than 2.0 below
  its control (floors 65.3 / 60.0 / 63.2). Approach recorded alongside
  (secondary; the healing indicator).
- MISS: A3_CUT_DUMPS stays default-off (already is — zero revert);
  negative ledgered here + roadmap. No restore: replays are scratch-only;
  production untouched either way until Confirm & process.

## Interactions ledgered

- Cuts change gate tags per segment -> the gate_full supremacy population
  moves; report n_gate_supremacy / posterior_source='gate_full' ctrl vs
  arm (G-GS-1 convention).
- Cutting removes production's split-on-reuse double counts (measured in
  production: 95 tids carry 195 events in study_1600 alone) — a
  volume-DOWN effect concentrated in the overcounted through cells;
  report the duplicate census in the arm DB vs production.
- Demotion census self-censuses the a3_ dump (a3_ deliberately absent
  from the base-prefix strip, e8ded5a: cuts CLEAN the census).
- Volume-gate/turn_merge coupling: report merged_away +
  census/expecteds ctrl-vs-arm diffs.
- Silent-fallback hazard: A3 resolution failure logs a warning and runs a
  control replica — armed-verification (stats sidecar variant =
  a3_study_*) is a REQUIRED step before scoring.

## Procedure

1. Arm replays study_0700/1100/1600, FRESH workdir
   _replay_scratch/trackrepair_20260824, apply=False (production
   untouched), env A3_CUT_DUMPS=1, from the repo root (kin npz lookup is
   CWD-relative). Chain: runs/v2_week1/gtr1_chain.ps1. The stale glued
   a3_ dumps fail the reuse key (glue.enabled=True vs CHAIN_GLUE off) and
   rebuild cut-only in-run — wanted.
2. Verify armed: sidecar variant a3_study_*; a3_ meta rule_rev 5 + glue
   disabled + kin fitted.
3. Copy working DBs to stems trackrepair_cam2_study_* (sqlite backup
   API); score all three with v2_score_dev in one call.
4. Verdict here + roadmap changelog, commit — PASS or MISS.

## Verdict — pending

## SHIPPED — pending (operator go required)
