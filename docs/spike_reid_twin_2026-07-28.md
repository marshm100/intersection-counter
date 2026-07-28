# Spike — ReID twin test (2026-07-28)

The convergence candidate after the LANE+ECHO cycle close: cam5's
unchained-concurrent-echo residual (thru bands missed held-out) and
cam2-EB's occlusion-split wall (17.2 production; 305 confirmed concurrent
ID-splits, corr 0.58 with SB-thru volume) are the SAME mechanism class —
one vehicle, multiple concurrent tracks. Image-space geometry cannot
separate twins from real neighbors at far-band compression (measured
2026-07-09, re-measured stronger at lane+echo iteration 2). Appearance
is the one untried signal: osnet_x0_25 embeddings — the shipped cam1
ReID machinery, byte-identical call path — were measured discriminative
at 20–40 px (AUC 0.87–0.89, reid_project_plan_2026-06-01).

This spike de-risks BEFORE any mechanism plan or cache build (a full
per-camera ReID sidecar is hours of compute; the spike embeds only
sampled pairs' crops).

## Design (scripts/spike_reid_twin.py; cam5 study_0700, event tracks)

Four pair populations: **seq** (direction-gated sequential chain edges =
same vehicle, calibration positive), **far** (co-temporal at 150–400 px
= different vehicles, easy negative), **near** (co-temporal within
60 px, FAILING the CD twin test = the hard negative: followers /
adjacent-lane), **twin?** (the CD-caught pairs — the population to
place). Anti-confound: overlapping boxes share pixels, so each track is
embedded only at CLEAN frames (outside co-life or partner-IoU < 0.05);
pairs with no clean frames are scored but flagged. Similarity = cosine
of per-track mean embeddings.

## Decision gate (pre-declared)

Proceed to the mechanism plan iff **seq-vs-near AUC ≥ 0.85** on
clean-frame similarity AND the twin? population places interpretably
(bimodal or clearly one-sided against the calibrated classes). Otherwise
the appearance candidate dies at spike cost and §3-B becomes the
recommended next block.

---

## VERDICT (2026-07-28 — FAIL; evidence runs/cam5_wall/spike_reid_twin.json)

**AUC seq-vs-near = 0.399 — worse than chance.** Similarity quartiles
(cosine, clean-frame per-track means, 0 pairs flagged):

| population | n | q0/q25/median/q75/max |
|---|---|---|
| seq (same vehicle, sequential) | 120 | .442 / .743 / **.802** / .845 / .961 |
| far (different, 150–400 px) | 120 | .500 / .701 / **.777** / .828 / .943 |
| near (different, <60 px, CD-fail) | 119 | .652 / .774 / **.820** / .868 / .947 |
| twin? (CD-caught) | 69 | .480 / .603 / **.691** / .787 / .956 |

Two different vehicles at the same spot score MORE similar (.820) than
the same vehicle at two depths (.802); the twin candidates score LOWEST.
At the 640×480 source, far-band crops are 10–30 px: osnet_x0_25 measures
WHERE and HOW BIG, not WHAT. The cam1-era AUC 0.87–0.89 was same-depth
association; it does not transfer across depths at this resolution.

**Consequence:** the appearance twin-test dies at spike cost (no cache
builds, no plan). THREE mechanism families are now measured dead on the
far-band concurrent-twin problem — image-space geometry ×2 (2026-07-09,
lane+echo iteration 2) and appearance ×1 (this) — which reclassifies the
residual thru-band excess as a **SOURCE-RESOLUTION wall** (the PRD-era
"640×480 is partly a resolution wall" note, now with a mechanism-level
proof for this failure class). Per the pre-declared gate: **§3-B
blind-gate validation is the recommended next block**; higher-resolution
source video is the named capability-track prerequisite for ever
reopening the twin problem.
