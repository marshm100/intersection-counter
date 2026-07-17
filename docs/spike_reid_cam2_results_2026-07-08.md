# Results — cam2 ReID generalization spike (2026-07-08)

Plan: `plan_reid_cam2_spike_2026-07-07.md` (removed after execution — see git history).
Question: **does the proven cam1 BoT+ReID recipe close cam2 per-approach WITHOUT
per-camera GT tuning?**

## VERDICT: FAIL — but the blocker is ATTRIBUTION, not tracking

The cam1 recipe unchanged makes cam2 dramatically worse (net −4.5% → ~−21%). A
ByteTrack control on the same bank shows the collapse is caused by the
**drawn-direct bank's channel attribution**, not by BoT-SORT or ReID: tracker
choice moves cam2 by only a few percent; bank choice moves it by ~15 points.
The spike premise ("drawn-direct = best cam2 attribution, so it isolates
tracking") was false at the event level.

## The 2×2 that isolates it (cam2, 07:00–07:30 vs Miovision)

| tracker + bank                              | net    | SB-thru | SB-right | WB-thru | NB-left | EB-right | EB-thru |
|---------------------------------------------|--------|---------|----------|---------|---------|----------|---------|
| ByteTrack + live bank (= live baseline)     | −4.5%  | −43     | +31      | −2      | −66     | +31      | −27     |
| ByteTrack + drawn-direct (CONTROL)          | −18.5% | −187    | −50      | −37     | −48     | +60      | −11     |
| BoT motion + drawn-direct (arm)             | −20.8% | −198    | −56      | −38     | −35     | +57      | −10     |
| BoT+ReID + drawn-direct (arm)               | −18.3% | −182    | −53      | −39     | −42     | +74      | −10     |
| full recipe, GT gate fixed (final combine)  | −20.8% | −182    | −56      | −39     | −35     | +30      | −10     |
| full recipe, blind bank-count gate          | −18.7% | −182    | −56      | −39     | −35     | +57      | −10     |

Per-approach AVG |err| per 15-min interval (final combine, fixed GT gate):
EB 20.6 / NB 5.2 / SB 55.2 / WB 37.0 [all FAIL except NB] — vs live baseline
EB 12.7 / NB 9.1 / SB 8.1 / WB 9.3. The ByteTrack+drawn-direct control has
NB at 3.3% (PASS) — NB attribution is fine; SB/WB attribution is broken.

## Findings

1. **Drawn-direct attribution loses ~60% of SB throughs** (123–128 events vs
   Miovision 310; the live bank matched 267 on the same detections + tracker).
   SB-right and WB-thru fail the same way. The missing vehicles produce NO
   event at all (no rejected rows, no NULL destinations) — their tracks match
   no channel. The bank's own QA foreshadowed it: raw supports SB-thru 187/310,
   SB-right 24/80, agreement_rate 0.409.
2. **ReID is neither the failure nor the cure on cam2.** Motion-only BoT
   collapses identically; ReID recovers just +16 SB-thru / +13 NB-thru events
   over the motion arm (cam1: 21.8→7.2% net). Nothing here says ReID is wrong —
   it says cam2's error doesn't live in track association.
3. **EB-right ~2× over-count (occlusion double-count) is tracker- and
   bank-independent** (+57…+74 raw everywhere; live +31). The shipped recipe
   only "fixed" it by consuming Miovision in the volume-gated merge: GT gate
   pulls it to +30, the blind bank-count gate leaves +57. The cam1 headline
   number owes part of its turn cleanup to a GT runtime dependency.
4. **Harness bugs found & fixed** (commit 9490361) — the real generalization
   payload of the spike:
   - `od_accuracy.leg_idx()` was 180°-flipped for every camera (N side → 'NB'
     approach instead of SB). Never bit cam1 (hand-built LEG_IDX everywhere);
     silently poisoned every cam≠1 use of `manual_od_by_cell()` (volume gate)
     and `_measure()`. Post-fix `leg_idx(1) == LEG_IDX` (verified mapping).
   - `combine_regimes()` hardwired Miovision as merge-gate expecteds; new
     `expected_by_cell` param takes the bank's `supporting_count` (the
     documented production path) — blind deployment cannot ship without it.
5. **Count sanity / fragmentation:** all drawn-direct variants under-produce
   events (1,098–1,133 vs 1,387 real); no net fragmentation inflation. The
   sidecar embed pass (580,094/580,094 embeddings, 100% lookup hit rate) and
   the CMC fix behaved exactly as designed — Phase 1/2 infrastructure is sound.

## Decision (per the plan's FAIL branch)

- **Do NOT roll BoT+ReID out as the cam2+ default** — it does not close the
  per-approach gap and adds NB-right/SB-uturn phantoms (+14 each).
- **Pivot to lever ② — coverage-aware attribution** (box-clip with shape /
  (s,d) matcher, MASTER_PLAN §2b). cam2's per-approach error bottoms out in
  channel MATCHING of far-field truncated tracks, which is exactly what
  lever ② addresses. The tracking stack (ByteTrack, even) is not the
  bottleneck on cam2.
- Before ANY "blind deployment" claim for the cam1 recipe: swap the merge
  gate to `expected_by_cell` = bank supporting counts and re-validate cam1 —
  its shipped number partially leans on GT via the old gate.
- Keep the ReID sidecar + `--resume`/`--threads` infra: cheap to rebuild,
  proven correct, and lever ② work benefits from clean long tracks for QA.
