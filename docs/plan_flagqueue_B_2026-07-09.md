# Plan — Workstream B: validate + complete the blind-QA flag queue (2026-07-09)

MASTER_PLAN §4 item 3. Grounding note first: **most of B's infrastructure already
shipped** (commit d31f03c "Step B" + fixes 9e8a95f/83a4bba/5cc9bba) and this plan
builds on it, not past it. What exists and was verified today:

- `review_flags` schema — two-feeder model (kind uncertain_event|suspected_gap),
  impact, batch_key, open→accepted/dismissed/resolved lifecycle.
- Feeder 1 `feed_uncertain_events` — det-conf < 0.35 standalone, posterior
  margin < 0.20 standalone, traj-conf corroborating-only; thresholds calibrated
  on real histograms (global failure-mode floors, not per-site knobs).
- Feeder 2 `feed_suspected_gaps` — S1 `interval_corridor_gaps` (per-bin corridor
  conservation), S2 `interval_anomalies` (abrupt per-approach drop vs local
  rolling median WITH reverse-partner-held asymmetry guard). Documented limit:
  a smooth uniform sag is invisible to both (spot-count's job).
- `rebuild_flags` orchestrator (idempotent), `routers/flags.py` (rebuild,
  worklist, next-flag, batch resolve), `routers/qa.py` acceptance endpoint,
  `test_flags.py`.

What has NEVER been done is the **§1b trust step**: *"we validate that the gate
tracks this metric, then trust it blind."* And this week produced three
evidence-backed gap feeders the queue lacks. That is the plan.

---

## B-VAL — the retrospective validation (do FIRST; pure measurement)

**RAN 2026-07-09 — `docs/flagqueue_retrospective_2026-07-09.md`.** Result: 1/6
caught (T1, corridor-conservation, rank 1 — with a caveat), T7 quiet, T2–T5 are
exactly the S3/S4/S5 classes (justification now empirical), and T6 is invisible
to S2 by construction AND will be invisible to S3 (common-mode detection input)
— the detection-sag class is permanently delegated to spot-window stratification
+ §3-D, and the queue's claim is corrected accordingly. Operator-load baseline:
corridor 159 flags/2 cam-h (Feeder-1 absolute volume — a C-workstream batching
problem, not a threshold problem). S3's mini-gate below inherits the corrected,
narrower claim.

Run `rebuild_flags` over the corridor (97a7849a) and FM51 (0acb12c0), then score
the queue against every KNOWN GT-validated miss. Ground truth is the scorer of
the QA gate itself — the last legitimate GT use before a blind site.

**Target table (all documented, none tuned-for):**

| # | known miss | GT evidence | which feeder SHOULD catch it |
|---|---|---|---|
| T1 | cam2 SB-right 58% recall (uniform, all-day) | diagnosis 2026-07-06 | S3 (box-clip disagrees) — S1/S2 blind to uniform loss by design |
| T2 | cam2 EB-thru coverage hole (31 vs 4 / 30 min) | bank audit 2026-07-09 | S4 (bank hole), S3 |
| T3 | cam5 EB-right −41% (23 vs 39) | bank audit 2026-07-09 | S3; possibly S1 (conf of the surviving events) |
| T4 | cam1 NB-left merge-borderline (+38 blind) | blind-gate revalidation 2026-07-08 | S5 (gate-threshold cell) |
| T5 | cam2 NB-left −66 (37 vs 103) | live baseline | S3 |
| T6 | FM51 PM detection sag (−12–20%/interval, 16:30–18:00) | FM51 audit §2 | S2 (its design case) — check it actually fires |
| T7 | FM51 side-road +75% — FIXED via through_gate | §2 #4 | expected NOT to flag (regression guard) |

**Metrics (per project):** (a) target recall — which of T1–T6 produce an open
flag at the right camera+approach+interval; (b) rank — position of each caught
target in the impact-ordered worklist; (c) operator load — total open flags per
2 h of footage, split by subtype; (d) T7 stays quiet. No pass threshold is
invented in advance for (a): the deliverable is the MEASURED coverage map of
which known-miss CLASSES the current queue sees — including the honest "S1/S2
cannot see T1" — which is precisely what justifies B4.

Artifacts: `scripts/flagqueue_retrospective.py` (runs feeders, joins targets,
prints the table) + `docs/flagqueue_retrospective_<date>.md` with numbers.

## B4 — the three new gap feeders (one at a time, each with its own mini-gate)

Every feeder: GT-free inputs only (events, banks, box-clip replay, operator
geometry), time-based constants, global thresholds (no per-camera knobs),
emits `insert_flag(**f)` dicts per the frozen B1 contract.

**S3 — two-counter disagreement (the Gate-B mandate; highest value).**
Pass-2 box-clip replay (`scripts/boxclip_pass2.py`, frozen constants, `--bank
db`) vs the live event stream, per (approach-movement cell × 15-min interval).
Flag when the two GT-free counters diverge beyond noise: |Δ| ≥ max(6 vehicles,
25% of max(live, boxclip)) on a cell-interval — constants to be ablated in the
S3 mini-gate, then FROZEN. impact = |Δ|. evidence = both counts + window.
Mini-gate: fires on T1/T2/T5 (Gate B showed exactly these disagreements); quiet
cells on cams 3/4 (their live baselines PASS, so box-clip's own blind failures
there will fire — measure the load and set the noise floor accordingly; if cams
3/4 flood at any sane threshold, S3 demotes to per-approach granularity).
Runtime note: pass-2 replays from the pass-1 dumps in ~1 min/camera — cheap
enough to run at rebuild time; dumps exist for all 5 corridor cams.

**S4 — bank-coverage hole.** A cardinal-legal (origin,dest) cell with NO
intersection_paths row, where EITHER a drawn channel exists for the cell OR the
box-clip counter attributes ≥ 1/15-min to it. The bank builder already computes
missing-movement QA cells at build time; this feeder makes the condition live in
the queue (the builder QA never reaches review_flags). impact = box-clip's cell
count (0 if none). Mini-gate: fires on T2 (cam2 EB-thru, 31 real); stays quiet
on cam1's driveway-leg cells (zero traffic) and cam5's ~13-vehicle holes should
rank at the bottom of the worklist (impact ordering does the triage — tiny holes
are dismissable in one keystroke, exactly the audit's conclusion).

**S5 — merge-gate borderline cell.** For each turn cell with a bank
supporting_count, compare the window's raw same-cell turn-event count n against
the volume-gate threshold 1.3 × expected: flag when 0.8 ≤ n/threshold ≤ 1.2
(the band where the binary merge decision flips on noise — cam1 NB-left blind
sat at 134 vs threshold 143). impact = |n − threshold|-adjacent overcount
estimate (n − expected when n > expected, else small). Mini-gate: fires on T4;
quiet on cells far from their threshold. Note: today this condition is only
computable where the hybrid/turn-merge path runs; wire it so the same check
runs in the §3-A productized pass-2 combine.

Order: S3 → S4 → S5 (value order; S4/S5 are each ~a day, S3 carries the ablation).

**STATUS after the 2026-07-09 second pass (details in the retrospective doc):
S3 mini-gate FAILED — blocked on a second counter of comparable accuracy (blind
box-clip's own error dominates the disagreement signal; floods cams 1/3/4). S4
SHIPPED (T2 caught at rank 3; exactly the 6 audited holes fire). S5 helper
built at the combine layer (post-hoc infeasible — raw pre-merge counts don't
survive); queue wiring lands with §3-A.**

## B6 — re-run B-VAL as the combined gate

With S3–S5 landed: full retrospective again. The queue's deliverable claim
becomes: "of the 6 known GT-validated misses, the blind queue surfaces N, at
median worklist rank R, at F flags per 2 h." That sentence (with real numbers)
is what §0 calls *knowing it worked at a site where Miovision never ran*.

## B7 — export gating (§3-A tie-in, small)

`get_acceptance` exists; excel/pdf export does not consume it. Gate the export:
block (with override + logged reason) while impact-weighted open flags exceed
the acceptance bound or the spot-count CI fails. Wire into the v3 export path.

## Explicitly out of scope

- Workstream C (worklist UX, one-keystroke resolution, live CI) — next phase;
  B exposes everything it needs via the existing flags router.
- Box-clip as a COUNTER (retired by Gate B; here it is only a disagreement
  signal), any tracker/attribution mechanism work, per-camera thresholds.

## Risks / open questions

- S3 noise floor on passing cams: box-clip's blind per-cell error (15–52% net)
  may flood; the mini-gate measures this and the granularity fallback is
  pre-declared (cell → approach).
- S2's T6 check needs FM51's PM window processed in 0acb12c0 (verify the events
  exist for 16:00–18:00 before scoring; if not, that half of B-VAL runs on the
  corridor only and T6 is deferred to the next FM51 processing pass).
- Operator-load target is unset until B-VAL measures the current baseline; the
  §5 "crying wolf" question is answered empirically, not by fiat.
