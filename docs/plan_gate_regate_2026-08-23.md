# Drawn-gates combined-basis regate (B1+B3 of the one-system pipeline) — gate doc

Declared BEFORE any scored run (gate discipline). Executes the revival
conditions of docs/plan_pathfit_dumps_2026-08-21.md on the personal
machine (base-20260823; controls proven byte-identical 2026-08-23).

## What is being tested

G-PF2-1 (2026-08-21) proved the paths and isolated the root: machine-
derived GATES are the accuracy cap (leg 28 = a 94 px stub above the
travel lanes; 1,275 journeys entering leg 27 die unexited in one 2-h
window; SB right counted 0 vs Mio 379; WB left 3 vs corpus-expected 42).

This round: (1) operator draws cam2 gate lines (B1 UI, shipped) —
operator-drawn gates are GEOMETRY TRUTH, not an experimental arm; they
are never rolled back by this gate. (2) pathfit --dumps re-derives cam2
paths against the drawn gates (cut + classification both improve;
(27,28) SB right predicted to self-evidence). (3) ONE regate:

- CONTROL = drawn gates + CURRENT production paths
- ARM     = drawn gates + refit paths (staged, then applied)

The 2026-08-19 controls are DEAD for this comparison (old-gate basis).
Fresh controls are replayed AFTER gates are drawn, BEFORE the arm.

## G-DG-1 (the ship gate)

- PASS: arm pooled 3-window movement bar (5/95 cell-bins, pooled
  compliant/scored) **> fresh-control pooled**, AND no single window
  more than **2.0 points below** its fresh control.
- Approach bar recorded alongside (secondary).
- Numeric control values (measured 2026-08-23 evening, BEFORE the arm):
  fresh-control pooled movement **57.8% (188/325)**; per-window movement
  study_0700 **61.9** (65/105), study_1100 **53.3** (57/107),
  study_1600 **58.4** (66/113). Approach pooled 43.8% (42/96):
  43.8 / 46.9 / 40.6. So G-DG-1 PASS requires arm pooled > 57.8% and
  no window below 59.9 / 51.3 / 56.4 respectively.
  NOTE, ledgered: the drawn gates ALONE (old paths still live) already
  beat the old-gate replay basis by ~+11 movement points pooled
  (46.7 -> 57.8) and turned study_0700 approach from 25.0 to 43.8.
- MISS: row-scoped byte-verified restore of intersection_paths from the
  pre-apply backup; refit suggestion back to pending; negative ledgered
  here + roadmap. Drawn gates REMAIN (operator geometry).

## Backup pre-flight (measured 2026-08-23, read-only immutable opens)

| backup | integrity | events | paths | gate_segment col |
|---|---|---|---|---|
| project.db.bak_pathfit_20260819 | ok | 97,109 | 33 | **ABSENT** |
| project.db.bak_pathfit2_20260821 | ok | 97,109 | 34 | **ABSENT** |
| project.db.backup_pathfix_20260813_124527 | ok | 97,107 | 33 | **ABSENT** |

The -shm/-wal sidecars next to the 08-19 backup: wal is 0 bytes — the
accidental live-open on 08-21 wrote nothing; content trustworthy.

**Operational law from this table: every existing backup predates B1.
A whole-file restore from any of them ERASES drawn gates (the migration
re-adds the column empty). Therefore: (a) a NEW VACUUM-INTO backup is
taken immediately after gates are drawn and verified — it becomes the
primary restore point; (b) any rollback against pre-B1 backups is
row-scoped (intersection_paths), never whole-file.**

## Procedure (pre-registered)

1. Operator draws gates on cam2 (leg 28 first; then legs whose derived
   gates run as long diagonals). Save. Claude verifies legs.gate_segment
   rows and that the inward arrow direction was confirmed on screen.
2. NEW backup: VACUUM INTO + integrity + event-count assert (the
   apply_recal_updates._backup_db pattern) ->
   data/projects/97a7849a/backups/project_<stamp>_postgates.db
3. `run_pathfit_cli.py --dumps --dry-run` -> confirm cell support;
   stage; fold-audit; operator eyeballs any sharp_apex_review flags.
4. FRESH CONTROLS: run_pass2 replay study_0700/1100/1600 (apply=False,
   scratch workdir regate_20260823) + v2_score_dev, stems
   `regatectrl_cam2_study_*`. Fill control numbers into G-DG-1 above.
5. Apply staged paths via the live endpoint; verify 0 skipped + live
   fold audit + events untouched.
6. ARM replays same three windows, stems `regatearm_cam2_study_*`.
7. Diff merged_away + merge_expecteds ctrl-vs-arm from stats sidecars.
8. Verdict here + roadmap changelog + commit, either way.

## Verdict — G-DG-1 MISS on the refit paths; the CONTROL is the ship (2026-08-23 night)

| window | movement ctrl -> arm | approach ctrl -> arm |
|---|---|---|
| study_0700 | 61.9 -> 56.2 (**-5.7, breach**) | 43.8 -> 34.4 |
| study_1100 | 53.3 -> 50.5 (**-2.8, breach**) | 46.9 -> 40.6 |
| study_1600 | 58.4 -> 51.3 (**-7.1, breach**) | 40.6 -> 34.4 |
| pooled | 57.8 -> **52.6** (bar: >57.8) | 43.8 -> 36.5 |

All three windows breach. Row-scoped restore executed BYTE-VERIFIED from
project_20260824T010947_postgates.db (10 rows, ids 119-128 back; refit ids
149-161 removed; suggestion 2 back to pending; events untouched 97,109).

**The finding that matters is the CONTROL, not the arm.** Operator-drawn
gates + the existing curated production paths measured pooled movement
**57.8% (188/325)** — +11.1 points over the old-gate replay basis (46.7) —
with study_0700 approach 25.0 -> 43.8. Third consecutive pathfit negative
(W1a, G-PF2-1, G-DG-1), each on a different basis: machine-fit paths lose
to the operator-vetted production set even when fit from 14,819 cut-clean
fulls against correct gates. Mechanism echo of W1a: arm events fell
(5735->5669 / 4574->4498 / 7272->7182), insufficient rose, merge_kept and
merged_away both fell (240/368/503 -> 179/279/350) — path swaps depress
classification + partially deactivate turn-merge. Working conclusion:
path REFIT is a dead lever on this corpus; gate GEOMETRY was the live one.

Score artifacts: runs/v2_week1/score_regatectrl_cam2_study_*.json and
score_regatearm_cam2_study_*.json.

**SHIP STEP (the control basis):** the drawn gates are already production
geometry and the restored paths are production paths — production
vehicle_events still reflect the pre-gates basis until pass-2 re-runs.
Operator clicks **Confirm & process** on the Town East card (pass-1 reuses
dumps; pass-2 re-runs ~10 min) to land the measured 57.8/43.8 basis in
production counts.
