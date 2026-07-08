# Gate B — box-clip blind generalization sweep: FAIL (2026-07-08)

Frozen constants (time-based, cam2-validated), each camera's LIVE applied bank,
operator calibration only, 07:00–09:00, scored per-approach vs Miovision with
the same harness throughout. No per-camera anything.

## Verdict table (per-approach MAE / net)

| cam | box-clip blind | live baseline (same window) |
|-----|----------------|------------------------------|
| 1   | 35.9% / −46.6% | 8.7% / −6.1% |
| 3   | 53.6% / −52.4% | **3.2% / +0.8% PASS** |
| 4   | 16.4% / −15.4% | **4.6% / +3.7% PASS** |
| 5   | 17.8% / −16.6% | 8.7% / −0.5% |
| 2   | 17.4% / −4.7%  | 9.8% / −4.5% |

**Box-clip does not generalize as a replacement counter.** Its cam2 result
(baseline parity, NB PASS) was its best case, not representative. On cams
1/3/4/5 it undercounts 15–52% net with the same frozen mechanism that worked
on cam2 — the same class of verdict that killed the ReID rollout, caught the
same way: blind, before any product wiring. The B-series' per-cell forensics
(chaining, lane posterior, phantom guards) remain valid mechanisms, but the
gate+attribution implementation is camera-shaped in ways two hours of one
camera could not reveal (candidate causes, unverified: origin_zone placement
quality varies by camera; sparse live banks give poor gate orientation and few
attribution templates; 10 fps truncation geometry differs from 25 fps).

## The reframe the sweep forced (bigger than the verdict)

The LIVE pipeline on this window: cam3 3.2% PASS, cam4 4.6% PASS, cam1 8.7%,
cam5 8.7%. The per-approach accuracy crisis is CONCENTRATED — cam2 (9.8%,
worst cells SB/EB) and single cells elsewhere (cam5-EB 17.5%, cam1-NB 13.3%)
— not corridor-wide. Priorities shift accordingly:
1. cam2's residual is detection-bounded in its worst cells (SB-right 58%
   recall diagnosis) → the §3-D detector workstream is the lever there.
2. Box-clip's salvage value is as the §3-B BLIND QA SIGNAL, not a counter:
   two independent GT-free counters (live pipeline vs box-clip) disagreeing on
   a cell/interval is exactly the "suspected gap" feeder the flag queue needs
   — on cam2 it would have flagged SB-thru and EB-right precisely.
3. Two-pass architecture (MASTER_PLAN 2c) stands: pass-1 dumps are now built
   for all 5 cameras; pass-2 re-runs in ~1 min per camera; every finding in
   this sweep came from that loop.

## Deploy-generalization fixes shipped during the sweep
- Frame-based constants → TIME-based (cams run 10–25 fps; frozen frames meant
  different durations per camera). cam2 regression-checked identical.
- `--bank db`: pass-2 runs from the camera's live applied bank.
- Movement labels for bank-uncovered cells derived from leg geometry
  (rank-based `derive_movement`) — no cell is ever unlabeled.
- Gate fallback for a leg with NO bank channels (cam1's zero-traffic driveway
  leg): orientation from the operator's reference_heading.

## Open item — cam1 blind-gate re-validation (BLOCKED, needs a decision)
The shipped cam1 7.2% leans on Miovision through the old merge volume-gate.
Re-validating blind requires retracking cam1's arms, but cam1's
balanced_960_skip1 cache was REPLACED at some point with a 3-minute window
([252030, 253830]); the original 30-min cache survives only as
`balanced_960_skip1.parquet.balanced30min_*.bak`, and the ReID sidecar npz
was built against THAT. Options: restore the .bak alongside (new variant
name), or build a fresh sidecar for study_0700 (hours, CPU). Not done in this
session — flagged rather than silently skipped.
