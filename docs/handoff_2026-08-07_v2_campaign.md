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

## FM51 HELD-OUT: RUN, and it changed the gate (2026-08-07, 2nd session)

The pre-committed out-of-sample test RAN (full verdict:
plan_v2_apply_gate_2026-08-07.md). Headline: **it did not validate h/F —
it found a precondition the gate never declared, plus a fail-open
defect.** At FM51 the entry gates barely engage (86%/94% of tracks never
cross one; ZERO full journeys in the PM window; blind coverage
0.031/0.012 vs the shipped 0.45 bar and the corridor's 0.43-0.49), so
the gate-evidence census is not a volume envelope there — and the gate
consumed it anyway, then fail-OPEN-applied the window it could not
measure. FM51's own AM candidate is -18.9 points, so that path was one
coin flip from shipping a real regression.

FIXED this session: census-adequacy precondition
(APPLY_GATE_MAX_OVERCLAIM = 1.0, a MEASURED bound — corridor windows sit
at -11.9%..+4.7% incumbent/census, FM51 at +371%) recorded as
`census_degenerate`, and FAIL-CLOSED by default
(APPLY_GATE_FAIL_OPEN=1 restores the old behavior). Corridor 11/11
UNCHANGED (the precondition never fires on a healthy site). FM51 is now
1/2 by outcome (the PM miss forgoes a +4.9 gain) but 2/2 by honest
reasoning — both windows now say "I cannot judge this" instead of
guessing.

## FM51 cam2 GEOMETRY: DIAGNOSED 2026-08-10 — not fixable by redrawing

Full evidence in plan_v2_apply_gate_2026-08-07.md. Short version: the
degenerate census is a SITE-SCALE property, not a calibration error. A
full journey needs 312 px of unbroken tracking where vehicles move ~36
px/s (~8.7 s); the median track lives 2.7 s / 96 px, so only 3.6% of
tracks are long enough (corridor: 41-58%). Identical across all three
detector bases on disk, so it is not a recipe artifact; endpoint
extension is the only real lever (96 -> 253 px, coverage 0.031 ->
0.197, still under the 0.45 bar). A SECOND, genuine defect was found on
the way: both arterial gates sit 78-85 deg off the travel direction
(build_gates averages channel tangents, and FM51's fan 33-89 deg), so
57-61% of vehicles drift out of the span instead of crossing — but
re-deriving orientation from reference_heading only reaches coverage
0.135 and is a wash on the corridor, so it is a separate measured block,
not a fix. Do NOT spend the next block redrawing FM51.

## THE NEXT BLOCK: an OPERATOR decision, not a scheduling one

h and F are STILL in-sample only, and the project has no processed
held-out site that CAN validate them. The options, honestly costed:

A. **Onboard a held-out site of the corridor's view class** (the only
   route to a real out-of-sample test). Needs footage where the
   intersection spans a few track-lifetimes, not ~9 s of them. This is a
   "which footage do we onboard next" question for the operator.
B. **FM51 camera 3** — NOT a cheap substitute: no legs, no channels, no
   detections at all, and it is the same road type that just failed.
   Calibration + detect + pass-1 + pass-2 for an unknown payoff.
C. **Proceed corridor-only**: keep V2 flags OFF, treat the gate as
   corridor-validated with `census_degenerate` as its honest boundary,
   and take the two remaining corridor items (bundle-rides-the-gate
   re-process, G1-closure) on that basis — accepting that h/F have no
   out-of-sample backing.

Cheap and independent of the above, worth doing either way:
- **Surface gate-evidence coverage per camera in the UI.** The number is
  already computed every run (FM51 0.031 vs the 0.45 requirement); today
  both the V2 evidence channel and the apply gate stand down silently, so
  an operator cannot tell a camera is unjudgeable.
- **Harden build_gates' orientation** (fan-spread test -> reference_heading
  fallback, or circular median): measured numbers are in the plan doc;
  needs its own pre-declared gate since it moves corridor cells too.

## Operator decisions open

1. ~~Push the branch~~ — DONE (pushed to origin 2026-08-07).
2. V2 flag posture: default-OFF still recommended — the gate protects
   the corridor, but its constants have no healthy held-out validation
   yet (see the next block).
2b. NEW: FM51's operator compass is rotated a uniform +90 degrees (leg
   labels W/E/S sit on the true S/N/E arms). Counting is unaffected —
   our turn handedness matches Miovision exactly — but a TMC export for
   that site would carry wrong NB/SB/EB/WB direction names. Worth a
   ticket; not touched by this block.
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
  _SATURATION 0.25 (shared with demotion's contrast guard) /
  _MAX_OVERCLAIM 1.0 (census adequacy); APPLY_GATE=0 reverts to
  unconditional apply, APPLY_GATE_FAIL_OPEN=1 restores pre-FM51
  abstention.
- Validation harness: py -X utf8 scripts/v2_apply_gate_validate.py
  [--project 0acb12c0] (corridor 11/11 binding; FM51 1/2 by outcome —
  exits 1 on any binding miss, so FM51 exits 1 BY DESIGN today).
- FM51 harness: runs/v2_week1/fm51_chain.ps1 (the G-A3 recipe on the
  held-out site); scratch data/projects/0acb12c0/_replay_scratch/v2_week1.
- The scorer is multi-site now (--project); the corridor path is
  byte-identical (verified by re-scoring against a committed JSON).
  FM51's leg->Mio-approach map lives in v2_score_dev.SITES, derived by
  turn handedness (see the plan doc, not guessable from cardinals).
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
