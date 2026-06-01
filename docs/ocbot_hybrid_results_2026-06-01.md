# OC+BoT per-regime hybrid — results (2026-06-01)

Built per docs/handoff_ocbot_hybrid_2026-06-01.md. cam1, project 97a7849a,
07:00–07:30, detection cache `balanced_960_skip1.parquet`. Metric = per-minute
GROSS (scripts/od_accuracy.py), corrected leg labels {22:NB,23:SB,24:EB,25:WB}.

## Headline
| config | net | per-min gross |
|---|---|---|
| OC-SORT only (baseline, `recal_cam1_odturns.json`) | 21.8% | 30.7% |
| BoT-SORT only | 24.4% | 32.0% |
| OC+BoT combine, **boundary dedup** | 24.5% | 31.8% ❌ |
| OC+BoT combine, **no dedup** | 20.1% | 28.3% |
| **OC+BoT, no dedup + intra-turn merge** | **15.8%** | **27.3%** ✅ |

Best = OC throughs ∪ BoT turns (no cross-backend dedup) + intra-turn fragment
merge. **gross 30.7% → 27.3%, net 21.8% → 15.8%.** Plus a correctness win: the
NB-right through-fragment phantom drops 35 → 9.

Reproduce:
```
py scripts/hybrid_ocbot.py --no-dedup --merge-turns --show-od
```

## What worked
- **Regime split at the event level.** Take `movement='through'` from the OC-SORT
  retrack (`relabeled.db`) and `movement IN (left,right,u_turn)` from the BoT-SORT
  retrack (`botsort_fresh.db`). Both arms retracked on the SAME bank
  (`recal_cam1_odturns.json`) + SAME cached detections, so OD geometry is identical;
  we only choose which tracker owns each movement regime. BoT's turn cells are much
  cleaner than OC's (NB-right phantom 9 vs 35, SB-right 38 vs 44).
- **Intra-turn fragment merge** (`scripts/hybrid_ocbot.py` `merge_turn_fragments`).
  BoT fragments one turning vehicle into several events (coasts the sharp curve, the
  pipeline finalizes the stub, then re-tracks the exit). Merge events sharing the
  SAME (origin,dest,movement) whose starts are within 30px / 40 frames → one vehicle.
  NB-left 136→96 (exact), EB-left 45→34, SB-right 39→31. This is **far safer than the
  arterial through-stitching the project refuses** (memory project_leg_labels_swapped
  / dedup_ceiling): turns are low-volume and constrained to one OD cell, so a ~1.3s
  same-spot same-turn follower (the false-merge risk) is rare.
- **Robust, not knife-edge.** Sweeping merge px∈{20,30,40} × gap∈{20,40,60}: gross
  stays 27.2–27.6% throughout. Temporally stable: 07:00–07:15 = 27.9%, 07:15–07:30 =
  26.8% (vs OC's wider 32.5 / 28.3).

## What failed (the handoff's predicted wall)
- **Cross-backend boundary dedup false-merges on the dense arterial.** Dropping an
  OC through when a BoT turn overlaps in time + starts within 60px deleted **154**
  OC throughs (NB-thru crashed 529→425) because a through and a turn routinely enter
  from the same arterial leg at overlapping times — start-proximity + time-overlap
  cannot separate them. Same conclusion as the sequential-stitching dedup ceiling.
  **Use `--no-dedup`.**

## Honest residual (the floor at 27.3%)
The remaining gross is dominated by **throughs**, which OC owns and the combine does
not touch — this is the documented through recall/over-track tension, not fixable by
any position-based tracker swap:
- NB-thru 529 vs 595 = **−66 under** (124 gross) — the OC `min_hits=3` price.
- SB-thru 486 vs 425 = **+61 over** (81 gross) — OC over-tracking; can't merge (unsafe arterial).
- → throughs alone = 205 of 332 gross (62%).

Plus **EB-right (EB→NB) = 1 vs 36** (35 gross), UNRECOVERED:
- The raw BoT tracker sustains **11** EB-right tracks (scripts/probe_tracker_od.py),
  but the pipeline event layer keeps only **2** — confirmed on both `botsort2.db` and
  a fresh retrack. So the BoT-derived bank (`recal_cam1_botturns.json`) reports
  EB-right `too_few` and **cannot emit an EB-right path** (Step 1's goal is blocked).
- It is NOT a clean entry/exit fragmentation (0 entry-stubs ending mid-intersection),
  and NOT the no-origin gate (EB-left, same L24 entry, survives 18–20). It's a deeper
  sharp-cross-street tracking loss inside the pipeline, documented across several
  sessions as detection/tracking-bound. Recovering it needs pipeline surgery (uncertain
  payoff, slow retrack iterations) or ReID — out of scope for this position-based pass.

## Bottom line
The position-based regime split + intra-turn merge is a **genuine, robust net
improvement over OC-SORT** (gross −3.4pts, net −6.0pts) and removes the NB-right
phantom. The cross-backend dedup hit the predicted complexity wall and was dropped.
The 15% gross target is not reached: the gap is the through tension + EB-right, both
needing ReID / better detection, not another position-based lever. Nothing applied to
production (engineer visual gate still pending). EB-right residual should route to
human review until a tracking/ReID project addresses sharp cross-street turns.

## Artifacts
- `scripts/hybrid_ocbot.py` — the combine (regime split + dedup + intra-turn merge + measure).
- `scripts/recalibrate_camera.py` — new `--db` arg to derive a bank from any events DB.
- `evaluations/recal_cam1_botturns.json` — BoT-derived bank (no EB-right path; documents the gap).
- `data/projects/97a7849a/_hybrid_tmp/{relabeled,botsort_fresh,ocbot_merged}.db` — arms + combined output.
