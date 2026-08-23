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
- Numeric control values are filled into this doc when the fresh
  controls are scored — before the arm replays start, per discipline.
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

## Verdict

(pending)
