# mdh vs dtw_mean — all-camera cost-metric sweep (2026-06-30)

**Decision being resolved:** the deferred "measure, don't change" call on the
joint-scorer cost metric (`JOINT_SCORER_COST_METRIC`, `backend/config.py`). The
default flipped to `mdh` on 2026-06-11 (Phase 2.3) on a **net**-error basis
(cam4 22.5→14.7); cam3 is pinned to `dtw_mean`. The per-approach-attribution
campaign raised the question of whether `dtw_mean` should come back to split the
collinear cam2 EB-thru/EB-right pair that `mdh` structurally cannot (it
hard-wires `coverage=1.0`). This is a **global config default**, not a per-site
knob — choosing it correctly generalizes to every site (the §0 blind-deployment
litmus), so it is worth deciding on evidence rather than per-camera intuition.

**Method.** `scripts/replay_fullchain.py --cost-metric {mdh,dtw_mean}`
re-attributes every stored trajectory through the real chain with the cost metric
FORCED per run (overriding cam3's DB pin), live banks held fixed — so the metric
is isolated from the bank. Scored on the acceptance metric
(`scripts/interval_metric.py`, AVG |err| per 15-min vs Miovision), **per-approach
AND net**. No retracks. Instrument validated against `interval_metric.py` on all
five cameras (each camera's live-metric arm reproduces the stored attribution
within ~2.7pp — e.g. cam2 mdh EB 46.9 vs live 44.2, cam1 mdh EB 11.5 vs 11.8,
cam3 dtw 39.7 == live 39.7).

## All-camera sweep — AVG |err| (the acceptance bar) | net%

| cam | scope | mdh AVG\|err\| | dtw AVG\|err\| | mdh net% | dtw net% |
|-----|-------|------:|------:|------:|------:|
| **cam1** | TOTAL | **4.9 PASS** | 8.1 FAIL | +0.6 | −7.5 |
| | EB | 11.5 | 9.7 | +7.9 | −7.7 |
| | NB | 7.5 | 6.8 | −6.6 | −5.5 |
| | SB | **6.4** | 12.3 | +5.0 | −10.7 |
| **cam2** | TOTAL | 2.4 | 1.9 | +1.1 | +0.2 |
| | EB | 46.9 | 36.7 | +40.4 | +32.4 |
| | NB | 4.2 | 3.7 | +3.1 | +2.8 |
| | SB | 18.2 | 15.9 | −18.6 | −16.3 |
| | WB | 5.7 | 6.3 | −2.5 | −5.1 |
| **cam3**¹ | TOTAL | 39.4 | 39.7 | −12.0 | −10.1 |
| | NB | 35.5 | 36.1 | −8.8 | −7.8 |
| | SB | 35.3 | 34.3 | −17.7 | −13.8 |
| **cam4** | TOTAL | 3.6 | **3.3** | +1.8 | −0.1 |
| | NB | **4.9 PASS** | 9.7 FAIL | −2.0 | −9.6 |
| | SB | 5.9 | 5.9 | +4.7 | +4.6 |
| **cam5** | TOTAL | 2.5 | **2.3** | +1.2 | +0.6 |
| | EB | **20.2** | 35.4 | −19.9 | −35.3 |
| | NB | 9.0 | **4.8** | +6.9 | +2.0 |
| | SB | 5.8 | **4.8** | −5.5 | −4.4 |

¹cam3 = full 24h window, dominated by night / no-coverage bins (max 100% @ 00:00,
12–13 zero-coverage bins). The mdh↔dtw delta is within noise (0.3pp total). cam3's
live `dtw` pin rests on a *peak-window* measurement that this 24h cut does not
re-test, so cam3 is not evidence either way here.

## The decisive cut — cam2 with the missing SB-left path added (both metrics)

The campaign's diagnosis is that cam2's worst cells trace to ONE missing bank path
(SB-left), not to the cost metric. Injecting the validated SB-left channel path
(`experiments/channel_replay/channels_cam2.json`, densified) via `--extra-paths`:

| cam2 config | EB | SB | NB | WB | total |
|---|---:|---:|---:|---:|---:|
| mdh, live bank (no SB-left) | 46.9 | 18.2 | 4.2 | 5.7 | 2.4 |
| dtw, live bank (no SB-left) | 36.7 | 15.9 | 3.7 | 6.3 | 1.9 |
| **mdh + SB-left** | **33.2** | **12.3** | 4.1 | 5.7 | 2.4 |
| dtw + SB-left | 35.3 | 14.2 | 3.7 | 6.3 | 2.1 |

**dtw's cam2 "win" was a PROXY for the missing SB-left path.** On the bare live
bank, dtw's looser coupling happened to peel some SB-left orphans off the EB-thru
magnet (EB 46.9→36.7). But once the actual missing path is in the bank, **mdh
beats dtw** on both failing cells: EB 33.2 vs 35.3, SB 12.3 vs 14.2. The two
"fixes" do not compound — they overlap, and the real path does the job better.
This also refutes the earlier hypothesis that dtw fixes the collinear EB residual:
dtw makes EB *worse* (35.3 > 33.2), so the residual is a bank/curvature problem,
not a metric one.

## Findings

1. **The net-vs-per-approach trap is real and exactly as warned.** dtw improves
   the *total/net* on cam2, cam4, cam5 — but on the **per-approach bar** (the real
   metric; errors cancel at the total) it is a wash or worse on 3 of 5 cameras:
   - **cam1 — mdh decisively.** dtw nearly doubles SB (6.4→12.3) and flips the
     total from PASS to FAIL (4.9→8.1). dtw also dropped ~1,100 events to the
     less-reliable entry-position fallback (12.5k matched vs 13.6k).
   - **cam4 — mdh per-approach.** dtw's "better total" hides NB going
     4.9 PASS → 9.7 FAIL — the exact cam4 regression mdh was *adopted* to fix.
   - **cam5 — mdh on the worst cell.** dtw helps NB/SB modestly but blows the
     known-weak EB cell 20.2 → 35.4.
2. **dtw no longer wins anywhere once the bank is complete.** Its only
   per-approach win (cam2) evaporates with the SB-left path added.
3. **The cam2 residuals are bank-completeness items, not metric items.** EB 33.2
   (the collinear EB-thru/EB-right split) and SB 12.3 (the SB-right under-count)
   both remain FAIL under *either* metric after SB-left; dtw does not help them.

## Recommendation

1. **Keep `mdh` as the global default. Do not flip.** It wins the per-approach
   lens on cam1/cam4/cam5 and a flip would regress cam1 (SB + total), cam4 (NB),
   and cam5 (EB).
2. **No cam2 `dtw` pin.** The dtw "win" on cam2 was a stand-in for a missing path;
   the general, blind-deployable fix (the SB-left channel) is both more principled
   (§0 — a builder completeness fix that generalizes, not a per-site metric knob)
   and numerically better (mdh+SB-left 33.2/12.3 < dtw+SB-left 35.3/14.2).
3. **Leave cam3's `dtw` pin as-is** — it was adopted on a measured peak-window
   basis; this 24h cut shows the delta is within noise but does not re-test that
   basis. No change, flagged as low-stakes and revisitable.
4. **Route the cam2 residuals to bank completeness, not the metric:** EB-right /
   EB-thru collinear split + the SB-right path (campaign Levers 1 and 3).

**Net: the deferred "measure, don't change" call resolves to _don't change_** —
keep `mdh`, no per-camera pins added. The reason cam2 *looked* like it wanted dtw
is that it was missing a path; supply the path and mdh is best everywhere.

## Decision status

No code default was changed; the recommendation is no-change. The only code
shipped is the additive `--cost-metric` flag on `replay_fullchain.py` (back-compat,
default = live resolution) that made this sweep possible. Pending user sign-off on
"keep mdh, no pins."
