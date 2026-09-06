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
