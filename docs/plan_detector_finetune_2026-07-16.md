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

Labeling time (est. 2–4 operator-hours with pre-extracted proposals) and a
GPU budget (Colab Pro session or local). Everything else — extraction
scripts, replay scoring, held-out discipline — exists.
