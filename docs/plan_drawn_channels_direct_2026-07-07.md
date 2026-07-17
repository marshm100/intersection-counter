# Plan — use operator-drawn channels *directly* as attribution templates (2026-07-07)

## Goal
An operator-drawn channel's **centerline** becomes the bank path's polyline **verbatim** — as
the same quadratic Bézier the calibration UI renders — instead of being refit from claimed
tracks, dedup-dropped, or bearing-rejected. The channel **width** keeps its job: defining the
corridor that *claims* which tracks support the cell (for QA / support count / expected_speed).

Motivating evidence (cam2, 07:00–07:30 vs Miovision, replay of stored tracks):
- Auto/refit bank: **NB-left = 40** (GT 103) — the refit flattened the turn and the dedup gate
  dropped it as "coincides with NB-through."
- The **drawn NB-left curve used directly = 105** (GT 103). Curvature carries the signal; the
  builder was discarding it before accuracy was ever computed.

## Root cause (current `scripts/build_bank_gtfree.py::build_gtfree_bank`)
1. Channels are used *only* to CLAIM tracks (`_channel_claim`) into `groups[od]`.
2. Each cell's exported polyline is `_fit_mean_polyline(claimed_tracks)` — **refit, flattening the
   drawn curve.**
3. That refit then runs the bearing gate, minor-cell coherence gate, and **dedup gate** — any of
   which can drop the operator's cell (NB-left was dedup-dropped).
4. The drawn curve survives *only* as a **zero-track fallback**, and even then it's sampled
   **piecewise-linear** (`_densify([entry, apex, exit], n)`), not the UI's Bézier.

So the drawn curvature is discarded unless a cell has zero tracks — and even the fallback shape is
wrong.

## Design — operator-authoritative channel cells, auto cells fill the gaps

**Step 1 — Faithful curve sampling.** New helper mirroring the UI exactly:
```
ctrl = [2*apex - (entry+exit)/2]            # _chCtrl
quad(t) = (1-t)^2*entry + 2(1-t)t*ctrl + t^2*exit   # _chQuadAt
_channel_centerline(entry, apex, exit, n)  -> n points along that Bézier
```
Replace every channel→polyline densification (`chan_decls`, fallback, and the new direct export)
with this. The builder's template now equals what the operator drew.

**Step 2 — Channel cells export the drawn curve, always.** Restructure the admission loop:
- `channel_ods = {ch['od'] for ch in raw_chans}`.
- For each channel: emit a path with
  - `polyline = _channel_centerline(entry, apex, exit, poly_pts)`  ← the drawn curve
  - `movement_label = ch['movement']` (operator-declared; fall back to `_cardinal_movement` only if blank)
  - `supporting_count = len(claimed_group)`  (QA/telemetry; may be 0)
  - `expected_speed  = median inter-point step of claimed tracks` (if any; feeds speed-tiebreak)
  - `source = "hand-drawn-channel"`
- These paths **bypass** the bearing gate, minor-cell gate, and dedup gate (operator-authoritative).
  Their bearing residuals are still *computed* for the QA report as a **warning**, never a rejection.

**Step 3 — Auto cells fill only the gaps.** The existing data-discovered grouping / fit / gate /
dedup runs unchanged, but **skips any OD in `channel_ods`**. A channel OD is never both drawn-direct
and auto-fit. Everything for channel-free ODs stays byte-identical to today.

**Step 4 — U-turn gate (companion).** A drawn u-turn channel emits a path only if it claimed
`>= --uturn-min-support` tracks (default 3); otherwise it's held out (kept in QA as "drawn but
unsupported"). This kills the +40-car EB/NB u-turn phantoms measured in the drawn-set replay.
Flagged so it is tunable / A/B-able.

**Step 5 — Retire the redundant fallback loop.** Its job is subsumed by Step 2. Keep the
"missing legal movement" QA flag for ODs with neither a channel nor an auto cell.

No DB schema change (channels already store entry/apex/exit/width). **No `pipeline.py` change** —
attribution consumes whatever polylines the bank holds; we only change which polyline a channel
contributes.

## Design caveat — shape-matching is a global partition
A track goes to the best-fitting path in the *whole* bank. A greedy auto-fit *through* polyline can
absorb a drawn *left* (why selective-drop-in scored 13.2% while the fully-drawn set got NB-left
right). Implication: **for a drawn turn to win, its parallel through should also be a drawn (tight)
curve.** cam2 already has all 16 drawn, so its rebuild is a clean fully-drawn partition. Add a QA
hint: "movement X is a drawn channel but its parallel through is auto-fit — draw the through too."

## Validation
1. **cam2 rebuild** via patched builder (reads DB channels) → replay windowed 07:00–07:30 vs
   Miovision. Expect: NB recovered (NB-left ≈ 105, NB approach ≈ 3%), and the buffer sensitivity
   (b20 37.7% vs b4 19.7%) to **vanish** for channel cells (polyline no longer depends on claim
   width). SB stays off until its channels are redrawn — this run cleanly separates "code" error
   from "drawing-quality" error.
2. **cam3 rebuild** (no channels) → assert bank **byte-identical** to pre-change (regression guard
   for channel-free cameras).
3. **Unit tests:** `_channel_centerline` matches the UI Bézier at t=0,.5,1; a channel OD always
   yields a path carrying the drawn polyline; a channel cell is never dedup-dropped/bearing-rejected;
   the u-turn gate holds out an unsupported u-turn.

## Safety / scope
- Change lives entirely in `build_bank_gtfree.py`. Affects only **gtfree rebuilds of cameras with
  channels**: cam2 (target) and cam5 (has 16 channels).
- cam5's *current shipped* bank is `data-driven-rawtrack` (a different builder), so it is untouched
  until someone rebuilds it via gtfree — **flag cam5 for re-validation before any gtfree rebuild.**
- cam1/3/4: no channels **and** non-gtfree banks → wholly unaffected.

## Rollout
- Default-on for channel cells (the operator drew them on purpose).
- `--refit-channels` escape hatch restores old behavior for A/B.
- Ship after cam2 replay confirms NB recovery **and** cam3 byte-identity.

## Then (separate workstreams, already scoped)
- Drawing mechanics (rotatable/extendable mouths) so SB can be placed accurately — MASTER_PLAN F.
- Re-measure the full cam2 drawn set once SB is redrawn; expected to beat the live bank.
