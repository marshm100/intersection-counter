# Gate supremacy scored gate (G-GS-1) — gate doc

Declared BEFORE any scored run. Follows the operator ruling of 2026-08-24
(gates are the law; docs/diag_regate_arbitration_2026-08-23.md post-mortem and
the 5/5 hand-label probe) and the demo-driven process: Stage-0/1 demos are on
the published demo page; this run is the money measurement.

## What is being tested

ARM = a CODE change only (commit d9e7c74): GATE_FULL_SUPREMACY on — a track
with observed entry AND exit gate crossings (tag='full') is classified by
those crossings; path matching may not override. Geometry unchanged
(drawn gates + curated 10-path set, the shipped basis).

CONTROL = the existing regatectrl scores (same geometry, flag effectively off
— the code predates the flag). Valid control per the E-series precedent: the
arm is exclusively a code arm.

Offline projection (no replay spent, ledgered on the demo page): EB_thru error
-70/-93/-166 -> -8/-3/-24 per window; EB_right +243/+138/+379 -> +194/+59/+250;
SB_right improves in all windows; SB_thru/EB_left worsen slightly (deficit
shuffling — those cells are short of VEHICLES, not labels).

## G-GS-1 (the ship gate)

- Controls (measured 2026-08-23): pooled movement 57.8% (188/325);
  per-window 61.9 (65/105) / 53.3 (57/107) / 58.4 (66/113);
  approach pooled 43.8% (42/96): 43.8 / 46.9 / 40.6.
- PASS: arm pooled movement > 57.8%, AND no window more than 2.0 below its
  control (floors 59.9 / 51.3 / 56.4). Approach recorded alongside.
- MISS: flip GATE_FULL_SUPREMACY default to off (one-line config revert),
  negative ledgered here + roadmap. No DB restore needed — replays are
  scratch; production events untouched either way until Confirm & process.

## Interactions ledgered

- posterior_source='gate_full' is non-NULL: the V2 demotion selector
  (two_pass.py:1120) filters posterior_source IS NULL, so gate_full events
  leave its "direct mass". V2 demotion is OFF by default — no behavior change
  this run; revisit if demotion is ever re-enabled.
- rescue_full's full-journey arm is subsumed when the flag is on (same cell,
  same labeling convention, earlier in the chain); its test is pinned to
  flag-off (test_partial_evidence.py).
- FRESH scratch workdir (gatesup_20260824): the pass-2 reuse sidecar keys on
  dump meta + calib fingerprint, NOT code version — reusing the regate workdir
  would silently serve pre-supremacy working DBs (the §6.5 stale trap, replay
  edition).

## Procedure

1. Arm replays study_0700/1100/1600, workdir _replay_scratch/gatesup_20260824,
   apply=False (production untouched).
2. Score, stems gatesup_cam2_study_*.
3. Verdict here + roadmap changelog + demo page, either way.
4. On PASS: ship = the already-pending operator Confirm & process click on the
   Town East card (one click now lands drawn gates + supremacy together);
   n_gate_supremacy counter and posterior_source='gate_full' population
   reported in the verdict.

## Verdict

(pending)
