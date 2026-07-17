# cam2 full-day two-pass exercise + B6 (2026-07-10)

The first real exercise of the two-pass product flow (plan_A4_stage3 stage 4):
cam2's three study windows dumped (BoT-SORT per `calib_pass1_backend`, NMS
0.85), pass-2 per window (corpus expecteds, applied-bank attribution, A4a
merge), measured, applied window-scoped with backups, flag queue rebuilt with
S5 rows by the product path. cam2's live table goes from 30 minutes of events
to the full study day (16,648 events).

## The apply gate (07:00–07:30, the only window with a live baseline)

Pass-2 **beats the live baseline: 8.1% per-approach MAE vs 9.8%**, same
watch-cell signature, and the merge fixed the two overcounts the live table
carried (SB-right +31 → −2, EB-left +11 → +2). Applied.

## Honesty: the windows with NO baseline

07:00–09:00 full window 16.6% MAE, 11:00 13.7%, 16:00 12.2% — the second
hours degrade (worst: EB 76.9% @08:15). Decomposed: NOT a merge artifact —
all undercounts, in the documented cam2 cells (NB-left −127/hr2, EB-thru,
SB-right recall dip at peak volume). This is what the blind flow honestly
produces on the corridor's hardest camera; the queue's job is to flag it.

## Day-long cell truth (6 h vs Miovision, dev yardstick)

| cell | old recipe | two-pass | read |
|---|---|---|---|
| SB-right | **0.58** (−461, the #1 deficit) | **1.07** | FIXED — BoT+merge recovered it |
| SB-thru | 0.95 | 0.85 | worse (−712) — partial trade with SB-right |
| EB approach total | +696 over | **+37** | massively better at approach level |
| EB-thru / EB-right split | 1.42 / 1.31 (both over) | 0.24 / 1.50 | the collinear split still broken; thru starves into right |
| NB-left | ~0.36 | 0.32 | unchanged — the known attribution wall |
| NET (6 h) | +1.5% (cancellation-flattered) | −8.8% (honest undercount) | cancellation reduced; errors now visible |

## B6 — the queue as the product left it

- **T2 CAUGHT at rank 1, impact 179** — the S4 bank-hole flag now carries the
  full day's fallback events for the EB-thru cell. The queue's top card is
  the top actionable defect. **Follow-up unlocked: the held bank-D apply
  (add the drawn EB-thru path) should be RE-TESTED under the two-pass recipe
  — its July-9 objection (cancellation vs EB-right's overcount) changed shape
  now that the merge is live.**
- **S5 is live in production** (a merge_borderline flag in the queue from the
  apply path). T4 proper still needs cam1's pass-2 run.
- **T1 dissolved rather than caught:** yesterday's rank-1 corridor flags are
  gone because the pass-2 counts CONSERVE — and the underlying mechanism
  (SB-right 58% recall) is genuinely fixed (1.07). The S1 feeder went quiet
  for the right reason. The residual SB-thru −15% did NOT trip the corridor
  threshold — noted as S1 sensitivity material for workstream-B tuning.
- T3/T5 unchanged (blocked on a second counter); T7 quiet.
- Load: intersection-2 queue = 891 flags / 24 cards (workable card count).

## Also landed

- cam3's full-day v2 dump completed (1.07M points, 47,620 tracks) — pass-1
  corpus complete on all 5 cameras. Parity check deferred to a scoped window.
- Window-scoped apply + per-variant working DBs (multi-trim study days work).
- `--resume` recipe validation (caught the bytetrack/botsort mislabel live).

## Known inefficiency (fix queued)

`run_pass2(apply=True)` recomputes the whole pass-2 instead of reusing the
measured working DB — correctness-safe, ~2× wall time. Fix: apply from the
existing working DB when its inputs (dump meta + bank) are unchanged.
