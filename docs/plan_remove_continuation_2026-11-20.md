# Remove the predicted-continuation rule (CONTINUATION_DEDUP) — 2026-11-20

First arm run through docs/ARM_TEMPLATE.md.

## 1. Requirement
- **Failure fixed:** none. The rule (arm pc1, 2026-09-25) was written for cam4 SB over-count from partial tracks.
- **Whose ruling:** nobody's. config.py said "Default OFF pending the arm and a ruling"; no ruling is recorded
  in CLAUDE.md or the plan docs. No owner = delete.
- **Physics or recommendation:** recommendation. If we do nothing, 115 lines of dead code, 153 lines of tests and a
  research script stay and get read in every future audit.
- **Raw video + calibration alone:** n/a (nothing runs).

## 2. Delete
Removed: CONTINUATION_DEDUP flag block (config.py), continuation_pass and its gate (two_pass.py),
continuation_pairs and continuation_dedup (turn_merge.py, 116 lines), backend/tests/test_continuation_dedup.py,
scripts/research_continuation.py (imported the removed function). Stale "continuation" mentions in two comments fixed.
Add-back risk: ~0. Default OFF, never shipped, so no production count changes.

## 3. Simplify
No constants added; none removed beyond the flag (the rule reused existing frozen constants, which stay).

## 4. Accelerate / 5. Automate
Nothing. No fleet run needed: behaviour on every default path is unchanged by construction (the rule never ran).

## Gate
Full backend suite green (1422 passed). No fleet score claimed or needed.

## Not decided here (needs an operator ruling)
Fracture dedup, bound-chain guard and turn merge are skipped when the linker runs (TRACKLET_LINKER_EXCLUSIVE),
but they still run if the linker fails (fail-safe fallback), under TRACKLET_LINKER_EXCLUSIVE=0 (arm lk0) and
TRACKLET_LINKER=0 (the honest 80.81 control). Question: on linker failure, fall back to the old rules, or flag
the run for re-run? Also unchecked: whether the linker has ever failed on a real run (stats["linker"], track_fates).

## Review date
2027-02-20.
