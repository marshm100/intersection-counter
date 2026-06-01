# Handoff: finish the corridor (cam4–5 left; cam1/2/3 shipped) — intersection-counter

## Shipped today (2026-06-01), live in `data/projects/97a7849a/project.db`
- **cam1** (N Belt Line & Northwest Dr): **net 7.2% / per-min gross 18.8%** (from 21.8/30.7).
  Full BoT+ReID regime hybrid + crossing-timestamp + raw-track EB-right path. Engineer-gated.
- **cam2** (N Belt Line & E Town East Blvd): **net 21.1% / gross 38.4%** (from 26.5/41.6 baseline).
  Deadline build — bytetrack throughs + BoT merged turns + raw-track bank. 5-min sample, yolo26s cache.
- **cam3** (N Belt Line & Bluffview Dr, T-intersection): **net 9.8% / gross 13.2%** (from 116.7% baseline!).
  GPU cache (openvino, 6.7 min) → BoT-retrack-with-bank (`apply_bank.py`). Cleanest corridor cam yet.
  Note: cam3's BYTETRACK throughs were BAD (61 phantom EB-throughs from the T-stem origin-misassignment);
  BoT+bank fixed it (picked the throughs tracker by measurement, per the pattern). 5-min sample, yolo26s.
- Backups: `backups/20260512_pre_reid_apply_cam1.db`, `_pre_cam2_hybrid.db`, `_pre_cam3_bank.db`.

## The winning pattern (proven cam1 + cam2)
**Regime split:** good-throughs tracker ∪ good-turns tracker, + volume-gated intra-turn
merge, + a path bank whose turn polylines come from RAW tracker tracks with OD
destinations read from the camera's Miovision XML (authoritative — never hand-guess turn
geometry), + events timestamped at the ORIGIN-CROSSING frame (pipeline.py, shipped).
- cam1 (10fps): BoT+ReID throughs + BoT-motion turns (ReID solved through recall).
- cam2 (25fps): bytetrack throughs + BoT-motion turns (BoT over-counts throughs at 25fps;
  bytetrack throughs were closer). **Pick the throughs tracker per camera by measurement.**

## Blockers
1. **~~ultralytics YOLO OpenVINO-GPU detector STALLS~~ — RESOLVED 2026-06-01: there was no stall.**
   Full diagnostic (see below) reproduced every layer at <1 GB free RAM and the Intel-iGPU path
   works: yolo26s@960 = **~7 fps** (pipeline-faithful, 3× the 2.33 CPU baseline), yolo26l@1280 =
   1.48 fps; compile 5–8 s, no OOM. The deadline "stall" was the detector's one-time **in-pipeline
   OV export** (heavy at imgsz=1280, low RAM) plus a **silent CPU fallback** that masked it as a GPU
   stall (it quietly ran CPU-bound at 2.33 fps). Fixed: detector now (a) **never** silently falls
   back — it raises loudly if an explicit `DEVICE=openvino` can't load the GPU; (b) does **not**
   export in the hot path — export is the explicit `scripts/export_yolo_openvino.py` step;
   `reprocess_camera.py --device openvino` (now the **default**) pre-exports before the destructive
   delete. **Use the GPU for cam3–5 builds** — it's proven and ~3× faster.
   Diagnostic evidence table:
   | path | compile | fps | RAM floor |
   |---|---|---|---|
   | raw-OV yolo26s@960 GPU | 5.3s | 7.07 | — |
   | ultralytics yolo26s@960 GPU | 5.1s | 9.40 | — |
   | pipeline (det+bytetrack, cam3) yolo26s@960 GPU | — | 7.25 | 0.56 GB |
   | ultralytics yolo26l@1280 GPU | 8.1s | 1.48 | 0.33 GB |
2. **~~Stack is cam1/cam2-hardcoded~~ — RESOLVED 2026-06-01: generalized to a camera parameter.**
   The leg↔Miovision-approach map is now data-driven: `od_accuracy.leg_idx(camera_id)` joins
   `legs.cardinal_direction` (N/S/E/W) to the cardinal prefix (NB/SB/EB/WB) of the XML approach Names.
   Reproduces both hand-built tables exactly (cam1 LEG_TO_APPROACH, cam2 shim {26:0,27:1,28:2,29:3}),
   handles 3-leg T's and 4-ways. Generalized scripts (all take `--camera N`):
   - `scripts/od_accuracy.py --camera N` — the universal metric (replaces measure_cam2).
   - `scripts/build_bank.py --camera N` — raw-track + Miovision-OD bank → `evaluations/recal_camN.json`.
   - `scripts/apply_bank.py --camera N [--apply]` — BoT-retrack-with-bank (use when BoT throughs win).
   - `scripts/apply_hybrid.py --camera N [--apply]` — bytetrack-throughs + BoT-merged-turns (cam2 case).
   `parse_miovision_xml.parse/approaches/slot_labels` take camera_id (variable movement count: 9 for a
   T, 16 for a 4-way). The 5 cam2 shims were DELETED after `--camera 2` reproduced them cell-for-cell
   (21.1%/38.4%, identical bank). cam1's production path (LEG_IDX/IDX_NAME module constants) untouched.

## cam4–5 recipe (cam3 DONE; ~15 min each now — GPU cache + generalized scripts)
cam4 = T-intersection (3 legs), cam5 = 4-way. Seeded (screenshots/seed_cam{4,5}.png).
Mapping is auto (cardinal join) — no per-camera mislabel check needed; verify `leg_idx(N)` if unsure.
1. **GPU cache + bytetrack baseline:** `py scripts/reprocess_camera.py --camera N --mode balanced
   --start-hms 07:00:00 --minutes 5 --yes` (DEVICE=openvino default, ~7 min for 5 min @10fps).
2. **Bank:** `py scripts/build_bank.py --camera N` → `evaluations/recal_camN.json`.
3. **Pick the throughs tracker by MEASUREMENT** (this is the key per-camera decision):
   - `py scripts/apply_bank.py --camera N` (BoT+bank, re-attributes throughs AND turns), measure it.
   - `py scripts/apply_hybrid.py --camera N` (bytetrack throughs + BoT merged turns), measure it.
   - Apply whichever wins with `--apply` (atomic backup auto-created). **cam3 → apply_bank won big**
     (bytetrack had 61 phantom T-stem throughs); **cam2 → apply_hybrid won**. Don't assume — measure.
4. **Verify** live project.db (`py scripts/od_accuracy.py --camera N`) + Excel cardinals.

## Upgrade path to cam1-quality across the corridor (bigger, future)
Blocker #1 is gone (GPU works). Build yolo26l@1280 caches (`--mode accurate`, 1.48 fps GPU →
~3.4 h per 30-min window — overnight) → embedding sidecars → BoT+ReID throughs +
BoT-motion turns + merge (the full cam1 pipeline via `process_camera_reid.py`, generalized
to camera-param), 30-min windows + sub-window stability + engineer visual gate per camera.

## How we work here
Diagnostic-first, data-driven, robust (no band-aids), engineer visual gate before any
production apply, atomic backups before mutating project.db. Metric = per-minute GROSS vs
the Miovision per-minute OD (`scripts/od_accuracy.py --camera N`).
