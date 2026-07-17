# Plan — §3-D domain-fine-tuned detector (2026-07-16)

The capability track, promoted: item 8's closure established that the
corridor's remaining per-approach error is dominated by RECALL-class
deficits (never-journeyed pools, SB-right true recall 0.12–0.16, the FM51
PM low-light miss), not attribution. Scoped from
`detector_derisk_spike_2026-07-08` (which killed the config-knob lever and
justified the fine-tune at its real targets). This doc makes the track
startable the moment labels/GPU are allocated; nothing else blocks on it.

## Targets, in order

1. **Articulated (FHWA 8–13)** — beat the ~70% bbox-size heuristic
   (`project_articulated_classification_2026_07_06`). Cleanest win: a
   trained class vs a geometric proxy; FM51 gives dev labels (102 Mio
   articulated) but the GATE is a held-out SITE.
2. **Low-light / far-field recall** — the FM51 PM −12–20% window and the
   corridor's far-field birth-late truncation (the never-journeyed family).
3. Explicit NON-target: per-site accuracy tuning of any kind (§0 litmus).

## Dataset design (the overfit guard is the design)

- Sites: corridor (5 cams) + FM51 + the rehearsal project + any new client
  footage as it lands — minimum 3 distinct sites in TRAIN, one full site
  held out ENTIRELY (rotate FM51 out first since its answers are the most
  reused in dev).
- Sampling: stratified crops — dusk/PM windows, far-field bands (top third
  of oblique frames), truck-heavy intervals; hard negatives from the
  phantom/flicker classes the track-quality gate rejects.
- Volume: a few hundred boxes/site to start (the spike's estimate);
  label classes = vehicle + articulated (two-class head keeps the labeling
  cheap and the win measurable); iterate only if the gate says the ceiling
  is data.
- Tooling: frames + proposals pre-extracted from the detection caches (no
  re-decode); labels reviewed in any COCO-format tool the operator likes.

## Training + the gate

- Base: current yolo26s (OpenVINO export path already in
  `scripts/export_yolo_openvino.py`); fine-tune on Colab/local GPU;
  reproducible seed + manifest committed.
- **Gate (held-out SITE, frozen weights):** (a) articulated recall/precision
  vs the held-out site's Mio classes — must beat the size heuristic's ~70%
  recovery WITHOUT precision collapse; (b) detection recall in the
  far-field band + PM windows vs the current model (proxy: detections
  matched to Mio per-interval volumes, the derisk-spike method); (c) the
  full counting chain on the held-out site must not regress per-approach
  MAE (replay from fresh detections — the two-pass replay makes this
  cheap). PASS → ship as the default model with the old one as fallback
  config. FAIL → findings, iterate dataset (not knobs).
- Corridor probes (dev-only, never the gate): cam2 SB-right trackable pool
  63/40 → should grow; never-journeyed 585 → should shrink.

## Prerequisites to allocate (the actual blockers)

Labeling time (est. 2–4 operator-hours with pre-extracted proposals).
Everything else — extraction scripts, replay scoring, held-out discipline —
exists.

## REVISED 2026-07-16 — local CPU training, chunked (user decision)

Compute is NOT a blocker. The Iris Xe cannot train (no practical PyTorch
backend for an 11th-gen iGPU; OpenVINO is inference-only), but the CPU can:
a SCOPED job (freeze the backbone, imgsz 640, two-class head, a few hundred
images) lands at ~8–24 h total — run as **chunked sessions of 5–10 epochs**
so the laptop stays usable and any interruption costs at most one chunk.

- **Chunking = sequential warm-start runs** (`scripts/finetune_detector.py`):
  chunk k trains E epochs from the previous chunk's `last.pt`, with a global
  LR decay across chunks (lr0 x gamma^k) standing in for the one-run cosine
  schedule. Deliberately chosen over ultralytics' `resume=True` single-run
  interrupt flow: warm-start chunks are deterministic and restartable after
  ANY kind of death (sleep, kill, crash) with no "run already complete"
  edge cases. A manifest JSON tracks cumulative epochs per run dir.
- **Label prep** (`scripts/prep_finetune_labels.py`): stratified frames from
  the detection caches (truck-heavy frames prioritized 50/50 with
  uniform-in-time), proposal boxes prefilled as class 0 `vehicle` in YOLO
  txt format — the operator's job is accept/fix boxes and PROMOTE semis to
  class 1 `articulated` (everything prefills 0 so the prefill cannot bias
  the articulated labels). Any YOLO-format labeling tool works on the
  emitted dataset directory.
- Training defaults: base yolo26s.pt, imgsz 640, freeze=10, epochs-total 40
  in 8-epoch chunks. The GATE is unchanged (held-out SITE, three parts) —
  chunked local training changes logistics, not the discipline. After a
  PASS, export via `scripts/export_yolo_openvino.py` so inference stays on
  the iGPU.

## RUN 1 RESULTS (2026-07-16 overnight) — trained; gate part 1 POSITIVE

- **Dataset v1**: 430 corridor frames (FM51 fully held out), human-labeled
  in the in-app labeler: 4,734 vehicle / 208 articulated / 139 long_single
  boxes after the semi-mining top-up (`--mode semis` tripled the semi
  class). Lesson paid for: verify the page build AND the persisted counts
  around every labeling handoff (one pass was lost to a stale page).
- **Training**: 64 epochs in 9 warm-start chunks (~10 min/chunk early,
  ~40 min on the doubled set) entirely on the laptop CPU. Best checkpoint
  = chunk 6 (56 epochs): overall mAP50 0.64, vehicle 0.76, articulated
  0.60 (P 0.79), long_single 0.54 on the enlarged val split. Extension to
  64 declined -> stopped per policy; 80-epoch cap never needed.
- **Gate part 1 (FM51 detection A/B, `fm51_detect_ab.py`, 1,800 sampled
  frames, both peaks): the fine-tuned model detects MORE in EVERY
  interval — +25–45% detections/frame — including the documented PM-miss
  window (16:45: 0.75→1.04/frame; 17:30: 0.91→1.13)**, on a site it never
  trained on. The far-field top-third split registered zero for BOTH
  models — the band is mis-calibrated for FM51's geometry (road sits low
  in frame); re-cut per-camera before reading that metric.
- **Open question for parts 2–3**: cross-site articulated transfer looks
  thin at frame level (7 art / 42 long glimpses across the windows vs
  Mio's 102 articulated day-total) — sparse 0.1 fps sampling can't settle
  it; the TRACK-level full-chain comparison decides. If it confirms weak
  transfer, the fix is a third site's semis in train (FM51 stays held
  out), not more corridor epochs.
- **NOT promoted**: the model ships nowhere until the full-chain gate
  passes; weights at `runs/detect/runs/finetune_v1/chunk6/weights/last.pt`.

## GATE PART 3 (2026-07-17): FULL-CHAIN on held-out FM51 — PASS

`fm51_fullchain_ab.py`: fine-tuned detections (OpenVINO @640, production
conf 0.10, classes mapped for chain parity) -> production pass-1 tracking ->
replay through the rehearsal's applied bank; scored vs the SHIPPED old-chain
events and Miovision per 15-min interval (`runs/finetune_v1/fm51_fullchain.json`).

- **TOTAL: Mio 3,469 | old 3,155 (−9.1%) | new 3,602 (+3.8%).**
- **Mean |interval err|: 8.8% -> 4.0% — halved, and under the ≤5% bar** on
  a site the model never trained on.
- **The documented PM miss is CLOSED**: 16:45 −19.0%->+0.5%, 17:00
  −17.2%->−0.4%, 17:15 −20.0%->+0.8%, 17:30 −12.8%->+2.7%. The evening
  capability gap that motivated §3-D no longer exists in the chain.
- **Residual, named:** a consistent mild OVERSHOOT (+6–9%) in the
  highest-volume intervals — the higher-sensitivity detector converts a few
  extra fragments into counted events. Before promotion: the per-approach
  cut (audit_fm51 machinery on the new working DBs) and a spot-check of the
  overshoot class (phantoms vs genuine recoveries).
- Remaining for promotion: per-approach MAE cut, overshoot spot-check,
  wiring the native articulated class into the deliverable (post-promotion
  integration), and the model-file/config swap through the product flow.
  Promotion is the OPERATOR's call on this table, per plan.

## PRE-PROMOTION CHECKS (2026-07-17): the complete decision table

Parity fix first: the replay DBs lacked the `through_gate` post-pass the
shipped events received — applied (95 impossible T-stem throughs killed).

| cut | old chain | new chain (parity) |
|---|---|---|
| TOTAL (4 audited hours) | −9.1% | **+1.1%** |
| mean abs err / 15-min | 8.8% | **2.5% PASS** (max 5.7%) |
| PM 16:30–18:00 | −12…−20% | −0.4…+3.8% |
| SB FM 51 (1,741) | −0.3% | −6.5% |
| NB FM 51 (1,668) | −19.2% | **+4.6%** |
| WB Co Rd 4699 (60) | +20% (72) | +122% (133) |
| abs approach-level misplacement | ~338 veh | ~263 veh |

**The overshoot mechanism, isolated:** the new detector's earlier far-field
births near the T-stem get their ORIGIN grabbed by the side leg — S-through
2→97 (impossible movements, killed by the gate), S-left 3→54, S-right
67→76 — draining SB (−114). One mechanism, both regressions.

**Countermeasure test (negative, valuable):** replaying the same dumps with
ORIGIN_EVIDENCE_GATE_ENABLED changed almost nothing (side +117%, SB −5.2%) —
FM51's entry-gate geometry is BLIND to the traffic (evidence coverage
5.5% AM / 1.9% PM vs cam2's 80%). Third data point confirming: the evidence
gate requires per-camera gate-geometry QA (n_evidenced/n_tracks is the
blind health check) before it means anything at a site.

**The trade, stated plainly:** the new chain is better on total (+1.1% vs
−9.1%), interval MAE (2.5% vs 8.8%, PASS), the PM window (fixed), NB
(fixed), and total absolute misplacement (263 vs 338) — and worse on SB
(−6.5% vs −0.3%) and the small side road (+73 vs +12 vehicles). Options:
(A) promote + let the flag queue surveil the side-leg cells; (B) hold for a
targeted far-field origin-grab fix (mid-block-birth class); (C) promote
detector + open the origin-grab fix as the next gate cycle. Operator's call.
