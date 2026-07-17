# Detector de-risk spike — are the failing cells detection-bounded? (2026-07-08)

MASTER_PLAN §4 item 1, the post-Gate-B top lever. Question: in the three failing
zones (cam2 SB-right 58% recall, cam5-EB 17.5% MAE, cam1-NB 13.3% MAE), are the
missing vehicles absent from DETECTIONS, or dropped downstream? If a
higher-capability detector (yolo26l @1280, the accurate profile) finds materially
more in-zone signal, the lever is a per-camera detection profile (config, cheap);
if not, the §3-D fine-tune is the justified path — or the cells are
downstream-bounded (tracking/attribution) and no detector work moves them.

## Method (`scripts/detector_zone_recall.py` — detections only, no tracker, no GT)

- **Zones from operator geometry only:** drawn channels (cams 2/5) / live-bank
  polylines (cam1 — no drawn channels), buffered ±30 px around the movement curve.
- **Control zone on every camera:** a healthy high-volume movement on the same
  camera. If the failing zone's accurate-vs-balanced uplift ≈ the control's, the
  bigger model is a UNIFORM gain (more boxes everywhere), not a failing-zone
  recovery.
- **Common conf floors:** counts at ≥0.10 (balanced cache floor) and ≥0.25 (the
  tracker birth gate `track_high_thresh` — what a track can be born from).
  Entry-third split (by curve arclength) localizes where any gap sits.
- **Novel-detection metric** (kills the more-boxes-per-vehicle confound): accurate
  dets ≥0.25 in-zone with NO balanced det ≥0.10 within 25 px on the same frame =
  vehicles the balanced config does not see at all.
- **Configs:** balanced_960 (yolo26s @960 conf 0.10) vs accurate_1280 (yolo26l
  @1280 conf 0.08). cams 1/5: both cached over the identical 07:00–07:30 frame
  window (251980–269980 @10 fps). cam2 has no accurate cache: fresh yolo26l
  OpenVINO @1280 pass on every 25th frame (1 Hz, 1800 frames, same wall-clock
  window), compared against the balanced cache restricted to the SAME frames.
- **Prior to beat** (backend/config.py caveat, FM51 2026-07-02): on 640×480
  source — all five corridor cams — 1280 inference upscales; measured effect was
  "+6% uniform, not a distant-vehicle recovery". This spike asks the same question
  zone-locally.

## cam1-NB (failing: NB approach thru+left; control: SB-thru)

| zone | config | dets/frame ≥.10 | ≥.25 | entry-third ≥.25 | mean conf |
|---|---|---|---|---|---|
| FAILING NB | balanced_960 | 2.455 | 1.546 | 1.108 | 0.423 |
| FAILING NB | accurate_1280 | 2.230 | 1.611 | 1.084 | 0.492 |
| CONTROL SB | balanced_960 | 2.501 | 1.545 | 0.120 | 0.403 |
| CONTROL SB | accurate_1280 | 2.499 | 1.762 | 0.116 | 0.476 |

Uplift in the failing zone: ×0.91 @≥.10, ×1.04 @≥.25 (control ×1.00/×1.14) —
**nothing**. Novel dets 0.110/frame (6.8%) vs control 3.1% — and chaining the
novel dets over time shows the sustained (≥1 s) chains are **stationary** (fixed
spots (144,218), (219,205) recurring for minutes = a static object / stopped
vehicle the large model intermittently boxes), zero sustained MOVING novel
vehicles. **cam1-NB is NOT detection-bounded.** Its gate-independent NB-thru −42
(−7%) residual (see the cam1 blind-gate re-validation) lives downstream
(tracking/association), or behind the 640×480 resolution wall.

## cam5-EB (failing: EB approach thru+right+left; control: SB-thru)

| zone | config | dets/frame ≥.10 | ≥.25 | entry-third ≥.25 | mean conf |
|---|---|---|---|---|---|
| FAILING EB | balanced_960 | 3.888 | 2.569 | 0.568 | 0.474 |
| FAILING EB | accurate_1280 | 5.045 | 3.343 | 0.648 | 0.468 |
| CONTROL SB | balanced_960 | 2.679 | 1.590 | 0.019 | 0.405 |
| CONTROL SB | accurate_1280 | 3.716 | 2.367 | 0.018 | 0.435 |

Failing-zone uplift ×1.30 — but the control gets ×1.39–1.49: the large model
emits ~30–50% more boxes EVERYWHERE on cam5 (the FM51 "uniform" effect, bigger
here), with no zone-specific recovery. Novel fraction 4.1% failing vs 4.2%
control — identical. **cam5-EB is NOT detection-bounded.**

**Concrete cam5 lead found while defining zones:** the live applied bank has NO
EB-through path at all — `intersection_paths` for cam5 covers 36→38 (WB-thru,
support 8) but nothing for 38→36; the operator's drawn channel 50 (38→36) exists
but the applied bank (source `data-driven-rawtrack`) predates drawn-direct. For a
bank-calibrated camera the movement comes from the path label, so EB-through
vehicles have no correct path to match — an attribution-COVERAGE gap squarely in
the failing approach. Re-applying the bank with the drawn channels included is a
cheap, GT-free fix candidate for cam5-EB, upstream of any detector work.

## cam2 SB-right (failing: drawn channel 27→28, entry at the right FOV edge; control: NB-thru)

Fresh yolo26l OpenVINO @1280 conf 0.08 on 1790 matched 1 Hz sampled frames
(07:00–07:30; `scripts/cam2_accurate_sampled_pass.py` →
`evaluations/cam2_accurate1280_sampled.parquet` — cam2 has no accurate cache;
follow-up stats from `scripts/cam2_sbright_followup.py`).

| zone | config | dets/frame ≥.10 | ≥.25 | entry-third ≥.25 | mean conf |
|---|---|---|---|---|---|
| FAILING SB-right | balanced_960 | 1.189 | 0.739 | 0.283 | 0.436 |
| FAILING SB-right | accurate_1280 | 1.727 | 1.021 | 0.341 | 0.419 |
| CONTROL NB-thru | balanced_960 | 3.109 | 1.897 | 1.775 | 0.417 |
| CONTROL NB-thru | accurate_1280 | 3.117 | 2.193 | 2.066 | 0.494 |

**cam2 is the one zone with a REAL zone-specific detection gap:** failing-zone
uplift ×1.38–1.45 vs control ×1.00–1.16, and the novel fraction is 11.2%
(0.115/frame) vs control 1.6% — 7× the control. Entry-third (the FOV-edge birth
region from the diagnosis): median conf 0.387 → 0.527, below-birth-gate fraction
35% → 30%, density ×1.11–1.20.

**But sized against the miss, it is a MINOR share:** chaining the novel dets at
1 Hz finds ~0.13 moving novel vehicles/min, vs the SB-right miss of ~1.28/min
(−461 over 6 h) — the bigger detector surfaces roughly **10% of the missing
vehicles** as genuinely new detections. The other ~90% are vehicles the balanced
config ALREADY detects (the 2026-07-06 diagnosis: detections abundant through the
whole turn, majority above the birth gate) whose tracks die mid-turn or never
birth — an association/birth failure, not a detection one. The un-chained novel
dets concentrate mid/exit-third (occluded-frame recoveries), where the tracker
experiment showed both trackers terminate DESPITE abundant detections.

## Verdict

**The per-camera detection-profile config lever is DEAD as the failing-cell fix.**
Two of three failing zones (cam1-NB, cam5-EB) get NO zone-specific detection
signal from the accurate profile — the uplift is at or below the same camera's
healthy control, and the novel detections are stationary flicker (cam1) or the
uniform more-boxes effect (cam5). The third (cam2 SB-right) shows a real
zone-specific gap, but it sizes to only ~10% of that cell's miss. Gate B's
"detection-bounded" framing is hereby REFINED: the failing cells are
**downstream-bounded** —

1. **cam2 SB-right** → tracker birth/association at the FOV edge and through the
   occluded turn (the GT-validated mechanism stands; detection contributes ~10%).
2. **cam5-EB** → attribution coverage: the live applied bank has NO EB-through
   path (predates drawn-direct). Cheapest candidate fix on the board: re-apply
   the cam5 bank with the operator's drawn channels included, then blind-QA.
3. **cam1-NB** → gate-independent NB-thru −7% residual, association/attribution
   (not detection, per this spike; not the merge gate, per the blind-gate
   re-validation).

**Is the §3-D fine-tune justified? Yes — but scoped at its REAL targets, not
sold as the failing-cell fix.** The evidence base: FM51 PM low-light miss
(−12–20%/interval), articulated 0/102 (bbox heuristic caps at ~70%), and the
cam2 entry region's demonstrated domain headroom (a GENERIC bigger model lifts
entry median conf +0.14 and cuts the below-gate share 35→30%; a domain-tuned
model plausibly pushes more of the edge-clipped distribution over the 0.25 birth
gate — an assist to, not a substitute for, the tracker-side fix).

### §3-D fine-tune spike scope (blind-deployment rules, MASTER_PLAN §0)

- **Data:** diverse-site frames — all 5 corridor cams + FM51 + any third site,
  sampled across lighting (AM/PM/dusk) — a few hundred labeled frames per site,
  every vehicle boxed, FHWA-articulated as a class. NEVER only failing zones,
  never tuned per-site against GT. **Hold out one full SITE** (not a window) as
  the blind eval.
- **Train:** Colab GPU; base = yolo26s (the balanced deploy model — CPU speed is
  a product constraint); yolo26m/l as upper-bound reference arms.
- **Gates:** frozen constants; score with the SAME harness
  (`scripts/detector_zone_recall.py` zone density + novel metric) plus
  end-to-end blind pipeline runs; acceptance = failing-zone novel-vehicle
  recovery AND no regression on the passing cams (3/4) AND held-out-site
  parity. Negative result = a deliverable.
- **Order:** articulated first (cleanest win, per §3-D), then low-light/edge
  recall.

### What this spike does NOT license

No per-camera conf/imgsz knobs against the corridor's known answers (the §0
overfit trap); no tracker changes without their own plan doc + ablations +
frozen-constant blind sweep (the cam2 birth-at-edge / turn-association fix is a
TRACKER mechanism and gets the full gate discipline when scoped).
