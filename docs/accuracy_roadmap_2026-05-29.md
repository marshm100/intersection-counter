# Accuracy Roadmap — close cam1 30.3% gross → production-grade (Grok-validated)

**Date:** 2026-05-29 · branch `claude/accuracy-impl-2026-05-27` · designed with Grok (read-only plan mode)
**Decisions (user, up-front):** overnight cache builds OK · set up OpenVINO on Iris Xe · include the hybrid tracker as escalation · stop at validated-&-ready for the engineer visual gate (do NOT auto-apply to production).

## Where we are
cam1 (N Belt Line Rd & Northwest Dr, 640×480) = **net 21.4% / per-minute GROSS 30.3%** (from a mismeasured 40.5%; corrected baseline 35.2%/43.8%). Metric = per-minute origin→dest vs the Miovision per-minute OD export. **Miovision got its counts from the SAME footage → the gap is OUR detection+tracking, an algorithm/compute gap, not a sensor limit** (mostly — Phase A tests this for the EB cells specifically).

## Residual decomposition (the 30.3%)
- **A. Missing cross-street turns** EB-right 0/36, EB-left 3/27 (~60) → UNDER-DETECTION.
- **B. Through/turn over-count** SB-thru +61, NB-left +39 (~100) → TRACKING fragments (sequential-merge unsafe; overlap-only safe but small after min_hits=3).
- **C. Phantom NB-right +44** → through-fragments mislabeled as turns (net-heading guard reverted; tail-direction guard is the right version).
- **D. Through under-count** NB-thru −40 → min_hits trimmed truncated/edge throughs.
- **E. Per-minute timing** (gross−net ~9pp) → boundary/finalization latency; ~irreducible in this metric (15-min TMC buckets wash it out).

## Honest target
Realistic floor after robust levers (single cam, no review): **~15–20% gross** (from 30.3%), with the EB cells either recovered (Phase A go) or explicitly bounded (no-go). ~8–10pp is irreducible per-minute noise vs an imperfect Miovision estimate. **Literal 0% is not the target.**

## Phases
### Phase A — Detection-recall GO/NO-GO (dominant lever; addresses A+D, shrinks B+C)
- A0 (cheap, no build): confirm the current cache's real recall (metadata is inconsistent) + probe whether the missing EB-turn vehicles are even in the detections (detection_vs_tracking_probe, validate_recall).
- A1: build a KNOWN high-recall "gold" cache for 7:00–7:30 (yolo26l@1280, conf≈0.05) [overnight OK].
- A2: predefined GO/NO-GO on the EB cells: GO if EB band recall improves >20–25% rel AND, after retrack, EB-right/EB-left gross drops ≥25–30 absolute (cells move from ~0–3 to double digits). NO-GO if flat → those EB movements are a sensor-angle/glare limit on this view → bound them / multi-cam / review (don't chase single-frame YOLO).
- imgsz 1280 on 640×480 is NOT theater (helps sub-32px objects). Full-frame SAHI IS theater here; the non-theater version is a TARGETED far-field ROI second pass on the specific EB approach — only on a GO.

### Phase B — Cheap attribution/tracking fixes (low-risk, parallel)
- Strengthen the TAIL-direction turn gate: raise turn coverage floor 0.40→~0.50 + tail_prior 0.85→~0.88 (turn paths only) in score_path_joint; add a fallback tail-heading veto in _finalize_vehicle (turn requires tail within ~60–70° of the dest-leg exit direction). Kills phantom NB-right (C). Zero risk on real turns (tail is the trustworthy signal).
- Finish the safe overlap-only ID dedup (OcSortBackend union-find, simultaneous co-located IDs only) — small but safe.

### Phase C — Hybrid tracker (escalation, only if B leaves through over-count >~15–18%)
- Run both backends on the cache; throughs from ByteTrack (no fragmentation on straight queues), turns from OC-SORT (2× recovery); cross-backend boundary dedup (movement classes disjoint → low false-merge). Prototyped in scripts/hybrid_prototype.py. Promote only if combined gross beats the better single backend clearly.

### Phase D — OpenVINO production enabler (separate track; makes daily runs tractable)
- Export YOLO to OpenVINO (FP16/INT8 via NNCF); extend VehicleDetector device seam ("openvino" path + PyTorch fallback); encode backend/precision in the cache variant name; parity-test (OpenVINO vs PyTorch detections → near-identical counts within noise). Expected ~4–7× iGPU throughput → gold-cache builds in a work session, full-day overnight (vs multi-day on CPU). ~2–4 days.

## Compute/iteration
Cache BUILD is the only slow step; everything after is `process_cached` (minutes on the 30-min window). Tier caches: "gold_high_recall" (built once per validation window, for R&D + go/no-go) vs "daily_balanced" (s@960, production). Variant name encodes (model,imgsz,conf,skip,backend); old caches stay valid for regression.

## ⚠ PHASE A0 RESULT (2026-05-29) — REPRIORITIZES THE WHOLE PLAN
scripts/probe_od_detection.py: the missing EB turns ARE in the current yolo26l@1280 cache's raw detections — EB-left(EB→SB)=24 (manual 27), EB-right(EB→NB)=22 (manual 36) — but the pipeline emits 3/0. **So bucket A is a TRACKING/ATTRIBUTION gap, NOT detection.** Better detection won't help (already detected at l@1280). Consequences:
- **Detection-recall / gold-cache / ROI-second-pass work (Phase A1/A2): NOT NEEDED for the EB turns.** Skip.
- **OpenVINO (Phase D): demoted to pure SPEED enabler** (faster builds/daily runs), no longer accuracy-critical → re-defer or do later; not urgent.
- **NEW top lever = ATTRIBUTION: derive correct EB cross-street turn paths** (EB-left EB→SB origin L24→dest L23; EB-right EB→NB L24→L22) so the joint scorer attributes the ~24/22 already-tracked EB turns instead of the derive fallback dropping them. Combine with the Phase B tail gate. This recovers the biggest bucket cheaply (cache-fast, no GPU).
- The earlier EB derivation failed (arterial-contaminated clusters dropped by gates); now armed with the OD ground truth (EB→SB ~24, EB→NB ~22) + leg geometry, cluster turns by (origin-region L24, dest-region) and emit EB paths matching the OD cells.

## REVISED sequencing
1. **EB cross-street turn-path derivation + tail gate (attribution)** — biggest cheap lever (recovers ~60). [was Phase A detection; now this]
2. Overlap-only dedup (small/safe).
3. Hybrid tracker (escalation, for through over-count B).
4. OpenVINO — speed only, deprioritized.

## (superseded) Sequencing (impact-per-effort)
A0 (now) → B (cheap, parallel) → A1/A2 (gold cache + go/no-go) → C (if needed) → D (production enabler; can start in parallel since user authorized). NEVER: full SAHI, sequential tracklet merge, unbounded imgsz, "just add compute" without OpenVINO.
