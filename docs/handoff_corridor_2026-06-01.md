# Handoff: finish the corridor (cam3–5) — intersection-counter

## Shipped today (2026-06-01), live in `data/projects/97a7849a/project.db`
- **cam1** (N Belt Line & Northwest Dr): **net 7.2% / per-min gross 18.8%** (from 21.8/30.7).
  Full BoT+ReID regime hybrid + crossing-timestamp + raw-track EB-right path. Engineer-gated.
- **cam2** (N Belt Line & E Town East Blvd): **net 21.1% / gross 38.4%** (from 26.5/41.6 baseline).
  Deadline build — bytetrack throughs + BoT merged turns + raw-track bank. 5-min sample, yolo26s cache.
- Backups: `backups/20260512_pre_reid_apply_cam1.db`, `backups/20260512_pre_cam2_hybrid.db`.

## The winning pattern (proven cam1 + cam2)
**Regime split:** good-throughs tracker ∪ good-turns tracker, + volume-gated intra-turn
merge, + a path bank whose turn polylines come from RAW tracker tracks with OD
destinations read from the camera's Miovision XML (authoritative — never hand-guess turn
geometry), + events timestamped at the ORIGIN-CROSSING frame (pipeline.py, shipped).
- cam1 (10fps): BoT+ReID throughs + BoT-motion turns (ReID solved through recall).
- cam2 (25fps): bytetrack throughs + BoT-motion turns (BoT over-counts throughs at 25fps;
  bytetrack throughs were closer). **Pick the throughs tracker per camera by measurement.**

## Two blockers to fix for a clean cam3–5 (and a cam2 upgrade)
1. **ultralytics YOLO OpenVINO-GPU detector STALLS** (low RAM, no frames; raw-OV osnet works,
   so it's ultralytics' integration). Forces CPU detection at **2.33 fps** (yolo26s@960) →
   5-min cache = 54 min, 30-min = 5.4h. Fixing this (or pre-exporting the OV model another
   way) unlocks fast, high-recall (yolo26l@1280 = `--mode accurate`) caches.
2. **Measurement/derivation/combine stack is cam1-hardcoded**, and cam2's helpers
   (measure_cam2, build_cam2_bank, apply_cam2_bank, cam2_hybrid_measure, apply_cam2_hybrid)
   are cam2-hardcoded. **Generalize to a camera parameter** before cam3–5 (cam2's OD geometry
   matched cam1's structurally; the Miovision XML gives each camera's OD map + leg positions).

## cam3–5 recipe (per camera, ~1–1.5h each on CPU)
cam3/cam4 = T-intersections (3 legs), cam5 = 4-way. All seeded (screenshots/seed_cam{3,4,5}.png).
1. **Mislabel check** (cheap): compare leg origins to Miovision approach positions + cardinals
   to approach names (cam2 passed by construction; cam3–5 likely too). See the cam2 check.
2. **Cache + baseline:** `DEVICE=cpu py scripts/reprocess_camera.py --camera N --mode balanced
   --start-hms 07:00:00 --minutes 5 --yes` (writes cache + bytetrack events).
3. **Bank from raw tracks + Miovision OD** (generalize `build_cam2_bank.py` to camera N).
4. **Hybrid + apply** (generalize `apply_cam2_hybrid.py`): measure bytetrack-thru vs BoT-thru,
   pick the better throughs; + BoT merged turns + bank. Visual-gate, then apply with backup.
5. **Verify** live project.db + Excel cardinals.

## Upgrade path to cam1-quality across the corridor (bigger, future)
Fix blocker #1 → build yolo26l@1280 caches → embedding sidecars → BoT+ReID throughs +
BoT-motion turns + merge (the full cam1 pipeline via `process_camera_reid.py`, generalized
to camera-param), 30-min windows + sub-window stability + engineer visual gate per camera.

## How we work here
Diagnostic-first, data-driven, robust (no band-aids), engineer visual gate before any
production apply, atomic backups before mutating project.db. Metric = per-minute GROSS vs
the Miovision per-minute OD (`scripts/od_accuracy.py` / `measure_cam2.py`).
