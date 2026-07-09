# Plan — worklist flood control: batch_key rollups (2026-07-09)

The next implementation after B-VAL/B4 (docs/flagqueue_retrospective_2026-07-09.md).

## Grounding — what exists, what the measured problem is

Built and verified today: the flag queue (feeders S1/S2/S4, router, lifecycle),
the Phase-C keyboard worklist (`frontend/js/worklist.js` — one item per screen,
looping clip, 1–4/Enter/Del keys, add-missed), and **B7 is already done** —
`acceptance()` carries a `review_flags` item, `export_gate()` aggregates it
worst-wins, and `/export/download` withholds with 409 absent `?override=true`.
`batch_resolve_flags()` (DB + endpoint + worklist wiring) also exists.

The measured problem (B-VAL): **the corridor rebuild yields 3,241 open flags —
2,756 of them impact-1 `low_det_conf` — 159 per 2 camera-hours.** One-per-screen
traversal is unworkable and the queue reads as endless. Meanwhile every feeder
sets `batch_key = None`, so the existing batch machinery has nothing to grip.
This plan is that missing link: assign batch keys at the feeders, roll batches
up into single worklist cards, and re-measure the queue's effective length.

## Design

**Batch semantics (schema comment: "groups identically-resolvable flags").**
A batch is a set of flags an operator can honestly judge with ONE decision
after sampling a few members. Uncertain-EVENT flags qualify: "23 marginal
detections, NB-thru on cam3" is one judgment (real traffic in poor light vs
phantom cluster). Suspected-GAP flags do NOT batch — each is a distinct
investigation (an interval to review, a bank to rebuild); they stay singleton
cards and their small count (8 corridor-wide today) needs none.

**Batch key.** `subtype:camera_id:approach-movement` for uncertain_event flags
(e.g. `low_det_conf:3:N-through`). No time component: per-hour splitting
multiplies cards ~8× for marginal legibility gain, and the drill-in view keeps
each member's clip + interval for spot-checking. Pre-declared fallback if
practice shows a card mixing distinct conditions (e.g. dusk vs noon): add a
coarse day-part (`:am|:pm`) — a one-line key change, flags rebuild idempotently.

**Batch actions are accept/dismiss only.** `batch_resolve_flags` can also set
`movement` on every anchored event — safe for a hand-picked tight batch,
reckless across a whole-day cell batch. The rolled-up card's one-key actions
are limited to accept-all / dismiss-all; movement edits stay per-item in the
drill-in. (No backend change — the worklist card simply never sends `movement`.)

**Impact of a card = sum of member impacts**, so a 200-member impact-1 card
correctly outranks a 30-member one but still sits below a single impact-94
corridor gap. Worklist ordering becomes card-level.

## Stages (each shippable, tested)

1. **Feeder batch keys** — `feed_uncertain_events` computes `batch_key` as
   above (gap feeders keep None). Tests: key format; same-cell events share a
   key; different camera/cell/subtype do not; gap flags unkeyed.
2. **Worklist rollup cards** — group the open list by batch_key at render:
   one card shows count, summed impact, cell, first-N sample clips; `Enter` =
   accept all, `Del` = dismiss all, `→` drill into per-item flow (existing
   screens unchanged). `flags/summary` gains `open_cards` alongside `open`.
3. **Re-measure + record** — rebuild on the corridor, report flags → cards per
   intersection in the retrospective doc (acceptance target: the corridor
   worklist collapses from 3,241 items to a two-digit card count per
   intersection; T1/T2's gap cards still rank at the top). Update the
   §3-C/§4 status lines in MASTER_PLAN.

## Out of scope

S3 (blocked on counter quality), S5 wiring (§3-A), impact-model changes,
per-event confidence threshold tuning, any new feeder.
