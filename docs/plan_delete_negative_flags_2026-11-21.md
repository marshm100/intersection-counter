# ARM — delete the default-OFF flags with a written negative (2026-11-21)

## 1. Requirement — question it
- **Failure it fixes:** none; it removes code. Seven switches default OFF with a recorded negative and no caller path in
  the shipped default (docs/removal_trials_inventory_2026-11-20.md, group C).
- **Owners/rulings:** V2_TIMELOCAL ("LEDGERED-DEAD 2026-08-06"), A3_CUT_DUMPS (Demo-1 negative 2026-08-24), CHAIN_GLUE (Demo-2
  negative), LINKER_STOPPED_LEVEL (arm lk1/lk2; CLAUDE.md "it broke cam3"), NOCROSS_DROP_ALL (arm nc1, superseded by
  NOCROSS_DROP_SMALL), NOCROSS_EXTENT_FALLBACK (arm nf2, superseded by NOCROSS_NO_FALLBACK), APPLY_GATE_FAIL_OPEN (fail-closed is
  the gate's stated contract).
- **Physics or recommendation?** Housekeeping. If we do nothing: dead branches stay in the counted path.
- **Raw video + calibration alone?** Unchanged.

## 2. Delete
- Flags: the seven above. Dead code behind them: ensure_cut_dump, glue_chained_fragments (track_cut.py); the demotion time-local
  mix (two_pass block, pass2_replay param, pipeline block, _demotion_timelocal); score_destination_by_polyline_extent and
  _projects_inside; the stopped level and LINKER_STOP_GAP_S in the linker; their tests; scripts/viz_glue_demo.py (demo of the
  deleted glue); the two stopped-level asserts in scripts/reprocess_default.py.
- Add-back: ~0 %. Nothing the default uses was cut.
- NOT deleted, on purpose: TRACKER_WEAK_BIRTH_PROMOTE. Its recipe key ("promote") is part of the pass-1 recipe passed to the
  tracker (two_pass._cfg_weak_birth, also scripts/research_breaks.py), so deleting it risks invalidating cached dumps' reuse key,
  and test_tracker_weak_birth.py exercises promotion. config.py says "back on once that continuity is fixed": an open intent.
  Needs its own arm (tracker evidence, not fleet scores).

## 3. Simplify
- No constants added; LINKER_STOP_GAP_S removed. The linker's levels list is now two fixed moving levels.

## 4. Accelerate
- Counts are identical by construction (all flags OFF), so the check is one fleet on the existing dumps. NOTE: the linker
  signature lost two keys, so the lk{sig} derived dumps are rebuilt once (content should be identical); expect a slower first run.

## 5. Automate — nothing yet.

## Gate (declared before scoring)
- ARMS: control = foctl / fodel (default, 91.88 on 11 windows); arm = this code, stem fodg.
- PASS: every window delta 0.00 and event counts identical (cam3 0600 29220 events / 7997 dropped). Any difference is a bug in
  the deletion, not a trade-off.
- Fresh working DB mtimes printed (LESSONS 2026-10-15).

## Independent review
`/review-arm docs/plan_delete_negative_flags_2026-11-21.md` in a fresh session.

## Review date
2027-02-21.

## STATUS (2026-11-21)
Code deleted, suite 1368 passed (1389 - 21 tests of deleted code).
FLEET CONFIRM PASS (stem fodg, 2026-11-21, 11 windows, FLEET_WORKERS=4): fleet 91.88 -> 91.88 (+0.00); all 11 score_fodg_*.json
are byte-identical to score_fodel_*.json (fresh mtimes 02:05-02:32); cam3 0600 events=29220 dropped=7997. Not covered: cam1 0700 (outside
the default 11-window list). Review NOT yet run.
