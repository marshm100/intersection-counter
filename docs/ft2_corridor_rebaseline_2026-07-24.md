# ft2 corridor re-baseline — FINDINGS (2026-07-24)

The corridor scoreboard predated both fine-tunes (stock-era caches), so the
promoted ft2 chain was measured on the corridor's own study windows:
detect (ft2 OpenVINO @640, chain ids, conf .10 — the promoted profile
exactly) → production pass-1 recipes (incl. cam1's botsort+reid, ReID
sidecar rebuilt for the new cache) → replay → per-approach vs Miovision on
the replayed-minutes basis. Windows bit-identical to the stock baseline
(frame ranges read from the stock dumps' extents). cam3 (24 h, passing
3.2% live) excluded. Evidence: `runs/finetune_v2/corridor_ft2_rebaseline.json`;
per-window event counts in the session logs.

FRAMING (§0): the head trained on these cams' own frames — these are
production site-adapted numbers, the deployment flow at its most favorable;
FM51 (3.0% MAE held-out) remains the blind-generalization proof.

## The table (AVG|err|% per 15-min, full study windows)

| cam | basis | total | per-approach |
|---|---|---|---|
| 1 | stock | 4.0 | EB 21.0 · NB 5.9 · SB 2.4 |
| 1 | **ft2** | **26.1** | EB **93.9** · NB **36.3** · SB 9.7 |
| 2 | stock | 4.1 | EB 24.8 · NB 13.9 · SB 12.2 · WB 9.8 |
| 2 | **ft2** | 4.9 | EB **38.3** · **NB 8.9** · **SB 8.6** · WB 11.4 |
| 4 | stock | 4.7 | NB 4.6 · SB 9.1 |
| 4 | **ft2** | **11.6** | NB **10.0** · SB **22.1** |
| 5 | stock | 7.2 | EB 16.1 · NB 17.3 · SB 5.1 |
| 5 | **ft2** | **13.8** | EB **63.9** · NB 23.3 · SB 6.7 |

Event volumes: cam1 +26%, cam2 +5–9% (peak-correlated), cam4 +7%, cam5 +7%.
Detection density roughly doubles everywhere (cam2 14→32/frame; cam2 PM
54/frame), median confidence drops (.42→.28) — the add-missed far-field
labeling expressing itself; births stay gated at activation .25.

## The finding in one sentence

**The promoted detector's gains convert to counting accuracy ONLY where
downstream tracking/attribution is sound — everywhere it is weak, more
detections mean proportionally more misattributed events, and each
camera's known defect is amplified in its own signature way:**

- **cam1** (oblique far-field, the birth-late camera): newly-detected faint
  far-field traffic fragments into per-fragment events — every approach
  floods (+1,200 events, EB 94%). Even ReID re-association does not hold
  the new mass together.
- **cam2** (occlusion splits): the ONLY genuine wins — NB 13.9→8.9,
  SB 12.2→8.6 (the far-field recall the labels targeted, on the two
  recall-limited approaches) — while EB's SB-thru-occlusion double-count
  scales with the same density (24.8→38.3, worst at peaks: AM EB 83.5,
  midday 13.7).
- **cam4** (mid-block-birth origin grabs — the retired veto's class): SB
  9.1→22.1, NB 4.6→10.0. The far-field mass lands mid-road and mis-claims,
  exactly the phase-0 signature at scale.
- **cam5** (bank hole — no EB-thru path): EB 16.1→63.9. Traffic the stock
  model never saw now hits the missing-path wall in volume.

## Dispositions

1. **The corridor's applied production counts KEEP the stock-era basis**
   (they already do — pass-2 reuses existing caches). ft2 must NOT be
   re-detected onto corridor-class cameras until attribution hardens.
2. **The FM51 promotion stands on its own gate** (held-out, 3.0%), but this
   measurement defines its risk class: complex oblique multi-lane cameras
   with heavy far-field. The blind guards for that class are the
   conservation/volume feeders (a +26% event flood is exactly what they
   flag); whether the default profile needs an explicit caveat is an
   operator decision.
3. **The 5%-bar route through the corridor is attribution hardening, not
   detection.** The compound candidate: the item-8 evidence gate (proven
   cam2 9.1→3.3–3.5 on stock) behind its blind coverage precondition,
   now ALSO measured on the ft2 basis at cam2 — the one camera where ft2
   has real wins (NB/SB) that an entry-evidence gate could keep while
   suppressing the EB split-flood (a split fragment born mid-intersection
   crosses no entry gate). cam5 needs its bank-coverage hole closed
   (EB-thru path discovery), cam1/cam4 stay stock pending the same
   fragment-robustness work.

## Costs (for the record)

~1.04 M frames detected on the iGPU across 10 windows (~14 h wall incl.
the cam1 ReID-sidecar rebuild + one crash-resume — the sidecar dependency
of recipe botsort+reid on NEW variants is now a known launch step).
