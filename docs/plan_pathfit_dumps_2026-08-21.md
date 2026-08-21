# Pathfit-from-dumps (B2 of the one-system pipeline) — gate doc

Declared BEFORE any scored run (gate discipline). Operator authorized
the autonomous regate 2026-08-21 ("stage → apply → arm → ship-or-
restore, like last night").

## What is being tested

The W1a apply (2026-08-19) lost the movement bar for two measured
reasons: (1) three cells had no path because a 15-minute sample gave
them 0–6 clean journeys; (2) turn-merge deactivated under shifted
expecteds. B2 re-derives the cam2 path set from the production pass-1
dumps — 3 windows × 2 h pooled (~13.5 h of tracked traffic at 25 fps)
— cut-clean against the confirmed gates, fold-gated, cardinal-labeled.
Prediction: the three W1a-collapsed cells ((28,27) EB left, (27,28)
SB right, (26,29) WB left) self-evidence with real support, removing
loss mechanism (1). Mechanism (2) is instrumented this run
(merge_expecteds in every pass-2 result) and diagnosed from the
ctrl/arm diff — no constant re-freeze a priori.

## G-PF2-1 (the ship gate)

- PASS: arm pooled 3-window movement bar (5/95 cell-bins, pooled
  compliant/scored) **> 46.7%** (ctrl pooled 148/317), AND no single
  window more than **2.0 points below** its control (ctrl per-window:
  study_0700 53.4, study_1100 42.9, study_1600 44.0).
- Approach bar recorded alongside (secondary; ctrl pooled 40.6%).
- MISS: byte-verified restore from backup (the rehearsed 2026-08-19
  procedure), suggestion back to pending, negative ledgered here and
  in the roadmap.

Controls are REUSED from 2026-08-19 (score_pathfit_ctrl_cam2_study_*
.json) — same replay basis, valid because production cam2 geometry and
events were byte-restored after the W1a verdict (re-verified before
comparison this run).

## Procedure (pre-registered)

1. Suite green; §8 production per-window counts verified.
2. `run_pathfit_cli.py --dumps --dry-run` — confirm the three cells'
   support; stage for real; fold-audit the staged payload.
3. Apply via the live endpoint; verify 0 skipped, live fold audit,
   events untouched. Any cell still below support: proceed, name the
   gap in the verdict (operator present Friday for hand-draw).
4. Backup `project.db.bak_pathfit2_20260821` (sqlite backup API).
5. Arm replays study_0700/1100/1600 sequentially, detached
   (Start-Process runner + Monitor on log+err).
6. Score → `runs/v2_week1/score_pathfit2_arm_cam2_study_*.json`.
7. Diff `merged_away` + `merge_expecteds` ctrl-vs-arm from the stats
   sidecars; findings recorded below.
8. Verdict here + roadmap + commit, either way.

## Amendment 1 (declared 2026-08-21 after the unscored dry-run, before
## any staging or scored run)

Dry-run finding: the (28,27) EB-left fit from 247 cut-clean fulls
measured 103.3° concentrated turn — rejected by PATH_FOLD_REJECT_DEG
100, yet far below every condemned fold (116–173°) and supported by
two orders of magnitude more clean journeys than the W1a-condemned
paths had. W1a measured that an ABSENT path collapses its cell worse
than a folded one. Amendment: for CUT-CLEAN fits (this CLI only), the
band [100°, 120°) is keep-plus-flag (`shape_flag:
"sharp_apex_review"` — operator eyeballs it in the preview; they own
geometry); ≥120° (the pinch law) stays reject. Raw-discovery
(auto_calibrate.discover_paths) keeps the strict 100° reject — raw
members are uncut and contamination-prone. Also recorded: (27,28)
SB right yields only 5 fulls from 13.5 h against ~800 real vehicles —
a structural gate-span defect at the 28 mouth (B1 evidence), not
sample thinness; the cell stays path-less this run and the gap is
named in the verdict.

## Verdict — G-PF2-1 MISS (2026-08-21); RESTORED; root cause isolated

| window | movement ctrl → arm | approach ctrl → arm |
|---|---|---|
| study_0700 | 53.4 → 44.3 (**−9.1, breach**) | 50.0 → 46.9 |
| study_1100 | 42.9 → 44.9 (+2.0) | 40.6 → 28.1 |
| study_1600 | 44.0 → 41.7 (**−2.3, breach**) | 31.2 → 46.9 |
| pooled | 46.7 → **43.6** (bar: >46.7) | 40.6 → 40.6 |

Restore executed byte-verified against project.db.bak_pathfit_20260819
(10 rows, ids 119–128; suggestion back to pending; events untouched
18,269). Score artifacts: runs/v2_week1/score_pathfit2_arm_cam2_*.json
vs the reused score_pathfit_ctrl_cam2_*.json.

**The negative is decisive, not ambiguous: every mechanism points at
the GATES, not the paths.**
- SB right went to literal 0 at 0700 (ctrl 214 via the old fold; Mio
  379) — no path can fill a cell whose journeys never cross the 94 px
  gate stub (defect measured above).
- WB left produced 3 events at 0700 DESPITE having a clean 41-support
  path for the first time — and the corpus bank built from the same
  dumps EXPECTED 42 there (merge_expecteds, new instrumentation). The
  system sees the traffic; classification's gates drop it.
- The displaced mass overshoots neighbors (NB left 578 vs Mio 411;
  SB thru 1605 vs 1384) — attribution redistributes what the funnel
  lets through.
- turn-merge stays partially deactivated (merged_away ctrl
  237/379/492 → arm 125/199/345): expecteds and event distributions
  both moved; secondary to the funnel defect.

## Revival conditions (supersede W1a's)

Path quality is PROVEN (fold-audited, cardinal-labeled, full-trim
support); the funnel is the cap. Order for the next attempt:
1. Operator draws GATE LINES (B1) — the Friday session; gates are the
   root every stage funnels through (classify, census, cutter,
   pathfit, u-turn tests).
2. Re-run pathfit --dumps against the drawn gates (seconds; the cut
   and classification both improve, (27,28) should self-evidence).
3. ONE regate of the combined basis (drawn gates + refit paths):
   fresh CONTROLS first (drawn gates alone change the basis; the
   2026-08-19 controls die with the old gates), then arm.

## Gate-span defect measured (the B1 evidence, 2026-08-21)

Diagnostic on study_0700 with the PRE-apply gate basis
(screenshots/gatespan_cam2_sbright_2026-08-21.png): **1,275** journeys
entering leg 27 die unexited in one 2-h window; **460** of those die
within 150 px of the 28 mouth; the derived 28 gate is a **94 px stub**
positioned above the actual travel lanes, and two other legs' gates
run as long diagonals across the intersection (the channel-tangent
orientation defect, measured 49–85° off on other cameras, made
visible). (27,28) SB right registers **3** fulls in the window against
~379 real vehicles — the cell's thinness is a GATE defect, not a
traffic or tracking one. This is the root-cause case for B1
operator-drawn gate lines: classify, census, the cutter, and pathfit
all funnel through these segments.

## Coupling diagnostic findings

merge_expecteds landed in every pass-2 stats sidecar (first
instrumented run). Arm expecteds are sane per cell — e.g. (26,29)
42/41/30 across windows, (27,26) 500/465/785 — confirming the corpus
bank tracks real traffic while the gate-starved classifier cannot
count it. Controls predate the field; the next ctrl/arm pair (post
drawn-gates) diffs it both ways.
