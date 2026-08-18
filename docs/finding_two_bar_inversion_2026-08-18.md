# FINDING — the two-bar inversion (2026-08-18)

**The PRD's own accuracy bar is HARDER for this pipeline than the
campaign's movement bar, and the gap is made of missing vehicles, not
missorted ones.**

## The two bars

- **Movement bar** (campaign standard since 2026-07-28): per
  movement-cell per 15-min bin, |ours−ref| ≤ max(5·bins_equiv,
  5%·ref). THE engineering bar; all 246 recorded scores use it.
- **Approach bar** (PRD §7.2 as written): total vehicles per APPROACH
  per 15-min interval within ±5%, target ≥95% of intervals. First
  measured today (scored with the same rule595 small-count grace —
  friendlier than the PRD literal, and the conclusion still holds).

## The measurement (live production, 13 Mio-covered windows)

  window            movement   approach   PRD>=95
  cam1 study_0700     60.5%      62.5%      miss
  cam1 study_1100     78.5%      71.0%      miss   (first-ever score)
  cam1 study_1600     54.5%      40.6%      miss
  cam2 study_0700     55.8%      25.0%      miss
  cam2 study_1100     55.0%      46.9%      miss
  cam2 study_1600     49.5%      31.2%      miss
  cam3 study_0600     72.6%      28.0%      miss   (14 h window)
  cam4 study_0700     75.4%      37.5%      miss
  cam4 study_1100     73.5%      41.7%      miss
  cam4 study_1600     75.8%      66.7%      miss
  cam5 study_0700     66.4%      50.0%      miss
  cam5 study_1100     71.7%      40.6%      miss
  cam5 study_1600     63.1%      21.9%      miss
  AVERAGE             65.6%      43.4%      0/13 PASS

Artifact: runs/v2_week1/two_level_scores_2026-08-18.json. Movement
column reproduces the committed standings exactly (harness parity).
Historical context: no recorded score on ANY bar has ever reached 90%
(best ever: 87.5% movement-bar, held-out FM51 site, replay-isolated
dev arm; best production: 75.8%, cam4 study_1600).

## Why the intuition inverted

The pre-registered expectation (2026-08-18, this session) was that
approach totals would score HIGHER because misclassified turns cancel
inside an approach. Falsified, for two mechanism reasons:

1. **The movement bar's ±5 small-cell grace already absorbs most
   misattribution.** Sixteen small cells each carry their own ±5/bin;
   an approach total >100/bin loses the absolute grace entirely and
   is judged on pure 5%.
2. **Same-sign volume errors do not cancel — they accumulate.**
   Missed vehicles (the thrice-confirmed birth/selectivity wall) and
   phantom echoes push a whole approach one direction; summing
   movements CONCENTRATES net-volume error. Example, cam2 study_1600
   EB approach: −287 net (−17%) after all internal cancellation —
   no attribution mechanism can touch it; those vehicles were never
   counted.

## Roadmap consequence (the ranking splits by bar)

- Movement bar is attribution-limited → calibration wave (busy-window
  auto-cal → gates/paths/banks), re-attribution, label fixes.
- Approach/PRD bar is NET-VOLUME-limited → detection recall (A2
  motion-mask, A4 scale-matched 1280, queued/stopped mechanisms),
  echo suppression, and the flag-review add-missed pass (cam2's queue
  alone estimates 2,126 missed vehicles, 12.5% of window volume).
  Calibration will barely move this bar.

Any accuracy claim must state its bar. The two-level scorer mode is
the standing instrument (landing in scripts/v2_score_dev.py; interim
harness in the session scratchpad, results JSON committed).
