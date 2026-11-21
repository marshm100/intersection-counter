# ARM — FLOW_ORIGIN_INFERENCE removal trial (2026-11-20)

## 1. Requirement — question it
- **Failure it fixes:** entry-less births (born past the gate) lose their origin and are dropped; it shipped 2026-08-27
  (plan_counted_path_2026-08-27.md, "B") on the pre-linker basis. Never re-measured since.
- **Owner:** the 08-27 counted-path campaign; no CLAUDE.md ship line. Candidate for deletion if it changes nothing.
- **Physics or recommendation?** Physics-based (the track's own birth point and bearing against path templates, unique
  claim only, pertinence guard). Fits the on-screen-only allowance; the open question is whether it still earns its keep.
- **Raw video + calibration alone?** Yes.

## 2. Delete
- If flag-off passes the gate: delete `_origin_flow_infer`, the flag, the `n_origin_flow_inferred` counter, and their tests
  in the same arm. If it fails: keep, and record the delta in docs/LESSONS.md as measured value.
- Add-back rule: n/a (deletion arm).

## 3. Simplify
- No new constants. Removal frees the dependency on ORIGIN_VETO_D_MAIN_PX / CHAIN_DIR_TOL_DEG in this path.

## 4. Accelerate
- Pass 2 replay over existing dumps only (no video). FLEET_WORKERS parallel. Both runs serial, never concurrent.

## 5. Automate — nothing yet.

## Gate (declared before scoring)
- ARMS: control = default (fresh run, stem fo_ctl); arm = FLOW_ORIGIN_INFERENCE=0 (stem fo_off). Same dumps.
- Compare arm to the FRESH control, not to the 91.92 in CLAUDE.md (that number predates 9.124-9.126; those deletions are
  unmeasured). The control also checks that 9.124-9.126 left the default at ~91.92.
- SCORE: fleet mean over all 12 windows + per-camera + per-window. Journey labels (eval_journeys) for the arm if the fleet
  does not decide it.
- DELETE if: fleet does not fall > 0.5; no camera mean falls > 1.0; no window falls > 3.0.
- KEEP (rule stays, trial recorded) if the fleet falls more than that.
- Known risk: cam3 0600 fires 1755 times; if it swings, it is cam3.
- Verify each scorer reads a FRESH working DB: print the mtime (LESSONS 2026-10-15).

## Independent review
`/review-arm docs/plan_flow_origin_trial_2026-11-20.md` before the deletion is committed.

## Review date
2027-02-20.

## RESULT (2026-11-21) — gate PASSED, deletion NOT yet done
- Control (default, stem foctl) vs arm (FLOW_ORIGIN_INFERENCE=0, stem fooff), same dumps, 11 windows (the fleet script's
  default list leaves out cam1 0700; the 12th window was not run). Both scored from fresh working DBs written 2026-11-20/21.
- Fleet mean movement 91.88 vs 91.88 (delta 0.00), approach 81.85 vs 81.85. Every window delta +0.00 (movement and approach).
- The flag does change events, just not the score: cam3 0600 29231 -> 29220 events (dropped 7443 -> 7997 in the arm's
  log), cam5 1600 5993 -> 5992 (dropped 1029 -> 1030). Order of 0.04% of events. The health-sidecar counts of 3-1755
  "inferences" per window were counter increments, mostly not surviving to a counted event.
- Control also shows 9.124-9.126 left the default at 91.88 (11 windows) against 91.92 (CLAUDE.md, 12 windows): no regression.
- UNPROVEN: the scorer reports one decimal against Miovision; a 0.00 delta can hide a handful of right/wrong swaps.
  Per-vehicle journey labels (scripts/eval_journeys.py) were NOT run on the arm. Run them before deleting.
- Verdict under the declared gate: DELETE. Remaining before the code removal: eval_journeys control vs arm, then
  /review-arm. Deletion = `_origin_flow_infer`, FLOW_ORIGIN_INFERENCE, n_origin_flow_inferred, the two tests that patch it
  (backend/tests/test_pipeline.py:350, :1555), and the counter in pass2_replay.py:282.

## PER-VEHICLE CHECK + DELETION (2026-11-21)
- eval_journeys foctl vs fooff: 4 of 5 clips (cam2 1600, cam3 0600, cam4 1600, cam5 0700; 419 vehicles) identical on every
  outcome, 0 discordant, McNemar p = 1.000. cam1 0700's clip has no DB in either stem: its 102 labelled vehicles are UNCHECKED.
- cam3 0600: control counts 5 more events than the arm, all 30->31 through, tracks 37864, 38038, 38376, 38548, 48152 (frames
  589751+, outside the labelled clip, so unjudged). The 7443 -> 7997 "dropped" figure is a counter, not 554 tracks.
- Code removed: _origin_flow_infer, FLOW_ORIGIN_INFERENCE (config + import + dispatch), n_origin_flow_inferred,
  the sidecar/study_health "origin_flow_inferred" field, test class TestFlowOriginInference (5 tests), and the flag
  pin in the origin-rescue test. Suite 1389 passed (1394 - 5).
- NOT DONE: confirming fleet run (needs operator go) and /review-arm in a fresh session.
