# Overnight handoff — 2026-05-21 polyline architecture test

## What got built today

The five-phase polyline-calibration architecture from the plan, landed in
three commits: `33381a9`, `8498046`, and the wrap-up commit. Branch is
`claude/bootstrap-project-structure-TC2A0`.

| Phase | What | Files |
|---|---|---|
| 0 | `scripts/auto_calibrate.py` + `scripts/auto_calibrate_viz.py` — DBSCAN-style clustering on trajectory starts/ends, polyline fit per (origin, exit) pair, movement labels from polyline tangents | scripts/ |
| 1 | `intersection_paths` table + `score_origin_by_polyline` + `score_destination_by_polyline` + pipeline tier-0 wiring (with auto-upgrade for cameras without paths) | backend/database.py, backend/services/{origin_detector,trajectory_classifier,pipeline}.py |
| 2 | Paths CRUD API (`/api/projects/{p}/cameras/{c}/paths`) + polyline drawing mode in calibration sidebar | backend/routers/calibration.py, frontend/js/calibration.js |
| 3 | `calibration_suggestions` table + `auto_calibrator_v2` background worker + suggestion API + UI banner with Preview/Apply All/Reject | backend/services/auto_calibrator_v2.py, backend/database.py, backend/routers/calibration.py, frontend/js/calibration.js |
| sklearn cleanup | Deleted the old DBSCAN module + its 5 failing tests; the old `/calibration/auto/*` endpoints replaced by `/calibration/suggestion/*` | backend/services/auto_calibrator.py (deleted), backend/tests/test_auto_calibrator.py (deleted), backend/routers/calibration.py |

Tests: 483 passing (was 487 — net -4 from removing the 5 sklearn failures + adding ~46 new tests across polyline matching / paths CRUD / pipeline init). The 2 pre-existing OneDrive teardown errors are unchanged.

## The overnight test that's running

**What:** Sunnyvale TX intersection 1 (camera 1), Balanced mode, AM + PM peaks (7:00-9:00 + 16:00-18:00), polyline calibration applied from the Phase-0 auto-cal script's output on a 15-min AM sample (7:00-7:15).

**Why:** This is the architectural validation. Pre-polyline (2026-05-20 baseline) had:
- L19 recall: **24%** (target: >70%)
- L20 over-attribution: **12,765%** of manual (2171 vs ~17) (target: <100)
- L18 phantom lefts: **67** in 23 min (target: <5)
- L21 fake throughs: **41** in 23 min (target: 0)

If the polyline architecture works, these numbers move dramatically toward ground truth. If they don't, the whole bet is wrong and we revert.

**ETA:** ~20-24 hours wall (Balanced on this hardware processes ~5-6× slower than real-time; 4h of footage → ~20-24h processing).

## Morning checklist

1. **Confirm the run finished:**
   ```powershell
   curl -s http://127.0.0.1:5000/api/projects/97a7849a/intersections/1/processing/status | py -m json.tool
   ```
   Expect `"status": "complete"` (or `"running"` if not done yet — let it finish).

2. **Run the morning summary:**
   ```powershell
   py scripts/overnight_summary.py
   ```
   This prints per-leg counts, runs `scripts/groundtruth.py --diff baseline`, and runs `scripts/replay_movement.py` to check Bug B residual on the fresh data.

3. **Check `n_origin_via_polyline` counter** in the status payload — non-zero means the polyline tier is firing.

4. **Look at the auto-cal output** at `evaluations/auto_cal_sunnyvale_am_15min.json` and the visualization at `screenshots/auto_cal_auto_cal_sunnyvale_am_15min.png` to see what calibration the pipeline used.

5. **Calibrated paths in the UI:**
   - Open http://127.0.0.1:5000
   - Sunnyvale TX → Intersections → NBeltLineRd-NorthwestDr → Cameras → Recalibrate first camera
   - Sidebar shows "Road paths" section with auto-cal'd polylines listed
   - Suggestion banner shows "applied" status

## Success criteria

| Metric | Pre-fix | Target | What it means if reached |
|---|---|---|---|
| Overall recall vs baseline | 64.9% (23 min AM only) | ≥70% over the full 4h | Polyline tier is a net positive |
| L19 recall | 24% | ≥70% | Bug A is solved by polyline matching |
| L20 attribution | 12,765% | <100 events | The driveway over-attribution is gone |
| L18 phantom lefts | 67 | <5 | Curve-aware classification works |
| L21 fake throughs | 41 | 0 | Same |

If MOST of these targets are met, the architecture works and we move to UX polish + multi-intersection rollout. If they're NOT met, we have to debug what's wrong with the polyline matching (likely tuning the `max_avg_distance_px` thresholds or revisiting the polyline fit algorithm).

## Failure-mode triage

- **L19 recall still low (<40%):** suggests the polyline isn't being matched. Check `n_origin_via_polyline` — if 0, the tier isn't firing at all. Likely cause: paths weren't applied to the camera before the run. Run `py scripts/apply_auto_cal.py --project 97a7849a --camera-id 1 --suggestion evaluations/auto_cal_sunnyvale_am_15min.json --save-suggestion` and re-run.
- **L20 still over-attributed (>500):** the auto-cal'd polyline for L20 may be too generous. Look at the visualization. Manual polyline drawing in the UI might fix it.
- **Lots of `insufficient_data`:** trajectories aren't matching ANY path. Lower the `max_avg_distance_px` from 30 default to 50 in `backend/services/origin_detector.py:score_origin_by_polyline` and re-run.

## What's left to build (deferred)

- **Phase 4** (continuous refinement): re-cluster trajectories after each run, surface drift, optional auto-update. ~3-5 days.
- **Auto-trigger on upload**: have video upload kick off an auto-cal job automatically. Trivial — just hook into `routers/videos.py`.
- **Multi-intersection rollout**: apply the same auto-cal → review → process flow to the other 4 Sunnyvale intersections.
- **More backend tests for Phase 3**: auto_calibrator_v2 + suggestion endpoints don't have unit tests yet (need video fixture).
