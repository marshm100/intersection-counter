# A2 parity gate — results (2026-07-09)

Plan: `docs/plan_pass2_replay_A2_2026-07-09.md`. Service:
`backend/services/pass2_replay.py`; harness: `scripts/pass2_parity.py`.
Tier 1 (HARD) = retrack-from-cache vs replay-from-dump on identical inputs,
bar worst per-cell |Δ| ≤ 2 over the 07:00–09:00 window. Tier 2 = context vs
the live shipped table (recipe history, not a gate).

## What tier 1 caught before passing (the gate earning its keep)

1. **Stage-0 (pre-registered): per-camera pre-track NMS missing from the
   dumper.** cam2's un-NMS'd dump carried 12,815 track IDs; the NMS-parity
   dump carries 8,071 — **37% of its track IDs were duplicate-box artifacts.**
2. **Empty-frame schedule divergence (caught live by cam4's first run,
   NB-thru +6):** `process_cached` feeds the tracker an EMPTY update for
   every detection frame with no cache rows (Kalman/lost-buffer cadence);
   the dumper skipped those frames, so tracks never aged through gaps. Same
   class in the replay's grace-window clock. Both fixed (dumper mirrors the
   full frame schedule; replay clock ticks every frame); no constants
   touched.

## Tier-1 verdicts (final dumper, per-cell over 2 h)

| cam | worst cell abs Δ | totals (retrack vs replay) | verdict |
|---|---|---|---|
| 1 | **0** | 3,639 = 3,639 | PASS |
| 4 | 2 | 4,937 = 4,937 | PASS |
| 5 | **0** | 5,325 = 5,325 | PASS |
| 2 | **0** | 5,577 = 5,577 | PASS |

## Tier-2 context (replay vs live shipped table) — the stage-3/4 work list

- **cam1: −529 NB-thru / −279 SB-thru.** The live table is the June BoT+ReID
  hybrid product; plain balanced ByteTrack (the dump recipe) loses exactly
  the throughs ReID recovers. **Consequence: cam1's ingest pass-1 must dump
  with the ReID recipe** (its `study_0700.reid.npz` sidecar exists) — a
  stage-3 wiring decision now backed by numbers.
- **cam5: throughs EXACT (NB 2,457 = 2,457; SB 1,737 = 1,737); turn cells
  high (NB-left +264).** The live recipe's volume-gated turn MERGE collapses
  fragments; A2 replays without it by design. The production combine (blind
  bank gate + S5 emitter) is stage A4's variable, and cam5 is its cleanest
  test case.
- **cam4: +35 EB-left / +26 SB-right** — same turn-merge family, smaller.
- **cam2 (on the matched 07:00–07:30 window — its live table covers only
  30 min): worst +31 NB-thru, total 1,324 vs 1,381 (+4.3%).** Tracker-family
  drift: cam2's live table is a BoT-SORT product (the bank-audit session's
  botsort arm reproduced it exactly); the dump recipe is live-default
  ByteTrack. Stage 3 must carry a per-camera pass-1 recipe (cam1 ReID, cam2
  botsort-or-revisit, cams 3/4/5 default) — the dump meta already records it.

## Verdict

**TIER 1 PASSES ON ALL FOUR CAMERAS — three at PERFECT per-cell parity
(|Δ| = 0) and cam4 at the bar (|Δ| = 2).** The pass-2 replay path
(dump → `_process_vehicle` → `_finalize_vehicle_data` → real event writer)
is a faithful stand-in for retrack-from-cache: identical inputs produce
identical counts. The two divergences the gate caught (pre-track NMS, the
empty-frame schedule) were both DUMPER-side and both fixed mechanically —
zero constants changed anywhere.

Cleared for stage 3 (ingest wiring + "Confirm & process" re-point), with the
tier-2 work list as stage-3/4 requirements: per-camera pass-1 recipe
selection, and the production turn-merge as A4's own gated change. cam3
joins the gate when its full-day v2 dump lands (overnight job).
