# Handoff — per-approach attribution (2026-06-30, session 2)

Branch `claude/accuracy-impl-2026-05-27`. New commit **`1ead6c3`** on top of
`d6ab618`. **`1ead6c3` is committed but NOT pushed** (push when ready). Continues
`docs/handoff_2026-06-30.md` (this session's start) and `docs/MASTER_PLAN.md`.

## Goal
The #1 lever from the acceptance metric (`MASTER_PLAN §1b`): **per-approach
attribution** — totals pass ≤5%/interval but per-APPROACH fails on nearly every
camera because errors cancel. Diagnose, close cells, re-measure.

## What shipped (`1ead6c3`, suite green: 633 passed; only the 2 known pre-existing fails)
- **`scripts/replay_fullchain.py`** — the campaign's measurement instrument.
  Re-attributes stored `vehicle_events.trajectory_data` through the REAL
  `ProcessingPipeline` (`_assign_origin` + `score_path_joint` + origin-rewrite
  gate + fallback) with NO detection/tracking, so any bank/matcher change is
  scored on `interval_metric.py` in minutes. Validated: reproduces live
  per-approach within ~2pp (cam2 EB 46.9 vs live 44.2). `--bank` swaps the whole
  bank, `--extra-paths` injects paths.
- **`build_bank_gtfree.py` QA-flag** — every cardinal-legal movement with NO
  admitted path is reported (`legal_movement_uncovered`, "draw a channel").
  Correctly flags cam2 SB-left (27→26) + NB-right (29→26). Closes the gap where a
  blind operator couldn't tell a real movement was silently dropped.

## Diagnosis (rigorous, evidence in memory `project_per_approach_attribution_2026_06_30`)
- **Mechanism:** the bank matcher READS ORIGIN OFF THE WINNING PATH, so a
  shape mis-match reassigns the vehicle's *origin approach* — exactly what the
  per-approach metric catches; errors cancel in the total.
- **cam2 root cause = a MISSING bank path (SB-left).** Dropped by BOTH builders
  because nearest-anchor grouping bins a turn's DESTINATION by nearest anchor
  POINT: SB-left ends nearest the NB anchor (not WB) — 100/103 — and its exit
  bearing (~270°) is 24° from NB vs 36° from its true WB exit, so the
  exit-bearing `_rebin` can't pull it out either. Only mid-path CURVATURE
  distinguishes SB-left from the collinear SB-thru. Missing SB-left caused a
  DOUBLE error: SB-left undercount + an EB-thru MAGNET eating the orphans
  (their exit endpoints nearly coincide).

## Proven lever (real interval metric, via the replay)
Adding a clean SB-left path to cam2: **EB 46.9→32.4 (−14.5pp), SB 18.2→12.0
(−6.2pp)**, NB/WB zero collateral, no over-collection (the apply-time turn
tail-prior gate handles it). A 3-point operator-DRAWN channel reproduces it
exactly (EB 33.1/SB 12.2). Blind-safe — SB-left is a real legal movement.

## Channel productionization — RESOLVED (`4f05578`)
The blind way to supply the clean path is an operator channel. Two dead ends
(both validation-caught): forcing a channel's **drawn** polyline regressed cam5
(2.9→13.4% — good refits replaced by rough drawings); a **coherence gate** also
regressed cam5 (13.0% — spreads overlap, can't separate cam2's CORRUPTED refit
from cam5's noisy-but-usable one).

**Root cause was just the `+20` halfw floor** (`halfw = width/2 + 20`). A
claim-purity sweep on cam2 SB-left: at halfw 20 the channel grabs 116 EB-thru vs
98 real SB-left (corrupt refit); at **halfw 12** it claims 241 SB-left-shaped
tracks, refit spread 19px, matching the drawn SB-left within 9px (clean). Fix:
**`--channel-buffer-px` (default 20, back-compat)** — a collinear turn uses a
tight buffer (e.g. 4) so the *existing* refit works; cam5 unchanged by
construction. Validated: cam2 rebuild with the tight channel emits a clean
SB-left path → the proven EB 46.9→33 / SB 18.2→12 gain.
`experiments/channel_replay/channels_cam2.json` is the validated SB-left channel.

## What's next (ordered)
1. **Ship the proven cam2 gain to the live corridor** — add the clean SB-left
   path to the live bank + retrack (expensive), so the deliverable's per-approach
   actually improves now. (Legacy GT bank — acceptable for the dev corridor.)
   Also run the cam2 NB-right movement the QA flag surfaced.
2. **mdh→dtw_mean all-cam sweep** (deferred, "measure don't change"): cam2 EB's
   residual (32%) is the collinear EB-thru/EB-right that `mdh` can't separate
   (it hard-wires coverage=1.0). dtw_mean fixes EB-thru exactly but overshoots
   EB-right; mdh was adopted on NET (cam4 22.5→14.7). Run per-approach + net
   under both metrics across all 5 cams, decide the default with the user. Use
   `replay_fullchain.py --bank` (cheap) — no retracks.
3. **cam2 SB-right** (tiny 105px path, −42%) and **cam5/cam1** per-approach cells.

## Gotchas
- `scripts/od_accuracy.py` uses the PRE-flip leg convention (`_CARD2PREFIX`
  N→NB) → mislabels by 180°. Use `interval_metric.py` / `triangulate_manual.py`.
- The replay's provisional origin runs on the full stored trajectory (vs the
  live partial prefix) → ~2pp drift on the fallback population. Always run the
  live-bank replay first to confirm it tracks `interval_metric.py` before an A/B.
- The naive entry-position origin gate FAILS (cam2 14.4→23.5): FOV clips
  approaches so `nearest_origin(first_point)` is unreliable even for throughs.
- Background `cmd > file.txt 2>&1; tail` loses output when wrapped in `timeout`
  or piped to `head` — redirect to a file and `cat` it.

## Tools & data
- `scripts/replay_fullchain.py` (NEW), `scripts/interval_metric.py` (the metric),
  `scripts/build_bank_gtfree.py` (QA-flag), `scripts/triangulate_manual.py`.
- Memory: `project_per_approach_attribution_2026_06_30`,
  `project_interval_metric_baseline`, `project_turn_residuals_2026_06_08`,
  `project_build_bank_recovery`, `project_phase2_gtfree_2026_06_11`.
