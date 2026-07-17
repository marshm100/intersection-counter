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

## Open item — cam1 blind-gate re-validation — RESOLVED 2026-07-08 (same day)

**Cache forensics first:** the on-disk `balanced_960_skip1.parquet` turned out to be
md5-IDENTICAL to the `.bak` (101,664 rows, frames 251980–269979 = the full 30-min
window, conf ≥ 0.10) — the parquet had already been restored; only its `meta.json`
was stale (it still describes the 3-min yolo26l@1280 pass, windows [252030, 253830]).
Restored the .bak as a NEW variant `balanced30min_restored` (+ correct meta.json;
`compute_video_content_hash` of the cam1 video re-verified = the cache dir hash).
The legacy ReID sidecar keys by (frame, rounded bbox), so it aligns with any
byte-identical parquet.

**Method:** `process_camera_reid.py` grew `--variant` and `--gate {gt,bank}`
(bank = `expected_by_cell` from the bank's `supporting_count` per (origin,dest) —
`evaluations/recal_cam1_odturns_ebr.json`, 13–773/cell, built over the SAME
07:00–07:30 window so no scaling needed). Both arms retracked ONCE on the restored
variant + legacy sidecar; combined TWICE (gate is the only difference); scored with
`measure_cam2_reid_spike.py --camera 1` (07:00–07:30, Miovision = scorer only).

**Numbers (07:00–07:30):**

| run | total net | per-cell abs (`_measure` net) | per-approach MAE | worst cells |
|---|---|---|---|---|
| shipped project.db (live) | −1.0% | — | 5.7% (EB 9.3 FAIL, NB 5.5 FAIL, SB 2.4) | NB-thru −53, NB-right +17 |
| rebuild, legacy GT gate | −0.4% | 6.7% | 8.3% (EB 16.7 FAIL, NB 4.8, SB 3.5) | NB-thru −42 |
| rebuild, BLIND bank gate | +2.2% | 10.0% | 4.9% (EB 6.9 FAIL, NB 4.2, SB 3.5) | NB-thru −42, **NB-left +38** |

**Verdict: no blind collapse — the honest cam1 number is ~10% per-cell (vs 6.7%
GT-gated), same class, not a box-clip-style failure.** The entire GT→blind delta is
the turn-merge volume gate: bank expected NB-left = 110 → threshold 1.3×110 = 143 >
raw 134 events → merge never fires → NB-left ships +38 over (GT expected ~96 → 125 <
134 → merge fires → −1). Turns kept 210 (GT) vs 242 (blind). The blind run's BETTER
per-approach MAE (4.9% vs 8.3%) is a cancellation artifact — NB-left's +38 offsets
NB-thru's −42 inside the NB approach total; per-cell error is strictly worse blind.
Two implications: (1) the shipped 7.2% leaned on GT only modestly, and only through
the turn-merge gate; (2) the bank-count gate's weakness is exactly the flag-queue
case — an over-fragmented turn cell just under the 1.3× threshold — a §3-B QA
feeder, not a counter redesign. NB-thru −42 (−7%) is gate-independent and is cam1-NB's
real residual (see the detector spike: NOT detection-bounded).
