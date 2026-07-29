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

## 4.2 / 4.3 / 4.4 (later blocks; sketches, own pre-declarations when built)

- 4.2 one-question cards: the bin-keyed queue (2.3) gets the language
  pass — one question per card kind ("One vehicle or two?", "Did it
  turn left?"), giant guarded buttons, single keys, undo, the stopping
  rule visible. Rides the C-polish keyboard flow.
- 4.3 cardinal wizard ("tap where north is" against a map thumbnail;
  the FM51 mislabeled-cardinals class) + auto-trims proposal from
  footage coverage with one-click accept (also retires the cams-3/4/5
  trims nag and tightens R5 + the star rating's night scoping).
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
