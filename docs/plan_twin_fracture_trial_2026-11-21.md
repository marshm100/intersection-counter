# ARM — COEXISTING_TWIN_DEDUP + STOP_FRACTURE_COLLAPSE removal trial (2026-11-21)

DRAFT. Nothing has been run. No fleet is started until the operator says go.

## FINDING THAT CHANGES THE PLAN (read first)
The two flags act at different stages, so "both off together on existing dumps" is not possible:
- COEXISTING_TWIN_DEDUP acts in pass 2 (two_pass.py:1960, `twin_track_dedup` on the replay DB). A fleet over existing
  dumps with the flag off is a clean removal trial. Cheap.
- STOP_FRACTURE_COLLAPSE acts in PASS 1 (two_pass.py:1343): `_collapse_stop_fractures` re-stamps twin B's rows to track A's
  tid IN PLACE in the dump. Every current study_* dump already carries the collapse. Setting the env var in a fleet over
  existing dumps changes nothing and would report a false "identical". An off arm needs pass 1 re-run with the flag off
  (new dumps, from the cached detections if the retrack path supports it; if it needs video, it is slow).
- Size of the effect, from study_health sidecars (pairs collapsed per window): cam1 0700/1600 6/5; cam2 0700/1100/1600
  10/14/27; cam3 0600 74; cam4 0700/1100/1600 3/1/3; cam5 0700/1100/1600 5/4/11. 163 pairs over 12 windows, against
  ~5000 events per window. Whatever it does is small and concentrated in cam3 0600 and cam2 1600.
- So: split into arm T (twin dedup, pass 2) and arm F (stop-fracture, pass 1).

## 1. Requirement — question it
- **Failure each fixes:** both shipped 2026-08-27 (docs/plan_counted_path_2026-08-27.md, C and C2) on the pre-linker basis, for
  the red-light dup engine (track lost at a stop, twin births at the rest position, both counted) and for coexisting twin
  tracks on one vehicle (operator scenes 1-3). Not re-measured since the tracklet linker (2026-09-30) and the tracker work
  (held-box guard, twin retire) landed.
- **Owner:** the 08-27 counted-path campaign. No CLAUDE.md ship line. No owner in the current rulings = candidate to delete.
- **Physics or recommendation?** Physics (overlapping spans, box IoU, rest-position pinning). The open question is whether the
  linker and tracker now cover the cause. Removal inventory (2026-11-20) calls both post-hoc count patches; the memory
  "fix tracking inside the box, not count patches" applies.
- **Raw video + calibration alone?** Yes.

## 2. Delete
- If an arm passes: delete its flag, function and tests in the same arm.
  T: `twin_track_dedup` (turn_merge.py), COEXISTING_TWIN_DEDUP, TWIN_OVERLAP_FRAC, TWIN_IOU_MIN if nothing else reads them,
  the stats["twin_dedup"] sidecar entry. F: `_collapse_stop_fractures`, STOP_FRACTURE_COLLAPSE, stop_fracture_pairs.json,
  the meta/study_health `stop_fracture_collapsed` field, the pass-1 reuse-key part, STITCH_STAT_* if unused afterwards.
- If an arm fails: keep the rule, write the measured delta in docs/LESSONS.md.
- Add-back rule: n/a (deletion arm).

## 3. Simplify
- No new constants. Removal frees constants named above (verify by grep before claiming it).

## 4. Accelerate
- Arm T: pass 2 only, existing dumps, FLEET_WORKERS=4, about 40 min with warm linker dumps.
- Arm F: slowest stage is the pass-1 re-track of 11 windows. Before paying for it, check whether the pairs list and the
  `track_fates` ledger can predict where the arm would differ: the 163 collapsed pairs are the only rows that can change.
  Re-track only cam3 0600 (74 pairs) and cam2 1600 (27) first; if those two are identical per vehicle, the rest cannot move much.
- Run T first, F second. Never two fleets at once.

## 5. Automate — nothing yet.

## Gate (declared before scoring)
- ARMS: control = the fodg fleet already on disk (default, 91.88, 11 windows, byte-identical to fodel).
  T: COEXISTING_TWIN_DEDUP=0, pass 2 over existing dumps, stem tw0.
  F: STOP_FRACTURE_COLLAPSE=0 at pass 1 (new dumps under a separate name, never over study_*), then pass 2, stem sf0.
  Control for F must be the SAME re-track with the flag on, or the re-track itself (not the flag) is what gets measured.
  If the re-track with the flag on does not reproduce fodg, stop: the pass-1 path is not deterministic and arm F is not
  judgeable by fleet score at all.
- SCORE: fleet mean over the 11 default windows + per camera + per window, then `eval_journeys` control vs arm on the five
  labelled clips (a 0.00 fleet delta hides right/wrong swaps; see the flow-origin trial). cam1 0700 is outside the default
  list: say so in the result and do not claim it.
- DELETE if: fleet does not fall > 0.5; no camera mean falls > 1.0; no window falls > 3.0; journey labels none worse,
  McNemar not significantly against the arm.
- KEEP if the fleet or labels fall past that, or if the dedup fixes a named double (operator scenes 1-3) that the arm loses.
- Known risks: cam3 0600 (74 pairs, 29220 events) and cam2 1600 (27 pairs, 78.0, the weakest window) carry most of the signal.
  Arm T can re-expose operator scenes 1-3 doubles; check those vehicles by track id if the labels do not cover them.
- Verify each scorer reads a FRESH working DB: print the mtime (LESSONS 2026-10-15).

## Independent review
`/review-arm docs/plan_twin_fracture_trial_2026-11-21.md` in a fresh session before any deletion is committed.

## Review date
2027-02-21.

## STATUS (2026-11-21)
- Arm T STARTED (operator go): COEXISTING_TWIN_DEDUP=0, stem tw0, FLEET_WORKERS=4, log runs/v2_week1/tw0_fleet.log (last line
  "exit N" when done). Confirmed off: the flag is absent from the run's "flags ON" line.
- Arm F re-track cost (read-only look): the pass-1 re-track runs from the cached detection parquet, NO video
  (scripts/retrack_default_tracker.py PROJ CAM VARIANT PREFIX aliases the cache and calls run_pass1). Past logs: cam4 1100 120 s
  (228k rows); cam3 0600 and cam2 windows 700-3400 s. Whole fleet is roughly 2 h serial. Needs a new prefix and a way to pass
  STOP_FRACTURE_COLLAPSE=0 (env var works: it is read at import). Not started: waits for arm T, so the two do not compete for the GPU.
  Still to check before running: that a flag-ON re-track reproduces the fodg dump (determinism).

## RESULT arm T (2026-11-21) - gate FAILED, COEXISTING_TWIN_DEDUP STAYS
- tw0 (COEXISTING_TWIN_DEDUP=0, pass 2 over existing dumps, 11 windows, fresh score files 03:14-03:33) vs fodg: fleet 91.88 -> 90.17 (-1.71).
- Per window: cam1 1600 -1.2; cam2 0700 -3.0, 1100 -2.0, 1600 -0.9; cam3 0600 -2.1; cam4 0700 -4.6, 1100 -2.1, 1600 -3.8;
  cam5 0700 +1.9, 1100 -1.0, 1600 0.0. Camera means: cam2 -2.0, cam3 -2.1, cam4 -3.5. Declared bars: fleet not > 0.5 down, camera not
  > 1.0 down, window not > 3.0 down. Three bars missed (fleet, cam2/cam3/cam4 means, cam4 0700 and 1600 windows).
- The rule is not dead weight and is not made unnecessary by the linker: it removes real doubles. cam4 (far-field, weakest-tracked
  windows) leans on it most.
- "events=" in the fleet line is identical in both arms (the dedup is write-then-reject, so rejected events are still written); do not read
  event counts as a difference test for this flag. Score files are the evidence.
- eval_journeys NOT run on arm T: the fleet gate already decides KEEP; labels would only spend operator-labelled clips.
- Unproven: why cam5 0700 gains +1.9 with it off (a wrongly rejected real second car there is the likely reading; not checked).
  Worth one look at the rejected pairs on cam5 0700 if the dedup is ever tuned, not now.
