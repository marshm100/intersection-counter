# Plan — native articulated wiring (2026-07-17)

The promoted detector (finetune_v1) natively separates class 1 "articulated"
from class 2 "long_single", but `_FT_CLASS_MAP {0:2, 1:7, 2:7}` flattens both
to COCO truck at parse time — the semi signal dies before the cache, and the
L/M/A deliverable's Articulated bucket still rides the §3-D ~70%-of-frames
size heuristic (`ARTICULATED_LEN_RATIO` vs the local car baseline, a
post-pass that only runs in the legacy v3 live finalizer — the two-pass flow
never runs it at all). Handoff 2026-07-17 names this the next integration:
persist class 1 through cache → events → L/M/A, retiring the size heuristic
where the native signal exists.

## Design (smallest faithful thread)

One reserved class id carries the signal through the EXISTING plumbing —
no cache schema change, no dump format bump, no replay change:

- `NATIVE_ARTICULATED_CLASS_ID = 8` (config; COCO 8 = boat, which we never
  request — the id is free in every cache/dump this app has ever written).
  `VEHICLE_CLASSES[8] = "articulated_truck"` so `is_vehicle`, class names,
  cache reconstruction and `_row_to_tracked` all accept it unchanged.
- Detector: `_FT_CLASS_MAP = {0: 2, 1: 8, 2: 7}`. Classes 0/2 keep the
  EXACT mapping the FM51 full-chain gate validated (long_single stays
  COCO-truck + aspect subclassification — byte-identical Lights/Mediums
  behavior); ONLY the articulated id changes. `RELEVANT_CLASSES` (the
  stock-model COCO filter) must EXCLUDE 8 or coco-scheme models would be
  asked for boats.
- Classifier: `YOLO_TO_SIMPLIFIED[8] = "multi_unit_truck"` → FHWA 9 →
  "Articulated Trucks" in every deliverable (they all key off fhwa_class
  via fhwa_to_class_group — verified export.py + excel_export.py).
- Pipeline: class-at-birth systematically under-calls semis (far-field
  births detect as class 0 before the trailer resolves), so the track
  accumulates native-articulated VOTES: `n_native_articulated` += 1 per
  class-8 detection in `_process_vehicle`. At finalize the effective class
  is 8 when votes ≥ `NATIVE_ARTICULATED_MIN_FRAMES = 2` (mirrors the size
  pass's `_MIN_MATCHED_FRAMES = 2` — chosen BY CONSTRUCTION from that
  precedent, not fit to any site; a 1-frame flicker never flips a class),
  else a born-8 track demotes to 7 (the validated truck path). Works
  identically live and in pass-2 replay: the dump's class_id column IS the
  vote stream; no scheme flag needed downstream (id 8 only exists in
  finetune-scheme caches).
- Retire the size heuristic where native owns it: the v3 live finalizer
  skips `reclassify_articulated` for cameras whose mode config says
  `yolo_class_scheme == "finetune_v1"`. Stock/coco runs keep the size pass
  unchanged (it is their only articulated mechanism).

## Gate (dev scorer only, FM51 held out from all training)

FM51 windows (AM 07-09, PM 16-18) re-detected with the native map as new
cache variants (`ftv1n_am/pm` — the ftv1 dumps pre-date the split and
carry 7s for both truck classes, unusable for this) → pass-1 → pass-2
replay → score:

- **Articulated**: events with fhwa 9 vs Miovision's Articulated count over
  the same intervals (audit_fm51 machinery; window-restricted — the
  full-day Articulated=102 is the familiar day-level yardstick, the gate
  scores the processed windows). Old chain's size pass measured ~95/102
  day-level; the bar is parity-or-better on the windows WITHOUT the size
  pass.
- **No-regression**: window totals / interval MAE / Lights+Mediums split vs
  the promoted ftv1 baseline (classes 0/2 mapping unchanged → expected
  byte-near-identical; the tracker consumes identical boxes, only some
  class ids differ).

PASS → ship (already promoted profile simply gains the native column).
FAIL → the map reverts to {0:2,1:7,2:7} (one-line), findings doc.

## Non-goals

- Long_single (class 2) native wiring — a separate cycle with its own
  Mediums-scored gate; today's validated aspect-split behavior stays.
- Corridor re-detection (stock-scheme caches keep the size pass).
- Any change to the origin/attribution chain (the origin-grab cycle owns
  that).
