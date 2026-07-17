# Methodology Research — Closing the Sunnyvale Accuracy Gap

**Date:** 2026-05-26
**Camera:** Sunnyvale TX, NBeltLineRd-NorthwestDr, project `97a7849a`, camera 1
**Status:** Research complete. Implementation deferred for future work.

This document logs the findings of a multi-agent research session (Claude + Grok)
investigating why the per-(leg, movement) accuracy at Sunnyvale is much worse than
the "92% recall" headline suggested, and what methodologies the literature + industry
recommend for closing the gap. The synthesis at the end is the actionable roadmap.

---

## 1. Diagnostic baseline (verified 2026-05-26)

The "92% accuracy" metric was misleading. `groundtruth.py`'s per-leg recall cancels
offsetting errors. A proper per-(origin_leg, movement) Σ|Δ| / total_manual metric
was built at `scripts/per_movement_accuracy.py` and run against the pre-fix DB state.

**A1 baseline:** **94.58%** aggregate per-cell error.

Worst cells (Δ vs manual):

| Cell | Manual | Ours | Δ |
|---|---|---|---|
| L22 thru | 5,687 | 896 | **-4,791** |
| L23 thru | 5,509 | 3,419 | -2,090 |
| L25 left | 271 | 1,724 | **+1,453** |
| L22 right | 330 | 1,348 | +1,018 |
| L22 left | 3 | 1,010 | +1,007 |
| L23 left | 788 | 36 | -752 |
| L25 right | 895 | 263 | -632 |
| L24 right | 3 | 526 | +523 |
| L24 left | 18 | 269 | +251 |

**Decomposition** (validated via `scripts/audit_tier_breakdown.py`):

- **~4,000 phantom L22/L25 lefts/rights** flowed via **Tier-0 polyline** (99–100%).
- **~600 phantom L24** flowed via **Tier-2 heading fallback** (73%).
- **~3,800 events missing pre-attribution** (L22+L23 throughs) — detection or
  tracking loss before vehicle_events were written.

**Key structural finding from B3 investigation:**

Stored movement labels are **100% consistent** with `derive_movement(origin, destination)`
— labels aren't wrong. The bug is **wrong destination attribution** (994 of 1,012
L22→L24-labeled events shouldn't be L22→L24 at all; they're SB throughs that the
polyline matcher mis-bucketed).

Why this happened: polyline tangent-based labeling is **structurally broken at this
camera**. Vehicles enter YOLO's view *mid-turn*, so the polyline's "entry tangent"
already reflects turn state, not approach direction. `derive_path_movement`
(`scripts/auto_calibrate.py:329`) assumes entry tangent = approach direction;
that assumption fails here.

---

## 2. Interim Stage A fix (currently in code, validated by replay)

Three bundled changes were applied to production code on 2026-05-26 and validated by
replaying all 9,785 existing trajectories under the new logic:

| File | Change | Constant |
|---|---|---|
| `backend/config.py` | Added `HEADING_FALLBACK_EXCLUDE_LABEL_KEYWORDS = ("Driveway",)` | new |
| `backend/config.py` | Added `ORIGIN_POLYLINE_HEADING_GATE_DEG = 25.0` | new |
| `backend/services/origin_detector.py` | `score_origin_by_polyline` rejects matches where polyline's avg first-3-segments bearing differs from track's by >25° | new |
| `backend/services/trajectory_classifier.py` | `score_destination_by_polyline` default `max_avg_distance_px` 40 → 20 | tuning |
| `backend/services/pipeline.py` | Tier-2 heading fallback skips legs whose label contains "Driveway" | new |

**Replay measurement (Stage A combined, ablation in `scripts/replay_attribution_changes.py`):**

- A1 baseline: 94.58% per-cell error
- All 3 changes: **69.88%** per-cell error (**-24.7pp**)
- Per-change contribution (paired): dest radius ~16pp, L24 heading-exclude ~10.6pp,
  heading gate ~10pp

**Known regression:** L25 right is *under*-attributed (27 vs manual 895) in replay.
The heading gate is too aggressive for L25's polylines specifically. The
recommended methodology replacement (section 5) makes this gate obsolete.

**Status of DB:** the Stage A reprocess deleted the original 9,785 events; only the
7:00 AM 15-min bucket (141 events) remains. Trims restored to original AM+PM peak
windows. Re-running balanced-mode end-to-end requires an overnight job (~8–11 hours).

---

## 3. Research synthesis — 3 parallel streams converged

Three research streams ran in parallel:
1. Claude agent on **CPU-only detection + tracking SOTA**.
2. Claude agent on **trajectory / map-matching methodology**.
3. Grok on **commercial product survey + industry traffic-counting practice**.

### Convergent findings (independently reached by all 3)

1. **Don't trust entry tangents at this camera.**
   - Stream 2: "trajectory starting mid-turn is just a short HMM observation prefix" — match by polyline shape, not by entry direction (Newson & Krumm 2009 HMM map-matching).
   - Stream 3: "stopbar trimming + representative paths" — discard pre-stopbar portion entirely (Jana et al. 2021, arXiv:2111.09171).
   - Stream 1: detection happens late in FOV, entry tangents inherently unreliable.

2. **Tracking-by-detection with motion-gap recovery beats raw detection improvements.**
   - Stream 1: OC-SORT (virtual trajectories extrapolated through gaps) recommended.
   - Stream 3: ByteTrack/BoT-SORT + Kalman buffering + short-gap linear interpolation; this is dominant in production traffic counting.
   - Same failure mode targeted: 1–3 frame YOLO drops fragmenting tracks.

3. **Trajectory shape matching > pointwise distance.**
   - Stream 2: partial Fréchet (Buchin et al. 2009).
   - Stream 3: min-Hausdorff + angle similarity + end-proximity (Jana 2021, Vasu 2021).
   - Both compute sub-curve similarity; both handle partial trajectories naturally.

### Commercial / industry context (from Grok survey)

Public disclosures are limited but consistent themes:

- **Miovision** (Scout/One/Detection Pro): proprietary CV/ML, heavy human-in-loop QA, claims 95–99% TMC accuracy. Trajectory database + homography output.
- **GoodVision**: DL detectors + MOT + trajectory clustering, configurable zones/lines. 95–99% counts in case studies. Closest in philosophy to what we want.
- **Vivacity Labs**: edge DL + RNN trackers, ~97% classification (TfL validated). Path/desire-line emphasis.
- **Iteris** (Vantage Apex/Vector): AI video + radar fusion. >99% detection claims with sensor fusion.
- **Q-Free / Kapsch**, **FLIR Trafibot**, **Citilog**: trajectory + 3D reconstruction + DL.
- **Wavetronix**, **Ouster**: radar / LiDAR (out of video scope but prove trajectory-first value).

**No vendor publishes full algorithms.** All commercial systems use
trajectory-first + data-driven shape matching + heavy QA. None rely on
orthogonal-leg or entry-tangent assumptions.

**Direction validated:** moving away from tangent-based labeling toward
shape-matching is the industry-aligned path.

---

## 4. Recommended methodology replacement

### Layer 1 — Detection / tracking (closes the ~3,800-event detection-loss gap)

**Adopt:** OC-SORT (or BoT-SORT) tracker swap + Kalman-buffered short-gap interpolation
+ detection cache (Parquet keyed by `(camera_id, video_hash)`).

**Why:**
- ByteTrack (current) has no motion extrapolation through detection gaps.
  OC-SORT's "virtual trajectory" re-associates tracks across the 1–3 frame
  YOLO drops that dominate our L22/L23 through losses. Same CPU cost as ByteTrack.
- Detection cache decouples detection from tracking from attribution — future
  attribution experiments run in **minutes instead of hours**. MOT17/20 convention.
  Detector outputs are persisted; trackers consume them with `--detections` flag.
  Implementation: write per-frame detections to Parquet (frame_idx, bbox, conf, class).
  ~24M rows for 30 FPS × 11 hours × 20 detections/frame; Parquet+zstd <1 GB.

**Effort:** Small (2–4 hours). Drop-in replacement using `boxmot` or `trackers` PyPI.

**Expected impact:** Recover 1,500–2,500 of the 3,800 lost events. 50–100× faster
iteration on attribution logic.

### Layer 2 — Attribution (closes the ~2,000-event misattribution + L25 regression)

**Adopt:** Replace `score_origin_by_polyline` + `score_destination_by_polyline`
with a **single joint partial-Fréchet scorer** over the unified path bank.

**Algorithm sketch (target replacement for `backend/services/trajectory_classifier.py`):**

```python
def score_path_joint(trajectory, paths, *, max_dist_px=25.0,
                     min_coverage_frac=0.40, tail_window_pts=8):
    """For each candidate path polyline:

    1. Partial Fréchet: sliding window over polyline arc-length, return
       min Fréchet between full trajectory and best polyline sub-curve.
    2. Length-coverage penalty: prefer paths whose matched sub-curve
       covers >= min_coverage_frac of polyline arc-length (rejects tracks
       that match a tiny segment of multiple paths).
    3. Tail-direction prior: cosine similarity between trajectory's
       last-window heading (last tail_window_pts points) and the
       polyline's EXIT-segment tangent. Tails are the trustworthy
       signal at this camera; entry tangents are not.
    4. Tie-break by supporting_count (more-observed paths win at ties).

    Returns: (origin_leg_id, destination_leg_id, movement_label, path_id)
    All four read from the chosen path's stored fields — origin is never
    separately estimated. Eliminates the entry-tangent dependency entirely.
    """
```

**Why this is the right replacement:**

- Partial Fréchet finds the best matching sub-curve of the polyline against
  the trajectory. A track starting mid-turn matches the *middle portion* of
  the polyline — the missing approach portion doesn't contribute to the cost.
- Origin is **read off** the winning polyline's stored `origin_leg_id` field —
  never estimated from the unreliable entry tangent.
- Tail-direction prior replaces my heading-consistency gate (which caused
  the L25 regression). Tails are stable at this camera; entries are not.
- Single decision point. Eliminates the cascading error between origin and
  destination tiers.

**Reference implementation:**
- `similaritymeasures` PyPI for Fréchet, DTW, partial-Fréchet variants
  (https://pypi.org/project/similaritymeasures/)
- `frechetdist` PyPI for the classic algorithm.
- Partial-Fréchet variant: O(nm) free-space-diagram with arc-length parameter
  sweep over the polyline; ~30 lines of custom code on top of the library.

**Cost:** With 9,800 tracks × 12 paths × 50 points ≈ 60M cell evaluations
total, well under 1 second in numpy.

**Effort:** Small–medium (4–8 hours implementation + tests).

**Expected impact:** The 24.7pp aggregate reduction from the Stage A patch is
likely a floor. Joint scorer should push per-cell error below 50% on existing
trajectories — replay-testable in minutes once the detection cache exists.

### Cross-cutting — Wall-clock acceleration (orthogonal, high daily-ops value)

**Adopt:** OpenVINO FP16 + INT8 export with Iris Xe iGPU offload for YOLO.

**Realistic stack:** PyTorch → OpenVINO FP16 (~3×) → INT8 (~1.8×) → iGPU offload
(~1.2×) ≈ **6–7× end-to-end** at 960 imgsz.

**Effort:** Medium (4–8 hours, Ultralytics has one-line export + documented
OpenVINO inference path).

**Expected impact:** Full-day balanced-mode reprocess goes from 11 hours to ~2 hours.

### What to discard from Stage A when adopting the above

- **25° heading-consistency gate** in `score_origin_by_polyline`: obsolete with
  partial Fréchet and over-aggressive on L25.
- **L24 heading-fallback exclusion**: joint shape matching handles low-volume
  legs naturally (no observed trajectories → no path → no false match).
- **20px destination radius**: partial Fréchet uses sub-curve match cost
  threshold; no radius needed.

The Stage A changes were a **defensible intermediate** but the methodology
replacement is more principled and should fully supersede them.

---

## 5. Implementation roadmap (when ready)

Suggested sequence with effort estimates:

1. **Detection cache + OC-SORT tracker swap** (small, 2–4 hrs).
   - Persist YOLO detections to Parquet keyed by `(camera_id, video_hash)`.
   - Wire OC-SORT (`boxmot` or `trackers` PyPI) as tracker; pass cached
     detections in.
   - Adds new infrastructure; backwards-compatible (ByteTrack path remains).
   - Validates by recovering 1,500+ L22/L23 throughs in a single re-run.

2. **Partial-Fréchet joint scorer** (small–medium, 4–8 hrs).
   - Implement in `backend/services/trajectory_classifier.py` as new
     `score_path_joint` function.
   - Wire into `pipeline.py:_assign_origin` and finalization, replacing the
     separate origin + destination Tier-0 calls.
   - Replay-test against current vehicle_events first (no reprocess), then
     full reprocess to validate end-to-end.
   - Remove or feature-flag the Stage A heading-gate / radius-tighten /
     L24-exclude changes.

3. **OpenVINO acceleration** (medium, 4–8 hrs).
   - Export `yolo26s.pt` and `yolo26l.pt` to OpenVINO FP16 then INT8
     (NNCF/POT calibration on a 1-hr Sunnyvale sample).
   - Modify `backend/services/detector.py` to load OpenVINO model when
     available; PyTorch fallback for environments without OpenVINO.
   - Smoke-test for detection-rate parity vs PyTorch.

4. **Final validation** (overnight + measurement, 12 hrs).
   - Balanced-mode end-to-end reprocess on full Sunnyvale 11-hour video
     (after step 3 this should be ~2 hours).
   - Run `per_movement_accuracy.py --diff A1_baseline`.
   - Report final per-(leg, movement) accuracy.

**Total methodology-replacement effort:** ~10–20 engineering hours.

**Out of scope but worth flagging for multi-intersection rollout:**

- **Hierarchical trajectory clustering** (Jana et al. arXiv:2111.09171, Vasu et al.
  arXiv:2108.07135) for auto-calibration without hand-drawn polylines. Grok's
  estimate: 160–320 hours. Worth investing for the next intersection rollout but
  not for closing the current Sunnyvale gap.
- **Active learning / YOLO fine-tuning** on Sunnyvale-specific frames to improve
  small/distant vehicle detection. Requires labeled data + training infra.

---

## 6. Key citations

### Map-matching from partial trajectories
- Newson & Krumm 2009, "Hidden Markov Map Matching Through Noise and Sparseness."
  https://www.ismll.uni-hildesheim.de/lehre/semSpatial-10s/script/6.pdf
- Lou et al. 2009, ST-Matching algorithm (handles spatial-temporal feasibility).

### Trajectory similarity / partial matching
- Buchin, Buchin, Wang 2009, "Exact Algorithms for Partial Curve Matching via the
  Fréchet Distance," SODA. https://epubs.siam.org/doi/abs/10.1137/1.9781611973068.71
- Wang et al. 2020, "Vehicle Trajectory Similarity: Models, Methods, and Applications,"
  ACM CSUR. https://dl.acm.org/doi/pdf/10.1145/3406096
- Tao et al. 2021, "A comparative analysis of trajectory similarity measures."

### Trajectory clustering at intersections
- Jana et al. 2021, arXiv:2111.09171 — hierarchical clustering on traffic
  trajectories with min-Hausdorff + angle similarity. Validated on real
  intersections (IITK + Etalyc/Dubuque).
- Vasu et al. 2021, arXiv:2108.07135 — auto-ROI + k-means clustering on
  start/end/delta features. 17.4% MAE on AICity subset.
- Lee, Han, Whang 2007, "Trajectory Clustering: A Partition-and-Group Framework"
  (TRACLUS), SIGMOD. https://hanj.cs.illinois.edu/pdf/sigmod07_jglee.pdf
- TRACLUS Python: https://github.com/AdrielAmoguis/TRACLUS

### Tracking-by-detection with gap recovery
- Cao et al. 2023, "Observation-Centric SORT" (OC-SORT), CVPR.
  https://openaccess.thecvf.com/content/CVPR2023/papers/Cao_Observation-Centric_SORT_Rethinking_SORT_for_Robust_Multi-Object_Tracking_CVPR_2023_paper.pdf
- Zhang et al. 2022, ByteTrack, ECCV. arXiv:2110.06864
- Aharon et al., BoT-SORT (with camera motion compensation).
  https://github.com/NirAharon/BoT-SORT

### CPU acceleration (Intel)
- Ultralytics "3x Faster YOLOv8 with OpenVINO":
  https://www.ultralytics.com/blog/achieve-faster-inference-speeds-ultralytics-yolov8-openvino
- Raymond Lo "1000 FPS YOLOv8 with Intel GPUs":
  https://medium.com/openvino-toolkit/how-to-get-yolov8-over-1000-fps-with-intel-gpus-9b0eeee879
- Lenovo Press, "YOLO + OpenVINO on Intel Xeon 6":
  https://lenovopress.lenovo.com/lp2345-accelerating-real-time-object-detection-yolo-models-intel-xeon-6-openvino

### Intersection turn-movement identification
- Sakr & Bullock 2021, "Identifying Vehicle Turning Movements at Intersections from
  Trajectory Data," IEEE ITSC. https://ieeexplore.ieee.org/document/9564781/
- US Patent 11,915,585 — Sakr-Bullock methodology.

### Commercial product references (Grok survey)
- Miovision Scout Plus: https://miovision.com/scout-plus/traffic-studies/
- GoodVision: https://goodvisionlive.com
- Vivacity Labs: https://vivacitylabs.com/north-america/smart-traffic-monitoring/
- Iteris Vantage Apex: https://www.iteris.com/oursolutions/traffic-detection/vantage-apex
- FLIR Trafibot: https://www.flir.com/products/trafibot-dual-ai/
- Citilog: https://www.citilog.com/technology/
- Ouster BlueCity: https://ouster.com/products/software/bluecity

### Tooling / libraries to use
- `similaritymeasures` PyPI: https://pypi.org/project/similaritymeasures/
- `frechetdist` PyPI for classic Fréchet.
- `boxmot` PyPI for OC-SORT / BoT-SORT integration.
- OpenVINO via Ultralytics export (`yolo export format=openvino`).

---

## 7. Artifacts in this repo

Scripts produced during the diagnostic + Stage A work; useful for re-runs:

| Path | Purpose |
|---|---|
| `scripts/per_movement_accuracy.py` | Per-(leg, movement) accuracy metric; aggregate Σ\|Δ\|/manual. Saves snapshots to `evaluations/`. |
| `scripts/audit_tier_breakdown.py` | Tier breakdown (polyline/tripwire/heading) per (leg, movement) cell. Replays existing trajectories through pipeline-order tiers. |
| `scripts/replay_attribution_changes.py` | Replay-only test of Stage A bundled changes; supports ablation flags. |
| `scripts/auto_cal_from_db.py` | Attempted auto-calibration from existing trajectories (chained DBSCAN; superseded by partial-Fréchet recommendation). |
| `scripts/bucket_accuracy.py` | Per-bucket accuracy comparison (single 15-min bucket vs manual). |
| `evaluations/A1_baseline.json` | A1 baseline snapshot (per-cell breakdown of pre-fix state). |
| `evaluations/A2_tiers.json` | Tier breakdown snapshot. |
| `evaluations/A_combined.json` | Stage A replay-result snapshot. |

These scripts can drive subsequent measurement / regression-checking when the
methodology replacement is implemented.
