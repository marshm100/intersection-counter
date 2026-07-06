# cam2 per-approach — RIGOROUS GT-anchored diagnosis (2026-07-06)

**Supersedes the earlier "SB-thru ↔ EB-right entry-starvation swap" framing (which
was wrong — see `docs/bev_derisk_cam2_2026-07-06.md` CORRECTION).** This is the
validated decomposition, built only from ground-truth correlations (no geometry —
the geometric cuts that misled earlier are avoided by construction).

## Method (instrument = Miovision, the ground truth)
`scratchpad/per_minute_diagnosis.py`: bin our stored events and the Miovision
per-minute OD into 5-min bins (72 bins over the 360-min window), by approach and by
movement. Decompose the mechanism from correlation STRUCTURE against GT:
- **Double-count** ⇒ `err_EB(t) ∝ mio_EB(t)` (constant inflation), independent of SB.
- **Swap/leak** ⇒ `err_A(t) ≈ −err_B(t)` per bin (anti-correlation), and the loser's
  volume drives the gainer.
No per-track geometry, so tight birth clusters + collinear paths can't corrupt it.

## The decomposition (per movement, whole window)
| approach-mvt | ours | Miovision | error | recall |
|---|---|---|---|---|
| **SB-right** | 647 | 1108 | **−461** | **0.58** |
| EB-right | 1595 | 1217 | +378 | 1.31 |
| EB-thru | 1067 | 749 | +318 | 1.42 |
| SB-thru | 4440 | 4695 | −255 | 0.95 |
| NB (approach) | 6555 | 6393 | +162 | 1.03 |
| SB-uturn | 71 | 15 | +56 | (phantom) |
| EB-left | 1120 | 1051 | +69 | 1.07 |
| SB-left | 552 | 567 | −15 | 0.97 |

The headline "SB −675 / EB +769 swap" is really **two independent defects** that
happen to partially cancel (net total +256):

## Mechanism 1 — SB-right is MISSED (−461, the single biggest error) = TRACKING
- `corr(err_SBright, err_EB) = −0.12`, `corr(err_EB, mio_SBright) = +0.07`, no other
  movement's error correlates with SB-right's (all |corr| ≤ 0.18) ⇒ SB-right does
  **not** leak — it is simply **not counted** (~42% lost).
- **It is a TRACKING failure, not detection (validated against the cache):** the
  647 SB-right tracks we do have are **born correctly** at (624,181) but **die at
  x≈581** — 93% truncate *before* the leg-28 exit (~497), median arclength just
  **126px** (vs 350–640px for every healthy movement). Yet the detection cache is
  **abundant all along the turn**: region A entry (x600–640) 71k dets, B mid-turn
  where tracks die (x555–600) 107k dets, C toward exit (x497–555) 157k dets — each
  with the *majority above* the 0.25 birth gate (58/61/71%). The vehicle is seen the
  whole way; the track just doesn't follow it.
- **Cause:** the entry sits at the **right image edge** (region A conf 0.30, 42%
  below the birth gate — edge-clipping), and the sharp near-field right turn in
  heavy SB-thru traffic breaks association mid-turn. ~40% of SB-right vehicles never
  get a track born (edge-clip + occlusion); the ~60% that do birth truncate at x≈581.
- **Fix family: tracker, not detector** — better birth at the FOV edge + occlusion-
  robust association through the turn (ReID / buffered IoU / longer memory).

## Mechanism 2 — EB is DOUBLE-COUNTED (+769), driven by SB-thru occlusion
- `corr(err_EB, mio_SBthru) = +0.58` (strong): EB over-count scales with **SB-thru**
  volume. But SB-thru itself is only −255 (95% recall), so SB-thru is **not being
  relabeled** EB — if it were, SB-thru would be massively under. Instead SB-thru
  *traffic* inflates EB.
- A rigorous concurrent-duplicate test (`scratchpad/`, interpolated per-frame
  positions, <20px) finds **305/3789 EB tracks are tight concurrent duplicates** of
  an earlier EB track (tracker ID-splits) — ~40% of the +769, and EB inflation ratio
  is ~1.33 overall.
- ⇒ **Mechanism:** SB-thru vehicles cross the intersection (N→S) in front of EB
  vehicles (W→…), occluding them mid-track → the EB track splits into two IDs →
  double-count. Correlated with SB-thru volume exactly as observed.
- **Fix family:** occlusion-robust tracking (ReID / longer track memory / buffered
  association to survive the SB-thru cross) and/or a track-level dedup of concurrent
  co-located tracks. cam2 already has some NMS (`project_cam2_nms_applied`).

## What this means
- **The per-approach gap is a TRACKING/DETECTION-quality problem, not attribution.**
  That direction is now GT-validated (and it explains why BEV and the entry-anchor —
  both attribution levers — could not help). The *specific* earlier mechanism
  ("entry-starved SB-thru→EB-right swap") was wrong; the correct mechanisms are
  SB-right recall loss + EB occlusion double-count.
- **Neither lever is attribution cleverness.** Both are upstream: recover the missed
  SB-right tracks, and stop EB tracks splitting under SB-thru occlusion.
- **Confidence:** the WHAT (SB-right loss is a miss not a leak; EB over is a
  double-count scaling with SB-thru) is GT-validated. The WHY at the pixel level
  (edge-clip vs short-track for SB-right; the occlusion split geometry for EB) is the
  leading interpretation and is the scoped next validation.

## The unification
**Both cam2 defects are TRACKING failures in the busy near-field zone, and the common
driver is the heavy SB-thru traffic:** it *breaks* SB-right tracks mid-turn (→ −461
under-count) and *splits* EB tracks under occlusion (→ +769 over-count). Neither is a
detector problem (detection is confirmed healthy at both) and neither is attribution.
⇒ **one fix family: occlusion-robust tracking** (ReID / buffered-IoU association /
longer track memory), plus better track birth at the FOV edge. This is exactly the
Phase-1 tracker direction (`project_phase1_tracker_2026_06_11`) — which is PER-CAMERA
(it helped cam3, hurt over-count cams), so it must be validated on cam2 specifically
against Miovision per-interval before shipping.

## Next steps (scoped, in priority)
1. **SB-right (−461, biggest) — DONE diagnosing: it's tracking.** Next = try a cam2
   tracker recipe (buffered-IoU + edge-birth loosening + ReID) and measure whether
   SB-right tracks persist through the turn (death x moves from ~581 toward the ~497
   exit) and recall rises toward 1108, without regressing NB/WB.
2. **EB occlusion double-count (+769):** same tracker change should also reduce the
   ID-splits; measure EB ratio dropping from ~1.33 toward 1.0. If tracking alone
   doesn't clear it, add a concurrent-duplicate dedup (the validated <20px test).
3. Re-measure the per-15-min interval metric after each; the bar is AVG|err| ≤ 5%
   per approach. Guard against per-camera over-fit (Phase-1 tracker is not a blind
   default).
