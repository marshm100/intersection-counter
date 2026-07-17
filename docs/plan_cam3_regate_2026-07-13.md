# Plan — cam3 re-gate on the botsort dump (2026-07-13)

Closes corridor hold #1 (MASTER_PLAN §2d). Context: cam3's accuracy gate
FAILED at 7.5% vs its live 3.2% because the pass-1 dump ran ByteTrack while
cam3's tuned knobs (`new_track_thresh=0.18` — a botsort-only parameter) show
its live recipe is BoT-SORT. `calib_pass1_backend` is corrected to `botsort`;
the full-day botsort re-dump is running detached (`logs/cam3_dump_botsort.log`,
resumable, watched).

## Steps (single command each once the dump lands)

1. **Harness prep (lands with this plan):** `pass2_parity.py`'s tier-1
   reference retrack hardcodes `bytetrack` — it must match the DUMP's recipe
   (read `meta["backend"]`, strip `+reid`). Without this, cam3's tier-1 would
   compare a botsort dump against a bytetrack retrack and "fail" on the
   tracker family, not mechanics.
2. **Tier-1 scoped parity** (07:00–09:00 via `--window`): |Δ| ≤ 2/cell. Extra
   value: the corridor's first tier-1 of a BOTSORT dump against a botsort
   reference (cams 1/2/4/5 all gated on bytetrack dumps).
3. **Accuracy gate via the endpoint measure-arm:** 07:00–09:00 per-approach
   MAE **≤ live 3.2% — the hard bar stands** (regressing the corridor's best
   camera is a hard stop; a marginal miss is a HOLD with the delta recorded,
   never a tune). Expectation: cam2's arm-A precedent (botsort retrack
   reproduced its live table exactly) says the botsort replay should land at
   ≈ live. 11:00/16:00 windows reported alongside for the record.
4. **Apply** (full-day window = the whole cam3 table, backup) + the automatic
   queue rebuild. Note: this replaces the 24 h table including the night
   segment §1b flags as a metric artifact — report the full-day event total
   before/after for the record.
5. **Docs:** §2d scoreboard row flips; corridor plan doc gets the outcome.

## Pre-registered risks

- The botsort full-day dump is ~2× bytetrack's cost (BoT association) — if it
  exceeds the overnight window, `--resume` continues it (boundary splits land
  in empty night hours at worst).
- cam3's dtw_mean cost-metric pin and tq filter flow through calib on both
  arms identically (verified plumbing in A2) — no action, listed for the
  record.

## Gate summary

PASS = tier-1 ≤ 2/cell AND MAE ≤ 3.2% → apply. Any FAIL = HOLD with numbers;
cam3 keeps its live table (which already passes the product bar).
