# A4a — production turn-merge gate results (2026-07-10)

Plan: `docs/plan_A4_stage3_2026-07-10.md`. Shipped:
`backend/services/turn_merge.py` (mechanism ported verbatim from
hybrid_ocbot — scripts re-import; frozen constants), `sample_window_seconds`
on `intersection_paths` (migration + corridor backfill 1800 s),
`merge_replay_turns` post-pass (merged fragments → `rejected=1`, reviewable;
throughs untouched by construction), the S5 emitter path
(`s5_flags` + `rebuild_flags(extra_flags=...)`), 9 new tests (61/61 pass).

## Run 1 — ×-scaled 30-min expecteds: GATE FAIL, recipe retired

With the applied banks' supports scaled ×4 (30-min sample → 2 h window):
cam4 MAE 4.6→5.1%, cam5 8.7→11.0% — both worse than live. Root cause:
thin-sample extrapolation. cam5's EB-left expected scaled 11×4 = 44 while the
real 2 h volume is ~90 — the gate under-expected and over-merged (−14 real
vehicles). **Extrapolated expecteds are RETIRED; the merge requires
corpus-window supports (scale 1).** The §3-A pass-2 flow provides this by
construction (the bank is built over the same corpus it counts).

## Run 2 — scale-1 corpus expecteds (2 h banks, QA-observed per-cell n)

| cam | live baseline MAE | replay+merge MAE | verdict |
|---|---|---|---|
| 5 | 8.7% (EB 17.5 FAIL) | **7.1% (EB 12.7)** | **PASS — better than live** |
| 4 | 4.6% | 5.1% | FAIL by 0.5 pt — cause outside the merge (below) |

cam5 detail: 1,048 raw turns → 758 kept; NB-left converges +264 (unmerged) →
−20 vs live; every through cell exact (SB 1752 = 1752, NB 2468 = 2468); the
S5 borderline fired on the real noise-sensitive cell each run. 15-min AVG
2.2% PASS (live 2.3%).

cam4 detail: the merge only touched 24 fragments and IMPROVED its cells
(EB-left +35 → +31). The residual vs live is pre-merge attribution, and the
bank builder names the root cause itself: **LEG SANITY — leg 34 calibrated
119.4° but traffic enters at 266.4°** (label/heading defect on the side
street), plus 3 missing-movement flags (cam4 has NO drawn channels). This is
operator calibration work — exactly what the QA queue and calibration studio
exist for — not merge mechanics. Goes on the stage-3 work list next to
cam1-ReID and cam2-botsort.

## Adopted recipe (production)

Pass-2 merge expecteds = the corpus-built bank's per-cell observed support
with `sample_window_seconds` = the corpus window (scale 1). The harness
approximated this with the 2 h gtfree QA per-cell n (claim contamination on
cam5's WB-left/N-right cells only errs CONSERVATIVE — inflated expecteds
block merging, never force it). No constant changed anywhere: merge_px 30,
merge_gap 40, vol_factor 1.3, S5 band ±0.2, all frozen.

## Stage-3 work list additions

1. cam4 leg-34 calibration review (operator; the builder flag + S4/S5 flags
   surface it — verify it lands in the queue at the cam4 pass-2 run).
2. The pass-2 orchestration must persist the corpus window into
   `sample_window_seconds` when it applies the bank.
