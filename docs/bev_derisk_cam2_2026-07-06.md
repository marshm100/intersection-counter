# Per-approach lever de-risk — cam2 SB↔EB swap (2026-07-06)

**Decision memo — with a same-session CORRECTION (read the CORRECTION section
before acting on the anchor/root-cause parts).**

- **BEV / IPM — de-risked NEGATIVE (SOLID).** Non-circular Miovision re-split moves
  the cam2 SB:EB split AWAY from ground truth under both homographies. Not the lever.
- **Entry-line anchor — prototype INCONCLUSIVE, not negative.** My first read said
  "negative" but it rested on a crude single-through-wire that missed turning
  vehicles; corrected below.
- **Detection at the entries is ADEQUATE** (not the wall I initially inferred).
- **The cam2 mechanism was subsequently RESOLVED** by a rigorous GT-anchored
  diagnosis — see **`docs/cam2_perapproach_diagnosis_2026-07-06.md`**: it is two
  independent TRACKING defects (SB-right tracks break → −461; EB tracks split under
  SB-thru occlusion → +769), not the attribution swap this doc set out to fix.

The BEV analysis (solid) is below; the anchor de-risk, the detection-cache
findings, and the **CORRECTION** that walks back the overstated parts follow it.
The resolved mechanism lives in the companion diagnosis doc.

## The question
The last accuracy hurdle is the per-approach §1b gap (interval MAE ≤5%). cam2's
worst residual is a ~700-vehicle SB↔EB attribution swap: the collinear pair
**SB-thru (leg 27→29, path 101)** and **EB-right (leg 28→29, path 106)** share the
leg-29 (South) exit and lie within ~21 px of each other over EB-right's whole
length in the image, so the matcher's min-directed cost can't separate them.

Two deep-research passes named **BEV / inverse-perspective-mapping** the top bet:
the pair overlaps in the IMAGE (perspective collapse) but should be ~90° apart in
WORLD space. The de-risk (cheap, data-in-hand, no pipeline code): build a rough
homography, project the stored tracks, measure whether the two clusters separate.
Separates ⇒ build the BEV matcher; FOV-clipped ⇒ fall back to the anchor.

## Method
Read-only over `data/projects/97a7849a/project.db`, numpy only (RAM-light).
Scripts in scratchpad: `bev_derisk.py`, `bev_faithful.py`, `bev_gt_test.py`.

- **Two homographies**, so a skewed projection can neither mask nor fake a result:
  - **A — zone-diamond**: the 4 cardinal leg zones → unit diamond N(0,1)/S(0,-1)/
    E(1,0)/W(-1,0). Rough (zones aren't the road-axis extremes).
  - **B — VP-metric**: the research's "auto-cal via vanishing points" — intersect
    the two N-S lane centerlines → VP_ns, the two E-W → VP_ew, send both to
    infinity along the world axes AND force them orthogonal. A real IPM.
- **Faithful cost.** Ported the pipeline's OWN kernels (`_mdh_cost`,
  `_min_directed`, `_resample_to`, `_densify_polyline`) — cam2 runs
  `cost_metric='mdh'`, whose discrimination lives entirely in `base` (min-directed
  MEAN); the `ang` (tail) and `end_prox` (exit) terms are shared by the pair and
  cancel. Hausdorff proxies were a first cut only; the faithful `base` is the test.

## Results

**1. Homography sanity — the rectification works.** Road cross-angle (want ~90°):
IMAGE 24.4° → zone-diamond 42.7° → **VP-metric 84.0°**. (VP-metric N-S straightness
is soft, 0.65 — the two opposing N-S centerlines are near-collinear, an
ill-conditioned VP — but the E-W axis and the overall cross are clean.)

**2. Ideal-template separation — the geometric PREMISE is TRUE (clean, label-free).**
Projecting the two *bank polylines*:

| space | mdh(SB,EB) | entry-heading separation |
|---|---|---|
| IMAGE | 21.5 | 16.1° |
| BEV-B (VP) | 48.1 | **138.5°** |

In a rectified world the pair is genuinely not collinear — entries ~138° apart.
The research was right about the geometry.

**3. Faithful-cost agreement (CIRCULAR — cannot credit BEV, kept for the
stratification only).** Classifying stored tracks to the nearer template by the
live `_mdh_cost`: IMAGE 0.964 vs BEV-B 0.897 balanced-accuracy. This test is
**circular** — the stored labels ARE the live mdh cost's own output, so it
structurally rewards the image cost and penalises BEV for *disagreeing* even when
disagreeing would *fix* a swap. Not decisive. The one clean signal it carries is
**where** the confusion lives: stratified by birth distance to the nearer true
entry, image accuracy craters on **downstream-born** tracks (born ≥100 px past
both entries: 0.98 near-entry → **0.80** downstream), and BEV makes those **worse**
(0.62) — the tracks that lack an entry are exactly the ones BEV can't help.

**4. Non-circular test vs Miovision — DECISIVE. BEV moves per-approach counts
AWAY from ground truth.** Re-split the same 6035 tracks between SB-thru and
EB-right by argmin `_mdh_cost`, restricted to the 360 Miovision-covered minutes,
compared to Miovision's actual counts:

| split of the SAME tracks | SB-thru | EB-right | EB-frac | \|dev vs Mio\| |
|---|---|---|---|---|
| **Miovision (GT)** | 4695 | 1217 | 0.206 | 0 |
| stored (live pipeline) | 4440 | 1595 | 0.264 | 633 |
| re-split IMAGE mdh | 4324 | 1711 | 0.284 | 865 |
| re-split BEV-B mdh (VP) | 4254 | 1781 | 0.295 | 1005 |
| re-split BEV-A mdh (zone) | 4090 | **1945** | 0.322 | **1333** |

Ground truth is EB-right = 1217; every cost over-assigns EB (the collinear
magnet), and **both BEV projections over-assign MORE than image** — monotonically
further from GT (dev 633 → 865 → 1005 → 1333). Crucially, the **cleaner-conditioned
homography (BEV-A, N-S straightness 0.087) is the WORST of all** — better
calibration made it worse, not better. That closes the "a metrically-surveyed
homography would win" objection: the failure is not homography quality, it's that
BEV is the wrong lever.

## Why BEV fails here (the four legs of the verdict)
1. **Premise true, signal unrecoverable.** The ideal templates separate in BEV
   (138°), but the actually-confused tracks are **born downstream of the
   divergence** (entry-starved). The separating entry is not in the data.
2. **Information argument (a-priori).** A homography is a bijection on the observed
   points — it adds **zero** information. If two classes are separable only by a
   trajectory portion that was never observed (FOV-clipped / born-downstream), no
   projection can separate them. BEV is a coordinate change, not new evidence.
3. **Non-circular GT confirms it.** BEV re-attribution moves the SB:EB split
   *away* from Miovision (dev 865 → 1005). It doesn't just fail to help; it hurts.
4. **The live cost discards the entry anyway.** partial-Fréchet ignores the
   uncovered approach prefix; the tail/exit prior is shared by the pair. Exploiting
   BEV's entry separation would need a NEW entry-using cost — and using the entry
   was already DISPROVEN twice on cam2 (the entry-tiebreak: 14.4→23.5, and EB
   33→41). BEV + a disproven discriminator is not a path.

Two independent homographies agree (and the *cleaner*-conditioned one scored
worst), and legs 2 & 4 are homography-invariant, so a metrically-surveyed
homography would not reverse the verdict: it can sharpen the ideal 138° but cannot
put an unobserved entry into an entry-starved track.

## Entry-line anchor — prototype (read the CORRECTION below)
The stated fallback (`scratchpad/anchor_prototype.py`): a **directed** tripwire per
approach (perpendicular to inflow, a short inset inside the FOV; directed because the
north end of Belt Line Rd is where SB *enters* and NB *exits*), origin = earliest wire
crossed. The first read looked negative — hybrid (anchor + matcher fallback) |dev|
2154–3600 vs pipeline 1606; "of 3789 pipeline-EB tracks, 1381 cross nothing, only 234
cross the SB wire." **But that read does not hold up — see the CORRECTION.**

## Detection-cache findings (the entries ARE detected)
Streaming the cam2 detection cache (`scratchpad/det_coverage.py`; 640×480 source, conf
floor 0.08, birth gate `TRACKER_ACTIVATION_THRESHOLD=0.25`):
- **The EB entry (y≈120) is detected well:** median conf **0.51**, 587k detections,
  ~75% *above* the birth gate; essentially nothing detectable upstream of y≈105 — so
  y≈120 *is* the in-frame entry and it is covered.
- **Far-field size penalty is real but not fatal to detection:** top-of-frame vehicles
  are ~14–26px vs ~120–200px near-field. Small, but still detected.
- So the entry gap is **not** a clean detection wall or a birth-gate the tracker could
  safely loosen (loosening was A/B-disproven — recall-bound). Detection ≠ the lever.

## CORRECTION — what I over-concluded, and why (same session)
I initially wrote "entry-anchor ALSO NEGATIVE" and "root cause = late-detection
entry-starvation." **Both were over-concluded on flawed rapid diagnostics. Do not
rely on them.** What broke:
1. **Crude wire placement.** The single anchor wire sat on the *through* path at inset
   70 ≈ (416,123) — right where EB-*right* turners are born (they diverge from the
   through). So the wire MISSED turners, inflating "non-crossers." The anchor is
   **UNVALIDATED**, not disproven — a fair test needs per-movement / operator-drawn
   lines placed *before* the movement divergence.
2. **A threshold artifact.** The "675 downstream / entry-starved" EB tracks are
   actually born tight at ~(411,113) — only ~62px from the EB-*right* mouth — and are
   **long, well-tracked** (median 193 points). They are normal EB-approach vehicles,
   not mid-scene fragments. The "≥60px from every mouth" cut mislabeled them.
3. **Mechanism is mixed, not a clean "SB→EB entry-starved swap."** A rigorous
   concurrent-duplicate test (interpolated per-frame positions, <20px) finds **305/3789
   EB tracks (8%) are tight concurrent duplicates** of an earlier EB track — tracker
   ID-splits — explaining ~40% of the +769 over-count. The remaining ~464 is not
   isolated (sequential fragmentation? a real swap fraction? unproven).

Root process failure: three crude geometric tests in a row lied because cam2 has
**tight birth clusters + collinear paths** that defeat naive proximity/threshold cuts.

## Where this leaves cam2 (honest state → now RESOLVED in the companion doc)
- **BEV is not the lever** — solid, keep.
- **Detection at the entries is adequate** — not un-detected (validated vs cache).
- **The mechanism is now fully diagnosed** in `docs/cam2_perapproach_diagnosis_2026-07-06.md`
  (rigorous GT-anchored, then cache-validated): two independent TRACKING defects —
  SB-right tracks break mid-turn (−461) and EB tracks split under SB-thru occlusion
  (+769, ~40% confirmed concurrent ID-splits). The lever is occlusion-robust tracking
  (Phase-1 tracker, per-camera), not attribution and not the detector.
- The entry-line anchor is **untested**, not dead — but it is moot now that the gap
  is a tracking problem, not an attribution one.

## Lesson (record)
1. **Ideal template separation in BEV ≠ recoverable separation on real tracks**, and
   judge a candidate matcher on *external* GT, not the system's own labels (the
   circular trap). The BEV de-risk was clean because it did both.
2. **Validate the instrument before trusting a per-approach geometric diagnostic
   here.** Tight birth clusters and collinear paths made three quick tests
   (through-path wires, a distance-from-mouth threshold, a birth-proximity duplicate
   test) each produce a confident but WRONG reading. Cross-check every geometric cut
   against the raw tracks before concluding.
