# Phase 0 Diagnostics — Findings (2026-06-11)

Plan: docs/implementation_plan_architecture_2026-06-11.md. Window for all numbers:
07:00–07:30, Sunnyvale corridor, project 97a7849a. Tool: scripts/diagnose_fast_misses.py
(raw detection cache vs finalized vehicle_events; orphan = detection no event explains).

## 0.1 Frame-cadence audit — RESOLVED (we do NOT skip frames; the sources are slow)

- `DEFAULT_FRAME_SKIP = 3` (backend/config.py:14) is ONLY the preview/checkpoint/progress
  cadence (`process_video()` arg, used at pipeline.py:349). It never skips detection.
- Detection skipping is `detection_skip`: v3 path passes `mode_cfg["detection_skip"]`
  (intersections.py:787) = 1 for accurate AND balanced; legacy path doesn't pass it → default 1.
  Only "fast" mode skips (3). **Production detects every frame.**
- The cache variant names confirm production config: `balanced_960_skip1` — corridor processing
  ran **balanced mode (yolo26s @ 960, conf=0.10), every frame**.
- BUT: **4 of 5 cameras are 10 fps sources** (cam2 is 25). At 10 fps a 45 mph vehicle moves
  ~2 m/frame — the low-FPS association fragility from the research applies *intrinsically*,
  via the source video. Tracked-vehicle median step is 11–32 px/frame per camera; the missed
  fast movers below run 75–218 px/frame.
- ACTION (naming hazard): rename `frame_skip` → `preview_skip` in process_video()'s signature
  or document it; it cost us a wrong hypothesis already.

## 0.2 Fast-vehicle misses — CONFIRMED, mechanism = birth gate + association, NOT detection

Per camera (balanced cache, 30 min): orphan clusters that move coherently ≥3 detections and
≥100 px ("vehicle-like"; counts are upper bounds — chaining can split/merge):

| cam | dets matched to events | vehicle-like orphans | birth-gate (conf_max<0.25) | assoc/filtered |
|----:|----------------------:|---------------------:|---------------------------:|---------------:|
| 1   | 96.8%                 | 20                   | 6                          | 14             |
| 2   | 98.5%                 | **3**                | 1                          | 2              |
| 3   | 91.7%                 | **74**               | 13                         | 61             |
| 4   | 93.9%                 | 14                   | 2                          | 12             |
| 5   | 97.2%                 | 20                   | 7                          | 13             |

- **The user-observed fast vehicles exist and are detected.** E.g. cam1 07:10:05: 616 px of
  travel at 86 px/frame, conf_max 0.113 — every box in the birth-dead band
  [conf_floor, TRACKER_ACTIVATION_THRESHOLD=0.25), where ByteTrack can extend existing tracks
  but can NEVER start one. cam3 07:21:54: 437 px at 218 px/frame, conf_max 0.51 —
  birth-eligible yet still no event (association/mid-pipeline loss at extreme displacement).
- 33–47% of ALL vehicle detections sit in the birth-dead band (most belong to vehicles that
  also produced ≥0.25 boxes at some point, so they tracked) — the band is load-bearing; a
  vehicle that never pokes above 0.25 is structurally uncountable today.
- Research-predicted verdict CONFIRMED: the loss is **track birth + association**, not
  detection recall → Phase 1 (1.1 birth loosening + offline filter, 1.2 OC-SORT, 1.3 C-BIoU)
  is the right lever; Phase 5 (detector) stays optional.
- Model-size note (cam1 has both caches): the accurate-1280-L cache holds 52 vehicle-like
  orphan clusters vs balanced's 20 — the 1280-L pass sees ~2.5× more unexplained vehicle
  candidates (incl. vehicles 960-S never emitted). A detector-variant upgrade has real recall
  headroom *if* tracker fixes don't close the gap — re-measure after Phase 1.

## 0.3 Miss census vs Miovision — error composition DIFFERS per camera

Totals 07:00–07:30 (net; movement-level detail in the turn-residual map memory):

| cam | Miovision | ours | net  | reading |
|----:|----------:|-----:|-----:|---------|
| 1   | 1215      | 1199 | −16  | near-balanced; small recall + small phantom residuals |
| 2   | 1387      | 1323 | −64  | undercount with only 3 orphans → NOT recall; attribution/classification (SB-right −41 cell) |
| 3   | 1180      | 1026 | −154 | worst; 74 orphans ≈ up to half the deficit is detected-never-tracked → **prime Phase 1 target** |
| 4   | 1183      | 1270 | +87  | OVERcount — phantom/duplication side (EB-left +38 cell), recall work won't help |
| 5   | 1275      | 1289 | +14  | balanced net; compensating errors both ways |

## Re-ranking Phase 1 (per plan gate)

1. **1.1 birth-gate loosening + offline track-quality filter** — directly recovers the
   birth-dead-band vehicles (29 clusters/30 min across the corridor; structural).
2. **1.2/1.3 OC-SORT + buffered-IoU** — cam3's 61 birth-eligible-but-lost clusters are the
   association bucket; 10 fps displacement is exactly C-BIoU's case.
3. **1.5 post-pass stitching** — cam4 (+87) and cam5 phantom/fragment side; also needed to
   absorb the extra fragments 1.1 will create.
4. cam2 is excluded from recall work (clean at 98.5%) — its −64 routes to Phase 2 matcher work.
5. Phase 5 (detector swap/upscale) stays parked: detection recall is NOT the binding
   constraint at balanced-960 for tracked outcomes; revisit the 1280-L orphan gap after
   Phase 1 lands.

Artifacts: evaluations/fast_misses_cam{1..5}_balanced_960_skip1.json,
evaluations/fast_misses_cam1_accurate_1280_skip1.json (cluster lists carry video timestamps
for eyeballing in footage).
