# Plan — finetune_v2 retrain (articulated recall + the Mediums class, 2026-07-20)

The route out of the native-artic gate verdict
(`plan_articulated_native_2026-07-17.md`): Articulated 41/102 recognized and
Mediums 7/92 are LABEL problems first (`labeling_round_v2_2026-07-17.md`).
The labels now exist; this plan owns the decisions that doc deferred: the v1
medium inconsistency, the combined dataset, the event-side class mapping,
and the gate bars. Full discipline: the gate is the SAME held-out-FM51
script, promotion is measure-then-apply, fallback is one line.

## Labeling state (verified against persisted data, 2026-07-20)

- **Round v2 COMPLETE**: 164/164 reviewed (`data/finetune_v2/reviewed.json`,
  17:33). Classes: 2,215 vehicle / **120 articulated** (83 frames) / **55
  long** (33 frames) / **63 medium** (45 frames); boxes 1,807 prefills →
  2,453 (+646 add-missed/edits). Post-labeling check PASSED (class-3 rows
  present, all 164 files touched).
- **v1 medium scan IN FLIGHT** (operator decision: full scan of all 430):
  206/430 reviewed, **89 M boxes across 71 frames** so far. Yield is
  ACCELERATING into the mid-tail (28 M-frames in the first ~100 scanned, 43
  in the second; positions 185–198 nearly solid) — v1's truck-first order
  puts the widest boxes (semis/longs) first and the medium band mid-list,
  so **the remaining 224 frames must be scanned; do not stop early.**
  Round-1 audit trail preserved as `reviewed_round1.json`; both dataset
  yamls now carry the four names.

**BLOCKER for training: the v1 scan completes + the post-scan check
(reviewed 430/430, M-yield curve recorded here).**

## Dataset — combined v1+v2, four classes

`data/finetune_v12.yaml` (datasets are local-only; `data/` is gitignored —
this yaml is reproduced here as the record):

    train:
      - C:/Users/onkar/Documents/intersection-counter/data/finetune_v1/images/train
      - C:/Users/onkar/Documents/intersection-counter/data/finetune_v2/images/train
    val:
      - C:/Users/onkar/Documents/intersection-counter/data/finetune_v1/images/val
      - C:/Users/onkar/Documents/intersection-counter/data/finetune_v2/images/val
    names: {0: vehicle, 1: articulated, 2: long_single, 3: medium}

~594 frames (430 + 164), FM51 contributes ZERO (held out, as always).
Ultralytics resolves labels/ from images/ path substitution — no copying.

## Training — the PROVEN v1 recipe, new run dir (no new knobs)

    py scripts/finetune_detector.py --data data/finetune_v12.yaml \
        --run-dir runs/finetune_v2 --epochs-total 64

From `--base yolo26s.pt` (NOT warm-from-ft1: the head reshapes 3→4 classes
anyway, and the from-base chunked recipe is the one that produced the
promoted detector — reproducibility beats entrenchment risk). Defaults
otherwise: freeze 10, imgsz 640, lr0 0.005 × 0.6^chunk, batch 4, 8
epochs/chunk, manifest-resumable. v1's best landed at 56/64 epochs; expect
the same neighborhood. CPU-chunked so the laptop stays usable; each chunk
is ~laptop-tolerable and interruption costs at most one chunk.

## Class scheme + event wiring (the .py work — AFTER the scan, server-safe)

New `class_scheme = "finetune_v2"` threaded exactly like finetune_v1 was
(pipeline/ingest/router):

| ft class | chain id | event class | deliverable bucket |
|---|---|---|---|
| 0 vehicle | COCO 2 (car) | car | Lights |
| 1 articulated | **8 native** (existing wiring, vote floor 2) | multi_unit_truck FHWA 9 | Articulated |
| 2 long_single | **native → single_unit_truck FHWA 5** | single_unit_truck | Mediums |
| 3 medium | **native → single_unit_truck FHWA 5** | single_unit_truck | Mediums |

Classes 2/3 both land in Miovision's Mediums (FHWA 4–7) — the L/M split
exists for LABEL precision, not the deliverable. The native 2/3 wiring
bypasses the aspect branch for ft schemes (the deferred non-goal from
`plan_articulated_native`; the aspect pass was built for COCO-7 boxes and
buries class-7s — measured in the native-artic gate). Same vote-floor
pattern as class 8 (a 1-frame flicker never flips a class); coco-scheme
runs see no 2/3-native ids anywhere, so this is a no-op for them by
construction.

## The gate — `scripts/fm51_native_artic_gate.py`, flow UNCHANGED

The ONE permitted touch: the weights/variant constants point at the
`runs/finetune_v2` best checkpoint (the script was written against the v1
chunk dir; the flow, windows, scoring, and Miovision reference stay
byte-identical). Bars:

1. **No-regression (hard)**: FM51 total ≈ +1.1%, interval MAE ≤ 2.5-class,
   through-kill counts unchanged vs the promoted baseline — the v1 gate's
   PASS must not degrade.
2. **Articulated (the headline)**: vs Miovision 102. v1 head = 41/102
   recognized → 22 events. The 120 new corridor semi instances target
   this; any material recall gain is progress, ≥~70 recognized is the
   aspiration (matches the retired size-heuristic's ~70% without its
   false-positive class).
3. **Mediums (now measured)**: vs Miovision 92. v1 = 7. The 63+89-and-
   counting medium labels + consistent v1 make this the first honest shot.

PASS → export (`scripts/export_yolo_openvino.py`) → promote into the
Balanced profile as `yolo26s_ft2.pt`@640, `class_scheme finetune_v2`;
fallback = revert the profile entry (one line, same as v1's lever).
FAIL → the verdict section records which bar and the next label/route
decision; the promoted v1 detector stays.

## Sequence

1. ~~Round v2 labels~~ DONE (verified above).
2. **v1 medium scan completes** (operator, 224 frames left) → post-scan
   check: 430/430 reviewed + final M counts recorded here.
3. Combined-yaml smoke: one `--status` + a 1-epoch dry chunk loads 594
   frames/4 classes cleanly.
4. Chunked training to 64 epochs (~overnight CPU, resumable).
5. Class-scheme + native-2/3 wiring (.py, after the operator's labeler
   session closes) + tests.
6. FM51 gate → verdict section HERE → operator promotion call.
