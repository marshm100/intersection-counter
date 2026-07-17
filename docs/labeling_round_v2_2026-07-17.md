# Labeling round v2 — articulated recall + the Mediums class (2026-07-17)

The route out of the native-articulated gate's verdict
(`plan_articulated_native_2026-07-17.md`): the head recognizes only ~41/102
held-out semis, and the ft taxonomy has NO class for Miovision's Mediums
(buses + non-long single-unit trucks were labeled plain `vehicle` in v1, so
FM51 Mediums scored 7 vs 92). Both are LABEL problems before they are
training problems. FM51 contributes zero frames — held out, as always.

## The dataset — `data/finetune_v2` (164 frames, ready to label)

Mined from the five corridor cams' study caches (stock-detector proposals,
prefilled class 0), v1 stems excluded so nothing is labeled twice:

- **semis pass** (120 frames): top frames by widest truckish box per
  window — the articulated-diversity miner. Several windows yielded 0
  because round v1 already claimed their widest trucks (the exclusion
  working, not missing data — e.g. cam3 has 394k truck detections, all its
  top frames were v1's).
- **mixed pass** (44 frames): truck-heavy + uniform-in-time, for medium
  trucks the widest-box ranking never surfaces.

Split: 136 train / 28 val. Truck-first manifest ordering — the early
frames are the valuable ones; stop whenever, `reviewed.json` resumes.

## Taxonomy v2 (the labeler now supports it end-to-end)

| key | class | meaning |
|---|---|---|
| A | 1 articulated (orange) | cab + SEPARATE trailer (hinge, trailer wheels) |
| L | 2 long single-unit (blue) | ~2+ car lengths, ONE chassis (box truck, dump, school bus, RV) |
| **M** | **3 medium (pink)** | **NEW: commercial truck/bus that is NOT 2+ car lengths — bobtail, delivery/service truck, shuttle bus** |
| — | 0 vehicle (green) | everything else incl. pickups, vans, pickup+trailer |

Backend accepts 0–3 (tested); `data/finetune_v2/dataset.yaml` lists all
four names.

## Operator instructions

1. `py start_server.py`
2. Open `http://127.0.0.1:5000/static/labeler.html?ds=finetune_v2`
3. Label per the on-page key card. Budget ~1.5–2 h for all 164; the first
   ~half (truck-first order) carries most of the articulated value.

Pre-handoff verification done (2026-07-17, per the paid-for lesson): served
page confirmed to carry the class-3 build (legend, M key, color), manifest
loads 164/0-reviewed, image endpoint 200. **Post-labeling check** (whoever
runs the next session): `reviewed.json` count moved + class-3 labels
actually present in the txt files before any retrain reads them.

## What the retrain cycle must decide (NOT decided here)

- **v1 medium inconsistency**: v1's 430 frames label mediums as class 0.
  Training v1+v2 together teaches "medium = vehicle" on v1 frames. Options
  for that plan doc: a focused v1 medium re-pass (a `?only=` style filter
  on truckish-width frames), class-3 loss masking on v1, or v2-only for
  the medium class head. The re-pass is likely cheapest — v1's truck-first
  ordering means mediums concentrate in the early frames.
- The event-side mapping for classes 2/3 (→ Mediums) and whether the
  aspect branch is bypassed for ft schemes — deferred by
  `plan_articulated_native` non-goals, owned by the retrain plan.
- Gate: re-run `scripts/fm51_native_artic_gate.py` UNCHANGED (it already
  scores L/M/A vs Miovision same-window); Articulated bar 102, plus
  Mediums now watched.
