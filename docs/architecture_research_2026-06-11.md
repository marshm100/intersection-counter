# Architecture Deep-Research — Is Our Approach the Best Path to ≤5% at New Sites?

**Date:** 2026-06-11
**Question:** For a fully-local TMC system, is the current architecture (YOLO26-L @1280 OpenVINO →
ByteTrack/BoT-SORT hybrid → trajectory-shape turn classification with a reference bank) the best
achievable approach for speed and accuracy, and what would let NEW intersections — with **zero
Miovision/ground-truth data** — reach ≤5% net counting error per movement at 15–30 min aggregation?
**Method:** Two research tracks. (A) Deep-research workflow: 5 search angles, 21 sources fetched,
105 claims extracted, 25 adversarially verified by 3-vote panels (20 confirmed, 5 refuted; 103 agents).
(B) Targeted agent on the fast-vehicle miss failure mode (detection/tracking under motion blur and
large inter-frame displacement).

---

## Verdict

**The architecture is fundamentally sound.** Trajectory-shape matching against per-movement
reference trajectories is the method that won the main academic TMC benchmark (AI City Challenge
2020 Track 1), beating zone/gate line-crossing head-to-head. The only non-standard piece is that our
turn bank is built from Miovision OD ground truth — every published top system bootstraps its bank
from the camera's **own unlabeled traffic** plus light human setup, so the hand-drawn-channel
direction (docs/channel_research_findings_2026-06-04.md) is the proven replacement, not a
compromise.

**However, ≤5% net per-movement at 15-min, fully automated, is not demonstrated anywhere in the
literature or industry.** Commercial "95%+" claims are aggregate-volume figures that include human
technician QA. Our current 7.2–14.6% net @30min is already within striking distance of published
SOTA — consistent with parameter sweeps having gone dry. The realistic path to ≤5% is the same one
Miovision uses: strong automation + a brief human review pass (which our review screen already
supports).

---

## Confirmed findings (3-vote adversarial verification)

### 1. The ≤5% target vs reality (confidence: high)
- Miovision's "95%+ accurate" is framed at classification/volume level; its third-party validations
  (96.4–99.5%) measure **aggregate volume or total intersection counts**, not per-movement OD
  accuracy, and explicitly include "visual inspection of video data, by a technician."
  [miovision.com/scout-plus/traffic-studies]
- AI City Challenge Track 1 scores nwRMSE on **cumulative** per-movement counts (more lenient than
  per-interval net error). The 2020 winner (Baidu, S1=0.9389) retained roughly **6–7% normalized
  counting error** on that lenient metric. (medium confidence — effectiveness back-solved, 2-1 vote)
- Best published movement accuracy: **multi-intersection cooperative track-sharing** raised correct
  movement identification from 86.67% → 95.65% ±1.55 (best site 97%) — i.e., even a heavier
  architecture than ours lands at ~4–5% average gross movement error.
  [Sensors 2023, PMC10747571] Note: that's gross per-vehicle; net-at-interval benefits from
  cancellation, which works in our favor.

### 2. Trajectory-shape matching beats zone/gates (confidence: high)
AI City 2020 winner's own ablation, same tracklets [Liu et al., CVPRW 2020, Table 3]:
- line-based (entry/exit lines): 86.44 effectiveness, 174 s
- shape-based (Hausdorff): **92.06**, 71 s
- shape-based + direction + spatial constraints: **93.44**, 71 s — the +1.4 from
  directional/spatial priors is directly analogous to our channel priors on top of shape distance.
Caveat: their line-based baseline is a simple ablation, not a tuned commercial zone system.

### 3. Building the turn bank WITHOUT ground truth (confidence: high)
No published top system uses OD ground truth. Verified ground-truth-free recipes:
- **The benchmark-winning recipe ≈ our channels approach** [Liu et al. §3.3.1, verbatim]: label
  entrance/exit line per movement → auto-collect tracklets crossing both → human picks 1–2 typical
  trajectories per movement → **hand-draw the polyline for movements with no collected tracklets**.
- **Accumulate-and-average** the site's own trajectories given only movement-direction definitions
  [Tran et al., CVPRW 2021].
- **Fully unsupervised**: stopbar auto-detection + agglomerative clustering with a purpose-built
  similarity, bootstrapped from **30 minutes of unlabeled video** per approach → 99.64–99.80%
  movement classification [Jana et al., arXiv 2111.09171 / MDPI 2023]. Caveat: single-approach
  camera views (easier than our oblique whole-intersection views); requires lane counts as input;
  measures classification downstream of tracking, not end-to-end counting error.
- **Endpoint clustering**: auto-generate movement labels by clustering trajectory endpoints, keep OD
  pairs above 1% frequency [Rezaie & Saunier, arXiv 2112.01570]. Caveat: tested on clean drone
  trajectories, not fragmented tracker output.

### 4. Trajectory matching does NOT transfer blindly across sites (confidence: high)
- Standard LSD-Hausdorff collapsed to **56.87%** where movement streams pack densely in the image;
  a similarity purpose-built for broken/incomplete vision trajectories — **min of directed Hausdorff
  distances + angle term + endpoint-proximity term** — scored 99.64/99.80% on the same data
  [Jana et al., Table 2]. Our plain-DTW channel matcher should be A/B'd against this.
- Across seven real intersections, **no single combination** of trajectory distance (DTW / Fréchet /
  Hausdorff) and clustering algorithm was consistently top-ten [Rezaie & Saunier]. A fixed matcher
  needs a per-site evaluation/QA step.

### 5. Tracker motion model is the measured headroom lever (confidence: high)
- On DanceTrack — closest public proxy to non-linear turning motion — with **identical detections**:
  ByteTrack 47.3 HOTA, OC-SORT 55.1, StrongSORT++ 55.6, **Deep OC-SORT 61.3** [arXiv 2302.11813,
  Table 2]. The gap on linear MOT17 is only ~2 points. ~7.8 points come from the motion model alone
  (no ReID, CPU-cheap); ~6.2 from ReID.
- Heavy ReID is prohibitive: adding FastReID dropped BoostTrack from 65.45 → 15.35 FPS (MOT17) and
  32.79 → 3.05 FPS (MOT20) **on an RTX 3090** [Springer s00138-024-01531-5]. On Iris Xe, only
  lightweight ReID (OSNet x0.25-class) or in-detector features are viable.
- Caveats: benchmarks are pedestrians/dancers, not vehicles; HOTA gains don't directly guarantee
  counting-error reduction. The pedestrian→vehicle transfer is the single biggest unvalidated lever.

### 6. Ground-truth-free validation is standard agency practice (confidence: high)
[Maryland SHA "Reviewing and Validating Turning Movement Counts"; corroborated VDOT/WisDOT/TxDOT/MoDOT]
- **Reverse-movement balance**: over a long count, a movement's volume ≈ its geometric reverse;
  imbalance triggers investigation.
- **Corridor consistency**: volume exiting one intersection ≈ volume entering the next downstream,
  net of mid-block access. Directly automatable across our corridor's intersection-days.
Both work with zero ground truth and would flag attribution errors per site.

---

## Fast-vehicle miss failure mode (track B)

User-observed: vehicles moving fast through the intersection are sometimes never detected/tracked.
Three stacked mechanisms, with the kill point most likely at **track birth**, not detection:

1. **Blur lowers confidence rather than eliminating boxes** — and ByteTrack **never births a track
   from a low-score detection** (low-score boxes only match into existing tracks). A vehicle blurred
   for its whole 2–5-frame transit can emit detections the entire way and produce zero tracks,
   regardless of detector conf (ours is already 0.08). [ByteTrack, arXiv 2110.06864]
2. **Frame skip attacks association first**: under aggressive frame sampling, ByteTrack fell ~62 →
   ~45 HOTA while clustering trackers held [FraMOT arXiv 2209.11404; FCG arXiv 2210.03355]. Our
   `DEFAULT_FRAME_SKIP = 3` (backend/config.py:14) makes 25 fps sources effectively ~8.3 fps and
   triples inter-frame displacement, so fast vehicles' boxes can stop overlapping entirely.
   Literature direction: **process every frame, sacrifice imgsz first** for fast large-in-frame
   targets (may invert for distant approaches — validate per camera).
3. **`fuse_score: true` (Ultralytics default)** multiplies IoU similarity by detection score —
   specifically penalizing the blurred low-score boxes we need to keep.
4. Verified from code (community blogs say the opposite): **raising** `match_thresh` accepts
   lower-IoU matches and is the correct direction for large displacement — independently consistent
   with our cam2 match_thresh=0.90 win.

**Diagnostic before any fix:** dump raw detections (no tracker) for known missed fast vehicles.
Boxes at score 0.08–0.25 across the transit → birth/association failure (cheap fixes). No boxes →
detection failure (blur-augmented fine-tuning; deblur preprocessing only partially helps per CVPR
2021 [Sayed & Brostow] and real-time deblurrers are GPU-only).

CPU-feasible mitigations, exploiting that our video is **recorded, not live**:
- Loosen birth (`new_track_thresh` down, `fuse_score` off) + **offline track-quality filter**
  (length × displacement × mean score) after the run.
- **Buffered-IoU (C-BIoU)** association — inflate boxes before IoU; ~10-line change; published fix
  for non-overlapping consecutive boxes [arXiv 2211.14317]. Or OC-SORT (motion-only, in BoxMOT).
- **Offline post-pass: AFLink + GSI** (tracklet stitching + Gaussian-smoothed gap interpolation,
  140–590 Hz, pluggable on any tracker's output) [StrongSORT, arXiv 2202.13514]. Pairs with looser
  birth: birth makes fragments, post-pass merges them.
- Raise Kalman process noise — SORT-lineage Q is pedestrian-tuned; fast through traffic is the
  classic maneuvering-target regime.

---

## Refuted claims (killed by 3-vote panels — do not act on these)

- YOLO26's claimed CPU-latency advantage over prior YOLOs (1-2) and RT-DETR degrading sharply under
  INT8 while YOLO26 stays stable (0-3) — **the detector-swap question is open**; needs A/B on our
  own footage, not literature.
- Appearance-free BoostTrack nearly matching its ReID version (0-3) — ReID's contribution should
  not be dismissed; the constraint is compute, not value.
- "Single-camera trajectory TMC commonly lands at ~13% error" (0-3) and "the cooperative paper's
  bank needs labeled ground truth" (0-3).

## Open questions (no surviving verified claims — silent, not negative)

1. Does homography/world-space (bird's-eye) classification measurably beat image-space shape
   matching for turn attribution on oblique views? Could address the attribution residual directly.
2. Best detector for the OpenVINO/Iris Xe budget (incl. SAHI tiling for distant vehicles) — empirical
   A/B required.
3. How many minutes of human spot-counting buy a given confidence interval on per-movement net error
   (sample-size statistics for new-site validation).
4. Do OC-SORT-style motion gains transfer from pedestrians to vehicles on our footage — biggest
   unvalidated lever.

---

## Prioritized recommendations

1. **Fast-vehicle diagnostic** (hours): raw-detection dump for known missed fast vehicles →
   determines birth/association vs detection failure and which mitigation track applies.
2. **Tracker motion-model upgrade** (the measured headroom; attacks turn residuals AND fast-vehicle
   misses): OC-SORT A/B vs ByteTrack/BoT-SORT on net@15min; loosened birth + offline filtering;
   AFLink/GSI post-pass; frame_skip=1 (drop imgsz first if compute-bound); C-BIoU association;
   `fuse_score` off A/B. Per standing rule: pick by measurement.
3. **Channel-bank v2 for new sites**: entrance/exit lines + auto-collected site trajectories
   (accumulate-and-average over the first 30–60 min) + hand-drawn fallback polylines; swap plain DTW
   for min-directed-Hausdorff + angle + endpoint-proximity; ship a per-site QA step.
4. **Conservation-based QA layer**: automate reverse-movement balance + corridor entry/exit
   consistency as the zero-ground-truth validation at new sites; surface in the UI next to the
   review screen.
5. **Reframe the 5% target**: ≤5% per-movement fully automated exceeds published SOTA; ≤5% with a
   brief human review pass is the industry-standard (and Miovision's actual) recipe. Budget review
   minutes into the product workflow rather than chasing the last points algorithmically.

## Key sources

- Liu et al., "Robust Movement-Specific Vehicle Counting at Crowded Intersections," CVPRW 2020
  (AI City 2020 Track 1 winner) — openaccess.thecvf.com
- Deep OC-SORT — arXiv 2302.11813; OC-SORT — CVPR 2023; ByteTrack — arXiv 2110.06864
- BoostTrack FPS/ReID cost — Springer s00138-024-01531-5
- Jana et al., unsupervised movement classification — arXiv 2111.09171 / MDPI Future Transportation 2023
- Rezaie & Saunier, trajectory clustering comparison — arXiv 2112.01570
- Tran et al., region-and-trajectory matching — CVPRW 2021
- Cooperative intersections — Sensors 2023, PMC10747571
- Maryland SHA, "Reviewing and Validating Turning Movement Counts" (conservation checks)
- Miovision accuracy claims — miovision.com/scout-plus/traffic-studies
- StrongSORT (AFLink/GSI) — arXiv 2202.13514; C-BIoU — arXiv 2211.14317
- FraMOT — arXiv 2209.11404; FCG — arXiv 2210.03355; Sayed & Brostow (blur) — arXiv 2011.14448
