# Handoff — V2 campaign state after the APPLY-GATE block (2026-08-07, second session)

Everything committed on `claude/accuracy-impl-2026-05-27` (NOT pushed; 12
commits ahead of origin after this block's five). 919 tests green.
Production counted tables untouched; V2 mechanism flags still default
OFF; APPLY_GATE default ON (product architecture, env kill-switch).

## Where the campaign stands (one paragraph)

The operator's bar: reach/exceed Miovision under an independent manual
referee, on 640x480, no footage upgrade (MASTER_PLAN §2e). Blocks 1+2
built the V2 harness, shipped three measured-safe mechanisms behind
default-OFF flags (endpoint extension, census-dosed claim demotion +
contrast guard + base census, merge rescue), and proved the
APPLICABILITY LAW on 11 blind windows: the bundle wins where journeys
are missing, loses where completion manufactures them. THIS BLOCK
(plan_v2_apply_gate_2026-08-07.md) made the law mechanical: the Phase-1
APPLY GATE — per-window candidate-vs-incumbent adjudication under the
blind guards (headroom vs gate-evidence census / per-cell flood envelope
/ saturation contrast / covered-mass recovery, h=3% F=15% sat=0.25) —
is wired into run_pass2/apply as product architecture and adjudicated
ALL 11 blind validation windows correctly (12/12 incl. the cam2 dev
window) through the shipped code path, zero Mio in the gate
(runs/v2_week1/apply_gate_validation.json). Dispositions are product
state (hold / force_once + apply_adjudications audit trail — uniform
apply can no longer overwrite curated judgment), and the schema-drift
bug is fixed (sidecars fingerprint the vehicle_events schema; int2's
Error card cause closed).

## THE NEXT BLOCK (start here): FM51 held-out adjudication

The gate's h/F constants were placed in measured gaps of the corridor
validation set — in-sample by construction (disclosed in the plan doc).
The pre-committed out-of-sample test: FM51 (held-out site, cam2 of
project 0acb12c0, zero corridor knowledge):
- Produce control + v2c candidate working DBs for FM51's window(s)
  (same recipe as the G-A3 sweep: run_pass2 in scratch, extension via
  scripts/v2_extend_dump.py, flags per the frozen bundle).
- Run the gate offline (scripts/v2_apply_gate_validate.py pattern,
  record=False) BLIND, then score both sides (scripts/v2_score_dev.py)
  to check the verdict.
- Gate correct at FM51 -> the apply gate's constants survive their first
  out-of-sample site; then the OPERATOR decisions unlock: bundle-rides-
  the-gate corridor re-process (cam2+cam3 apply, cam1/4/5 stand down,
  safe by construction) and G1-closure (re-run the 07-31 blind product
  test verbatim; product must reproduce >= curated scores cold).

## Operator decisions open

1. Push the branch (12 commits local-only).
2. V2 flag posture: default-OFF until FM51 validates the gate
   out-of-sample; after that, flag-ON + gated re-process is
   safe-by-construction (recommendation in the plan doc's verdict).
3. Blind-run rollback (2026-08-01 tables in production; backups in
   data/projects/97a7849a/backups/) — partially superseded: any future
   candidate now adjudicates; cam3's V2 result (72.6) exceeds both prior
   states and awaits the gated re-process.
4. FM51 sweep scheduling (the next block's long pole — pass-1 dump +
   2 pass-2 runs on a fresh site).

## Mechanics for the next session

- Docs chain: MASTER_PLAN §2e (authoritative) -> plan_v2_week1_verdict
  -> plan_v2_block2_2026-08-06 -> plan_v2_apply_gate_2026-08-07 (this
  block, verdict incl.) -> this handoff.
- The gate: backend/services/apply_gate.py (pure rule + orchestrator);
  census inputs via two_pass.gate_census_inputs (base-dump principle);
  wiring in _gated_finish_apply (both fresh and reuse paths); S5-union
  filters to applied windows (routers/two_pass.py). Dispositions +
  audit: backend/database.py (get/set_disposition, record/
  list_adjudications).
- Constants: config.APPLY_GATE_HEADROOM 0.03 / _FLOOD_MAX 0.15 /
  _SATURATION 0.25 (shared with demotion's contrast guard);
  APPLY_GATE=0 env reverts to unconditional apply.
- Validation harness: py -X utf8 scripts/v2_apply_gate_validate.py
  (11/11 binding + 12/12 recorded; exits 1 on any binding miss).
- Scratch evidence set: _replay_scratch/v2_week1 (12 DB pairs + stats
  sidecars; cam2 incumbents are demotion-standalone tables — sidecars
  record doses; ground truth = committed runs/v2_week1/score_*.json).
- Flags: V2_DEMOTION / V2_MERGE_RESCUE / V2_TIMELOCAL (dead) — env, all
  default off; TWO_PASS_ENABLED default on (product).
- Run pattern for long jobs: Start-Process detached + log file + Monitor
  (backgrounded tool tasks get reaped; detached survives).
- ortools is DEV-ONLY (numpy must stay 1.26.4 — the 2.5 incident).
- A stale server may hold port 5000 — kill by command-line match before
  serving fresh.
- Dev scoring: scripts/v2_score_dev.py <working.db> (the only Mio
  reader); py -X utf8 always (cp1252 console).
