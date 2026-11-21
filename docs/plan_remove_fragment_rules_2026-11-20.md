# Remove fracture dedup, bound-chain guard and turn merge — 2026-11-20 (DRAFT, awaiting operator ruling)

Second arm through docs/ARM_TEMPLATE.md. Nothing is deleted and no fleet is run until the ruling below.

## Evidence gathered (read-only)
- **Has the linker ever failed on a real run? No evidence of it, but the record is thin.**
  - No "tracklet linker failed" line in any log under the repo (runs/, docs/, logs).
  - All 106 linked dumps (`lk*_*.tracks`) carry `meta["linker"]`.
  - Every arm working DB written since the linker shipped (2026-09-30, ~700 DBs across 35 arm prefixes) has
    `track_fates` rows with reason `linked_into`, so the linker ran in all of them.
  - Unproven: server logs are only partly kept, and production project DBs hold no `track_fates` rows (the fates
    live in the arm DBs). A failure on a non-arm run would leave nothing to find. `stats["linker"]` is not
    persisted anywhere queryable.
  - Also noted: 28 `*_cam2_vl3_l1_*` DBs share identical row counts (1869 / 2258). They predate the linker by
    mtime, so they are not failures; they only look like one stale file copied across arms.
- **Who depends on the old path:**
  - Code: `two_pass.py` runs fracture (l.2027), bound-chain (l.2039) and the turn merge (l.2046) only when
    `_lk_replaces` is false, i.e. linker failed, `TRACKLET_LINKER=0`, or `TRACKLET_LINKER_EXCLUSIVE=0`.
  - Arms: lk0 (EXCLUSIVE=0) and the honest control 80.81 (TRACKLET_LINKER=0). Both are history; no shipped
    default needs them. After deletion neither is reproducible, so the 80.81 control is frozen as a number only.
  - Tests: test_fracture_dedup.py (137 lines), test_bound_chain_conserve.py (226), test_turn_merge.py (315);
    `turn_merge.py` is 631 lines but `twin_track_dedup` and `merge_replay_turns` internals are shared (see Delete).
  - `scripts/reprocess_default.py` lists the flag names (lines 33-35) so they are forwarded as env.

## 1. Requirement
- **Failure fixed:** none. These rules are the pre-linker answer to one vehicle broken into pieces. The linker
  replaced them on the linked path (CLAUDE.md, 2026-09-30, "it replaces the fracture rule, the bound-chain
  guard, the continuation rule and the turn merge on the linked path"). The only live use is the failure fallback.
- **Whose ruling:** the linker go (2026-09-30) made them redundant; deleting them is a recommendation, not a ruling.
- **Physics or recommendation:** recommendation. If we do nothing, ~1300 lines of code and tests stay, three
  flags (FRACTURE_DEDUP, BOUND_CHAIN_CONSERVE, TURN_MERGE) stay in the fingerprint, and a silent fallback path
  that nobody has ever seen run stays as well.
- **Raw video + calibration alone:** unchanged (nothing new reads ground truth).

## 2. Delete (proposed, not done)
`fracture_pass`, `bound_chain_pass` (two_pass.py); `fracture_pairs`, `fracture_track_dedup`, `bound_chain_recs`,
`bound_chain_pairs`, `_all_partials_pairs`, `bound_chain_dedup`, and the turn-merge call in turn_merge.py;
flags FRACTURE_DEDUP, BOUND_CHAIN_CONSERVE, TURN_MERGE, TRACKLET_LINKER_EXCLUSIVE (exclusivity becomes
unconditional); the three test files. To check before cutting: `borderline_merge_cells` / `s5_flags` (S5 flags
are "unchanged" under TURN_MERGE=0, so they likely stay), and `twin_track_dedup`, which runs regardless and stays.
Add-back risk: ~0 on the default path by construction (all three are skipped there). Fallback path: depends on
the ruling.

## 3. Simplify / 4. Accelerate / 5. Automate
- Simplify: removes four flags, adds none. `_lk_replaces` collapses to "linker ran".
- Accelerate: no fleet needed if the ruling is "flag the run". If the fallback is kept, nothing is deleted.
- Automate: persist `stats["linker"]` (or a `linker_ok` bit) with the run so the next "has it ever failed" is a query.

## DECISION NEEDED: linker-failure fallback
- **A. Keep the old rules as the fallback.** Safest for count quality when the linker breaks. But then nothing here
  is deleted, and the fallback has never been exercised. It reproduces roughly the 80.81 path, ~11 fleet points
  below the default, and the result looks normal.
- **B. Flag the run for re-run (recommended).** On linker failure, finish processing (the "never stop" rule),
  record `linker_failed` on the run, show it in the UI and keep it off the Excel until re-run. Deletes all three
  rules. The cost: a failed run yields no usable counts until fixed, instead of a plausible but worse count.
  Why I prefer it: a silent 11-point drop is worse for an engineer than a visible failure, and no failure has
  been observed in ~700 runs.
- B needs one new piece (the failure flag and its UI/Excel handling). Without it, deleting leaves failures
  silent and unrounded.

## Gate (declared before scoring)
- Ruling B: no fleet needed for the deletion (default path unchanged by construction). Gate = full backend suite
  green with the three test files removed, plus one forced-failure test (linker raises -> run flagged).
- Ruling A: no change; close this plan.
- If the operator wants a fleet anyway: single arm, default vs. deleted, all 12 windows, vs 91.92; PASS = identical
  counts. Verify the scorer reads a FRESH working DB (print its mtime), per LESSONS 2026-10-15.

## Independent review
`/review-arm docs/plan_remove_fragment_rules_2026-11-20.md` in a fresh session after the build.

## Review date
2027-02-20.

## RULED AND BUILT (2026-11-20): option B
Operator ruling: on linker failure, flag the run for re-run (not fall back).
Deleted: fracture_pass / bound_chain_pass, fracture_pairs, fracture_track_dedup, bound_chain_recs / pairs / dedup,
_all_partials_pairs, the turn-merge application in merge_replay_turns (S5 borderline signal kept; merged_away is
now always 0), flags FRACTURE_DEDUP (+GAP_S, DIST_BOXES), BOUND_CHAIN_CONSERVE, CHAIN_GUARD_ALL_PARTIALS,
TURN_MERGE, QUEUE_AWARE_MERGE, MERGE_EXCESS_ONLY, TRACKLET_LINKER_EXCLUSIVE; test_fracture_dedup.py,
test_bound_chain_conserve.py; scripts diag_fracture_pairs, research_chain_partials, research_merge_pairs.
Added: flag_linker_failed() and `_lk_failed` in run_pass2 - a linker error sets result["linker_failed"],
applied=False, removes the stats sidecar, skips the sidecar-reuse branch, and returns before the apply gate.
Gate: full suite 1398 passed (1422 before: minus ~28 deleted tests, plus 2 new); the reuse-guard test fails when
the guard is removed. No fleet run (default path unchanged by construction).
Kept on purpose: merge_turn_fragments + borderline_merge_cells (scripts/hybrid_ocbot, apply_hybrid and the S5
"merge_borderline" flags still use them). The S5 flag now describes a merge that no longer happens: follow-up.
Not done: no UI display of linker_failed beyond the result dict and the ERROR log line; no persisted linker stat.
