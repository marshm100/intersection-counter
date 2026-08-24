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

## Verdict — G-GS-1 PASS on all three windows (2026-08-24)

| window | movement ctrl -> arm | approach ctrl -> arm |
|---|---|---|
| study_0700 | 61.9 -> **67.3** (+5.4) | 43.8 -> 43.8 |
| study_1100 | 53.3 -> **62.0** (+8.7) | 46.9 -> 50.0 |
| study_1600 | 58.4 -> **65.2** (+6.8) | 40.6 -> 40.6 |
| pooled | 57.8 -> **64.8** (+7.0; bar >57.8) | 43.8 -> 44.8 |

Population: posterior_source='gate_full' on 502/579/605 events (1,686 total)
— the vehicles whose observed exit crossing now beats the path match.

Cumulative cam2 arc, one operator session plus one ruling:
old basis 46.7 -> drawn gates 57.8 -> gate supremacy **64.8** (+18.1).

SHIP: the pending operator Confirm & process click on the Town East card now
lands drawn gates + supremacy together in production counts.

## SHIPPED (2026-08-24, operator "go for it")

Confirm & process run 1: replays computed, **apply gate stood down all three
windows on no_headroom** — it is a VOLUME gate (incumbent within 3% of census)
and supremacy improves ATTRIBUTION at equal volume, structurally invisible to
it. Resolution: the designed operator mechanism — disposition **force_once**
on cam2 study_0700/1100/1600 (noted with the G-GS-1 PASS citation) — then
Confirm & process run 2: **applied: true x3**.

Verified in production after apply:
- production score = the arm exactly: movement 67.3 / 62.0 / 65.2,
  approach 43.8 / 50.0 / 40.6
- posterior_source='gate_full': 1,686 events
- events total 97,109 -> 96,421 (cam2 17,078 -> 16,448: the apply replaced
  the pre-gates cam2 window events wholesale with the new-basis set — fewer,
  better-attributed events; turn-merge/dedup differences absorbed the delta)
- force_once consumed: all three dispositions back to 'auto' (the volume gate
  guards again)
- pre-ship restore point: backups/project_20260824T040724_pre_ship.db

Lesson ledgered: attribution-improving applies will ALWAYS stand down at the
volume gate; force_once with a measured pre-registered PASS is the intended
route. Candidate future work: teach the gate a movement-bar headroom term.
