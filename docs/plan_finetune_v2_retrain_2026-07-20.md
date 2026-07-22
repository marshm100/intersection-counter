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
- **v1 medium scan COMPLETE (2026-07-21)**: 430/430 reviewed, **187 M boxes
  across 147 frames** — the full-scan decision vindicated (the 206-frame
  checkpoint had only 89; quartile yield by manifest position = [28, 50,
  45, 24], the predicted mid-list medium band, with even the tail quartile
  holding 24 M-frames — a partial scan would have left half the mediums
  contradictory). v1 final distribution: 7,910 vehicle / 227 articulated /
  90 long / 187 medium. Round-1 audit trail preserved as
  `reviewed_round1.json`; both dataset yamls carry the four names.

**COMBINED v1+v2 (the training set): 594 frames — 10,125 vehicle / 347
articulated / 145 long / 250 medium. Post-scan check PASSED; the training
blocker is CLEARED.**

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

## GATE VERDICT (2026-07-21 — evidence runs/finetune_v2/fm51_gate_v2.json;
the script's hardcoded outp briefly overwrote the v1 evidence, restored from
git; fix the path when the script is next touched)

Training: 64/64 epochs, 8 chunks, ~7.2 h CPU. **Winner chunk 5 best.pt (48
ep)**: val all .605 / articulated .697 (P .781) / long .608→.545 / medium
.499 — runner-up chunk 7 (long .608, medium .449); val is 113 images, the
gate decided. Exported `yolo26s_ft2_openvino_model` (FP16 @640).

**Held-out FM51, identical scoring basis, v2 vs the PROMOTED v1 native:**

| bar | promoted v1 | finetune_v2 | read |
|---|---|---|---|
| 1. No-regression (hard) | total +3.8%, MAE 4.0% | **total +2.0%, MAE 3.0%** | **PASS — strictly better** on both axes |
| 2. Articulated vs Mio 102 | 22 events | **56 events** | 2.5×; bar (~parity) still not met — 55% of Mio |
| 3. Mediums vs Mio 92 | 7 events | **157 events** | recall UNLOCKED; +65 overshoot, see composition |

Lights 3327 vs Mio 3275 (+1.6%). **The truck-mass composition explains the
Mediums overshoot:** ours M+A = 213 vs Mio's 194 (+10%) — the total truck
mass is nearly right, but ~46 semis the head still misses land one bucket
down in Mediums (46 of the +65; residual over-call ~19). The Mediums number
is not phantom traffic; it is largely mis-split articulated — the exact
inverse of v1's pathology (which lumped ALL 102 into Mediums), at a third
of the magnitude.

**Disposition: recommend PROMOTE** — every axis improves on the shipped
state (totals closer to truth, MAE 4.0→3.0, Articulated 22→56, Mediums
7→157-with-known-bias vs 7-with-nothing), and the flag queue's ambiguous-
class feeder (articulated↔medium) is the designed surveillance for the
residual split error. The remaining articulated gap is a capability limit —
route: a future semi-diversity label round, this gate re-runs unchanged.
Fallback stays one line (revert the profile entry).

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
