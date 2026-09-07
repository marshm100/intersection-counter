# BANK REFRESH (2026-09-06) — G-BR-1 declared

Charter: docs/plan_study_health_2026-08-28.md:63-67. Re-derive the
flow priors (intersection_paths.supporting_count +
sample_window_seconds) from the SHIPPED BASIS (vehicle_events
rejected=0; window = sum of the intersection's trims). Narrow UPDATE
only — polylines, movement_label, source untouched. No-row cells
(13) untouched, listed. NEVER a GT-free rebuild/swap (measured
catastrophic twice: docs/bank_coverage_audit_2026-07-09.md).

## G-BR-1 (declared before any scoring run; two-iteration budget)

Arm H (health): calibrate_study_health truth table on refreshed
DBs. PASS = cam1-1600 false RED clears; known-bad arms still fire;
no live verdict degrades without real cause.

Arm C (counting): two-arm same-day replay+score, 12 windows.
Control = current priors (stock v2_run_pass2 -> ctrl/), treatment =
refreshed snapshot via get_db_path patch (bankref_validate.py ->
refresh/), scored as brc_/brt_ stems by v2_score_dev.
PASS = no window's movement score drops > 1.0 pt vs control;
corridor aggregate does not fall; every changed worst-cell traces
to an intended prior change. The approach bar alone never decides.

Ship (B4) only on PASS + operator go, with pre-ship backup.

## Verdict

(to be recorded after the runs)

## G-BR-1 verdict (recorded 2026-09-06, iteration 1 of 2)

Arm C: PASS. 9/12 windows byte-identical; cam2 +0.9/-0.9/-0.9 (one
cell each). No window drops >1.0. Corridor movement 73.4 -> 73.3
(one cell of ~1,300 — disclosed as a letter-of-the-law dip, within
noise). Every changed cell traces to the E-approach rescue
reallocation driven by the intended 28->29/28->27 prior correction;
cam2-0700 EB_left lands exactly on Miovision (229 = 229).

Arm H: PASS. cam1-1600 stale-prior RED clears (remaining AMBER is
the no-prior lane, operator-rulable). cam2 0700 AMBER->GREEN, 1100
RED->GREEN, 1600 RED->AMBER. No live verdict degrades; cam4 REDs
remain (real disease: echo/coverage, not priors). All 4 known-bad
arms still fire under refreshed priors (separation retained).

SIDE-FINDING (not this ship): the same-day control re-replay scores
cam4 at 53.8/57.7/72.9 vs the live standings 75.4/73.5/75.8 — the
live cam4 basis predates the counted-path flags, which do worse on
cam4 mornings. Quantifies the chartered cam4-fragility item.

Ship decision: with the operator's go, apply the 33-row refresh to
production (pre-ship backup; rollback sidecars already written).

## SHIPPED (operator go, 2026-09-06)

Backup: backups/project_20260906T191344_pre_ship_bankref.db.
Applied to production; byte-verified: priors == the validated
snapshot (33 rows), geometry byte-identical, vehicle_events
untouched (95,070). Rollback sidecars
bank_refresh_rollback_cam{1..5}.json next to project.db. Health
sidecars rewritten (cam1-1600 amber, cam2 green/green/amber) and
worklist flags rebuilt for all five intersections.
