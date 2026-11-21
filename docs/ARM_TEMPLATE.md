# ARM TEMPLATE — one page, filled in BEFORE any scoring

Copy to `docs/plan_<slug>_<date>.md`. If a line cannot be filled, the arm is not ready to run.
The five steps are the SpaceX algorithm, in order; skipping ahead to step 4 or 5 is the failure it exists against.

## 1. Requirement — question it
- **What failure does this fix?** One measured sentence (cell, window, vehicle count), not a theory.
- **Whose words / which ruling is it?** Quote the operator or the CLAUDE.md line. No owner = candidate for deletion.
- **Physics or recommendation?** If only a recommendation, say what happens if we do nothing.
- **Does it work from raw video + calibration alone?** (Prime directive. Miovision/manual counts are yardsticks only.)

## 2. Delete — before adding
- **What existing rule, flag or code path does this make unnecessary?** List it, and delete it in the same arm
  (or say why not). An arm that only adds is presumed too big.
- **Add-back rule:** if more than 10 % of what an arm deletes has to come back, the cut was too timid; if ~0 %, say so.

## 3. Simplify — only what survived step 2
- Fewest constants. Search frozen modules before inventing one (memory: search-frozen-modules-before-new-constants).
- A fix that adds no constants cannot be called tuning.

## 4. Accelerate — cycle time
- What is the slowest stage of THIS arm's test (dump re-read, pass 1, pass 2)? Can the check use `track_fates`
  or a cached dump instead of re-running video?

## 5. Automate — last
- Only after the arm has run by hand once. Name what would be scripted, or write "nothing yet".

## Gate (declared before scoring, like G-DEF-1)
- ARMS: ...  ·  SCORE: fleet mean over all 12 windows + per-camera + per-vehicle labels (never totals alone)
- PASS: fleet rises; no camera mean falls > 1.0; no window falls > 3.0; labels none worse.
- Known before running (expected risks): ...
- Verify the scorer reads a FRESH working DB (print its mtime) — see LESSONS 2026-10-15.

## Independent review (a session that never saw the build)
Run `/review-arm <plan file>`. Ground truth first (scores, labels, audit), then spec-vs-result. A builder's
"done" is not evidence.

## Review date
Three months out. A rule or flag that never changed a result by then goes to a removal trial.
