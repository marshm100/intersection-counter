# PLAN — STAGE 4: CHILD-TEST UX PASSES (2026-07-29)

Parent: `plan_595_standard_2026-07-28.md` checklist Stage 4 (4.1 tally
spot-count screen, 4.2 one-question review cards, 4.3 cardinal wizard +
auto-trims, 4.4 traffic-light export language). Each pass ships against
a scripted dry-run; THE REAL GATE for all four is the 6.4 operator
rehearsal — by design, per the checklist. Each pass gets its detailed
pre-declaration here before its build.

The child test (the operator directive, verbatim intent): one clear
question, one obvious action, impossible to do wrong (guarded +
undoable), visibly verifiable.

## 4.1 — THE TALLY SPOT-COUNT SCREEN (this block)

What it replaces: propose-window → a number-input grid filled from
memory after watching the footage elsewhere → save. What it becomes:
the system serves the window WITH its footage playing on the same
screen; the operator taps big per-movement buttons as vehicles pass;
a live meter says when they have counted enough; save shows the
verdict.

**Independence rules (pre-declared, they bind the design):**
1. NO AI overlay, no system counts, no per-cell comparisons visible
   while counting — the raw stream only (the F3 range-served
   /videos/{id}/stream endpoint, no annotation layer).
2. The live meter shows VOLUME-ONLY progress against the STATIC
   certification floor (NEEDED_TOTAL_FOR_CI — a constant): "counted M
   of ~850 the statistics need". The DYNAMIC extend-to-certify number
   is a function of system-vs-manual agreement and therefore LEAKS —
   it appears only AFTER save, in the report, exactly like the §3-B
   extend-to-certify protocol ("count → save → told to extend →
   count more").
3. The post-save report may show everything (counting is committed).

**Mechanics:**
- Entry from the QA tab: the propose flow (stratified windows,
  first-uncovered-segment steering — unchanged) gains "Count it now"
  → the tally surface. The old manual grid remains as the secondary
  path ("enter a paper count") — clipboard counts are a real use-case.
- Surface: window header (video-time range, segment i of N, coverage
  strip), the playing window (seek to start, auto-pause at end),
  approach rows × movement columns of BIG buttons showing their
  running counts. Keyboard: ↑/↓ select approach row, 1–4 increment
  through/left/right/u-turn there, Z undoes the last increment
  (anywhere, any depth), Space play/pause. Every increment flashes the
  button (visible verification).
- Meter: manual total vs the static floor; "keep counting…" →
  "✓ enough volume — save when the window ends". Never red, never
  judging agreement.
- Save & compare → POST (existing endpoint; gains UPSERT-BY-WINDOW
  semantics: same camera+start+duration replaces the prior row, so the
  extend-to-certify loop re-saves one row per window instead of
  stacking rows) → the report panel (verdict, note, per-approach rows)
  + "keep counting this window" (extend loop, counts preserved) /
  "next window" / "done".
- Backend additions: needed_total_for_ci in the spot-windows response;
  the save upsert. Nothing else — the math all exists.

**GATE 4.1 (pre-declared):** scripted API dry-run green (propose →
save → report → re-save same window replaces → gate coverage
reflects); the meter payload PROVABLY leak-free (test: nothing the
tally screen renders before save contains a system count — enforced by
the response shape it consumes); full suite green. The rendered-screen
walkthrough lands in the 6.4 rehearsal (same precedent as 3.2's
screenshot — no browser automation in these sessions).

## 4.3 — CARDINAL WIZARD + AUTO-TRIMS (this block; pre-declared)

**Cardinal wizard** (the FM51 mislabeled-cardinals class = a child-test
failure: N dropdown decisions in a position-vs-bound convention).
DESIGN ADAPTATION, on the record: the checklist sketch said "against a
map thumbnail" — the app is OFFLINE BY DESIGN (no map service), so the
wizard is a rotatable COMPASS over the camera frame: the operator drags
the compass until its N needle points where the site's north lies in
this view (they know it from their own plans/maps), then one Apply
derives EVERY leg's cardinal from its origin-node bearing around the
legs' centroid (snapped 8-way) and writes through the existing legs
update path. Guard + verify: the panel immediately shows each leg's
derived position + bound label ("NE corner → SW-bound approach") for
one-glance checking; the dropdowns remain for override (the wizard is a
faster hand on the same fields, not a lock). Client-side geometry only
— no backend change.

**Auto-trims proposal** (retires the cams-3/4/5 trims nag; tightens R5
scope, star-rating night handling, spot segments, claim scope).
Blind-computable from footage metadata alone:
- covered wall-clock span(s) from the intersection's videos
  (recording_start + duration; gaps > 20 min split spans);
- proposal rule (frozen): if the coverage is SHORT (≤ ~4.5 h per
  span), propose the span(s) themselves — the study IS the recording;
  if LONG (full-day class), propose the STANDARD TMC peaks
  (07–09 / 11–13 / 16–18) clipped to coverage, plus an "everything
  (daylight)" alternative — the corridor's own declared trims are
  exactly these peaks, and the guarantee excludes night anyway.
- Child language: "Your footage covers HH:MM–HH:MM. Studies usually
  count the peaks. Accept these count windows?" — per-row accept +
  accept-all; rows land as ordinary trims rows (editable/deletable in
  the same tab afterward; accepting is UNDOABLE by deleting a row).
- Backend: GET /intersections/{iid}/trims/proposal (pure read);
  accepts reuse the EXISTING trims-create API row by row.

**GATE 4.3 (pre-declared):** scripted dry-runs — (a) proposal endpoint:
short-footage → its own span; full-day → the three peaks clipped +
daylight alternative; no videos → empty, no error; (b) wizard geometry:
a pure function (bearing + compass rotation → 8-way cardinal) unit-
tested on a synthetic 4-leg square at several rotations incl. the
diagonal snap; (c) accepting a proposal produces trims rows that the
claim-scope consumers see (queue_autoresolve.claim_windows picks them
up). Full suite green. Rendered-surface walkthrough = the 6.4
rehearsal, as with 4.1.

## 4.3 VERDICT (2026-07-29 — GATE MET; 889 tests, +12)

- **Cardinal wizard shipped**: one dial ("which way is north in this
  view?") on the calibration legs panel → live per-leg preview ("Leg 2
  → NE corner (SW-bound approach)") → Apply writes every leg's
  cardinal through the normal fields; dropdowns remain for override;
  nothing saves until the ordinary Save. The geometry is ONE
  server-side pure function (cardinals.derive_cardinals) — unit-tested
  on the square (identity + rotation), the diamond (diagonal snap),
  and a 17° dial error (snaps home). The FM51 mislabeled-cardinals
  class now takes one action instead of N convention decisions.
- **Auto-trims shipped**: GET /trims/proposal from footage metadata —
  short footage proposes its own span ("the recording IS the study");
  full-day proposes the standard TMC peaks clipped to coverage
  (partial-day clipping verified: 08:00-only footage yields an
  08–09 AM peak) with a daylight alternative; no footage answers
  calmly. Accepting = ordinary POST /trims rows (editable, deletable —
  undoable by design); the dry-run proves accepted proposals land in
  queue_autoresolve.claim_windows — the R5/claim-scope consumers see
  them immediately. The cams-3/4/5 trims declaration is now one click
  in the operator's next session.
- Rendered-surface walkthrough rides the 6.4 rehearsal (per 4.1's
  precedent). Remaining Stage-4: 4.2 one-question cards, 4.4
  traffic-light export.

## 4.2 — ONE-QUESTION CARDS (this block; pre-declared)

A LANGUAGE + GROUPING pass over the existing worklist — the actions,
keys, undo stack, batch machinery, and stopping-rule sidebar all stand
(C-polish, proven); what changes is what the operator READS and how the
answers are presented:

1. **One question headlines every card**, by subtype:
   low_det_conf "Is this a real vehicle?" · ambiguous_dest "Which way
   did it go?" · ambiguous_origin "Where did it come from?" ·
   echo_suspect "Are these separate vehicles?" · bank_coverage_hole
   "Is this movement really this small?" · merge_borderline "Fragments
   or separate vehicles?" · interval gaps "Did the system miss
   vehicles here?" The feeder's reason line stays as the small-print
   explainer beneath.
2. **The bin banner** (the 2.3 frame made visible): cards keyed
   `bin|cam|cell|HH:MM` open with "Fix this window: NB left ·
   07:15–07:30" + "up to N counts ride on this window" (the exemplar's
   cluster mass) + "the machine closed K similar items here"
   (cluster_n − live members) — child-test visibility of the Stage-2
   auto-resolution.
3. **Answers grouped by the question**: the PRIMARY answer(s) render
   as giant buttons (the existing actions behind them — Enter/Del for
   the real-vehicle question, 1–4 for the direction questions);
   secondary corrections and dismiss/skip stay small beneath. No new
   actions, no new keys — remapped presentation only, so the 6.4
   rehearsal judges language, not a new interaction model.
4. **Queue-wide machine-closed visibility**: the worklist banner gains
   one line when auto_resolved > 0 ("the machine closed N items —
   each card shows its own").

GATE 4.2 (pre-declared): pure presentation — ZERO API/behavior change
(the existing worklist tests must pass untouched); a question-mapping
unit is exercised via the existing enriched-flag fixtures if any test
renders cards (else the mapping ships as reviewed code — it is a
string table); full suite green. Rendered-surface judgment = 6.4.

## 4.2 VERDICT (2026-07-29 — GATE MET; 889 tests untouched, node
syntax-checked)

Shipped as pre-declared, presentation-only: one question headlines
every card (subtype table); the bin banner surfaces the 2.3 frame
("Fix this window: NB left · 07:15–07:30 · up to N counts ride on
this window · the machine closed K similar items here"); primary
answers render giant and match the question (Enter/Del for
is-it-real, 1–4 for which-way; echo_suspect gap cards get
duplicate-language actions); dismiss/skip/batch/undo unchanged
beneath; the worklist banner announces the queue-wide machine-closed
count with the reopen note. ZERO API or action change — the full
suite passed without touching a single test, which is the gate's
definition of presentation-only. Rendered-surface judgment = 6.4.

## 4.4 (later block; sketch, own pre-declaration when built)

- 4.4 traffic-light export screen: the acceptance items in child
  language ("what stands between you and export").

## Also recorded this block — 6.3 THE INTERIM REHEARSAL IS MEASURED

The 6.3 gate ("corridor post-review compliance with a simulated-
perfect reviewer ≥ 99%") is exactly the post-review CEILING the 5.1
inventory computes (caught failing bins → fixed to GT; uncaught stay;
compliant bins untouched — a perfect reviewer can do no more and no
less with today's queue). The measured verdict, production basis,
2026-07-29: **97.6 / 99.4 / 100.0 / 98.8 / 95.9 — PASS at cam2 and
cam3, FAIL at cam1 (−1.4), cam4 (−0.2), cam5 (−3.1)**, every residual
named (cam1 attribution over/under residuals; cam4 two uncaught
phantom bins; cam5 footage-gated undercount walls). Stage 4 does not
move this number (UX changes operator speed, not the perfect-reviewer
ceiling); qualifying footage does. 6.3 re-runs by one script
(rule595_phantom_inventory.py) whenever the queue or raw compliance
changes; the real bar remains 6.5 on procured footage.

## Sequencing + commits

1. 4.1 backend (windows payload + upsert) + tally surface + dry-run
   tests. COMMIT "Step 4.1 — tally spot-count screen".
2. 6.3 record + MASTER_PLAN stage lines. COMMIT with block close.
3. 4.2/4.3/4.4 in subsequent blocks, gated here.
