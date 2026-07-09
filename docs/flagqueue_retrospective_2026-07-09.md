# B-VAL — flag-queue retrospective, first pass (2026-07-09)

The §1b trust step (docs/plan_flagqueue_B_2026-07-09.md): rebuild the blind flag
queue on the corridor (97a7849a) + FM51 (0acb12c0), score it against the known
GT-validated misses. Harness: `scripts/flagqueue_retrospective.py` (CAUGHT
requires a suspected_gap flag — a lone low-confidence event in the right cell is
ANECDOTAL, not detection). DBs backed up first
(`backups/20260709_pre_flag_retrospective.db`).

## Queue volume (operator-load baseline)

| project | open flags | camera-hours | flags / 2 cam-h | by subtype |
|---|---|---|---|---|
| corridor | 3,241 | 40.8 | **159** | low_det_conf 2,756 · ambiguous_dest 483 · interval_corridor 2 |
| FM51 | 30 | 4.0 | 15 | low_det_conf 23 · ambiguous_dest 7 |

Feeder-1 fires on ~3.7% of events — per its calibration — but at corridor volume
that is 159 items/2h: **flood territory without batch_key grouping and the C
worklist**. Impact ordering does its job: the two gap flags rank 1–2 on their
intersection, far above the impact-1 event flags.

## Target coverage map

| tgt | verdict | best flag | known miss |
|---|---|---|---|
| T1 cam2 SB day-long recall | **CAUGHT** | interval_corridor, rank 1/55, impact 94 | see caveat |
| T2 cam2 EB-thru bank hole | ANECDOTAL | ambiguous_dest, impact 1 | needs **S4** |
| T3 cam5 EB-right −41% | ANECDOTAL | low_det_conf, impact 1 | needs **S3** |
| T4 cam1 NB-left merge-borderline | ANECDOTAL | low_det_conf, rank 299 | needs **S5** |
| T5 cam2 NB-left −66 | ANECDOTAL | low_det_conf, impact 1 | needs **S3** |
| T6 FM51 PM sag −12–20%/interval | ANECDOTAL | low_det_conf, impact 1 | **no planned feeder covers it — see below** |
| T7 FM51 side-road (fixed) | **QUIET** ✓ | — | regression guard holds |

**T1 caveat (honest read):** the rank-1 flag is a genuine SB conservation
violation on the right camera, bound, and window (link 1↔2 Sbound short 94 in the
07:15 bin, whole-window gap 26%) — but cam2's live DB holds only 30 min of
events, and within that window the SB-right CELL is +31 over, so the flag
captures a real S-bound inconsistency adjacent to T1, not the day-long recall
mechanism itself. Re-verify after cam2's full-day reprocess (S1 should then fire
on the −461 all-day deficit directly).

## Findings

1. **Current gap-feeder recall on known misses: 1 of 6.** T2–T5 are exactly the
   classes the planned S3/S4/S5 feeders target — the plan's justification is now
   empirical, not speculative.
2. **T6 is invisible to S2 BY CONSTRUCTION and will be invisible to S3 too.**
   S2 triggers at a ≥60% dropout vs a ±2-bin rolling median (ANOM_DROP_FRAC
   0.60); the FM51 PM miss is a 12–20% GRADUAL sag the rolling baseline follows
   down. And S3 (two-counter disagreement) shares the same detection input as
   the live counter — a common-mode detection loss moves both counts together,
   producing NO disagreement. **The flag queue cannot cover the detection-sag
   class; its §3-B coverage is the spot-window stratification (shipped,
   9e8a95f — forces spot counts into each trim segment incl. the PM) + the
   §3-D low-light detector work.** Recorded as a permanent, documented limit —
   the queue's claim must never imply it catches this class.
3. **Operator-load flood** is Feeder-1's absolute volume at corridor scale, not
   its rate. Levers (in C workstream, not thresholds-by-fiat): batch_key
   grouping, per-cell rollups of impact-1 event flags, and the stopping rule.
   The gap flags already outrank the noise.
4. T7 guard: quiet. The fixed through_gate bug does not re-flag.

## Consequence for the plan (order unchanged, claims corrected)

- S3's claim narrows to DOWNSTREAM divergence (tracking/attribution/bank) —
  which is T3/T5 (+T2 corroboration). It cannot cover detection-common-mode.
- S4 covers T2; S5 covers T4. After S3–S5 land, the expected map is 5/6 caught
  + T6 explicitly delegated to spot-count stratification. B6 re-runs this
  harness to verify.
