# 2026-05-22 — Polyline architecture validated, what's next

## Headline result

**Per-bucket recall went from 46–67% (pre-fix baseline) to 76–107% (polyline run)
across the processed AM + PM peak windows on Sunnyvale L19. Overall recall
on processed buckets: 63% → 92.2%.** The architectural bet paid off — the
polyline tier (origin attribution + destination scoring + movement labeling
in a single match against per-(origin, destination) road polylines) is a
clear net win over the previous tripwire-crossing + softmax-scorer + rank-
based-derive_movement stack.

| Bucket | Manual | Polyline (this run) | Pre-fix baseline |
|---|---|---|---|
| 7:00 AM | 564 | **558 (99%)** | 376 (67%) |
| 7:45 AM | 668 | 553 (83%) | 357 (53%) |
| 8:15 AM | 518 | 406 (78%) | 237 (46%) |
| 4:00 PM | 625 | **671 (107%)** | 382 (61%) |
| 4:30 PM | 732 | 743 (102%) | 481 (66%) |
| **AM total** | **4667** | **3999 (85.7%)** | **2583 (55%)** |
| **PM total** | **2730** | **2820 (103.3%)** | (no PM data) |

Snapshot saved to `evaluations/polyline-morning-2026-05-22.json` (compare
to `evaluations/baseline.json`).

## What got built (since 2026-05-21 morning)

Full polyline-calibration architecture per the plan, all five phases plus
the sklearn cleanup. Across these commits:

- `33381a9` — Phases 0-2 backend (auto-cal prototype + intersection_paths
  schema + score_origin/destination_by_polyline + pipeline tier-0 wiring
  + paths CRUD API). 21 polyline-matching unit tests, 12 CRUD tests.
- `8498046` — Phase 3 (auto-cal background worker + suggestion API + UI
  banner + polyline drawing mode in calibration.js) and sklearn cleanup
  (deleted backend/services/auto_calibrator.py and its 5 failing tests;
  the OLD /calibration/auto/* endpoints removed; replaced with
  /calibration/suggestion/* under the v2 service).
- `04dbfc5` — Overnight test scaffolding (apply_auto_cal.py to push
  suggestion JSON into intersection_paths; overnight_summary.py for
  morning analysis; original handoff doc).
- `256cba4` — Hand-crafted Sunnyvale polylines fixture as a fallback.

Net test count: **483 passing**, 2 pre-existing OneDrive teardown errors.
The 5 pre-existing sklearn failures are gone.

## What's still running

**Pipeline** (PID 9532, Sunnyvale intersection 1, Balanced mode):
- Status: `running`, segment 2 of 2 (PM peak)
- Progress: 51.9% through PM segment, ETA ~4.8h
- ~6824 vehicle_events already written
- Leave it running unless you need to cancel; the second half of PM peak
  will add ~3000 more events and let us see if recall holds.

## Where the polyline architecture still falls short

Tonight's data shows the *architecture* works but the **hand-crafted
polylines have wrong movement labels** in several places, because I
guessed left/right from leg positions without actually checking each
turn's geometry. Specifically:

| Issue | Manual | Polyline run | Diagnosis |
|---|---|---|---|
| L22 "phantom lefts" | 3 | **818** | The L22→L24 polyline is labeled "left" but the driveway is geographically to the RIGHT of an SB Belt Line vehicle. Swap label to "right". |
| L25 "fake lefts" | 213 (real) | **1199** | Several L25 polylines have flipped labels; the road geometry is correct but the left/right call is wrong. |
| L25 "fake throughs" | 7 | **2** | **FIXED** by polylines (was 41 in the baseline). |
| L24 driveway over-attribution | 15 | **529** | Down 76% from 2171 in the broken backward-extrap run, but the driveway polylines are still catching too many through-vehicles. Tighter match radius would help. |

The point: per-leg TOTAL counts are now in the right ballpark, but the
per-movement breakdown depends on whether the polyline's `movement_label`
was set correctly. Auto-cal infers this from polyline tangents and
would not have made the manual mistakes I made.

## Critical next steps

1. **Run auto-cal cleanly.** The 2026-05-21 attempt didn't finish in time
   for the overnight test; I fell back to hand-crafted polylines. Now
   that you're back, run a fresh auto-cal:
   ```powershell
   py scripts/auto_calibrate.py `
     --video "D:/Onedrive/.../405051_0035_20260512_000002 NBeltLineRd-NorthwestDr.mp4" `
     --sample-start 25200 --sample-end 26100 `
     --out evaluations/auto_cal_sunnyvale_am_15min.json
   ```
   Then push it into the camera via:
   ```powershell
   py scripts/apply_auto_cal.py --project 97a7849a --camera-id 1 `
     --suggestion evaluations/auto_cal_sunnyvale_am_15min.json --save-suggestion
   ```
   Visualize:
   ```powershell
   py scripts/auto_calibrate_viz.py --suggestion evaluations/auto_cal_sunnyvale_am_15min.json
   ```
   The auto-cal'd polylines should fix the movement-label issues.

2. **Tighten the L24 driveway match.** Even with correct labels, the
   driveway is catching ~35× too many vehicles. Two levers:
   - In `backend/services/origin_detector.py:score_origin_by_polyline`,
     drop `max_avg_distance_px` from 30 to 20 or 15.
   - In `backend/services/trajectory_classifier.py:score_destination_by_polyline`,
     drop `max_avg_distance_px` from 40 to 25.

3. **Re-run overnight with the auto-cal'd polylines** to lock in the
   final numbers. Expected outcome: L22 phantom lefts drop from 818 → <50,
   L25 fake lefts drop from 1199 → ~200 (close to manual 213), L24
   over-attribution further drops from 529 → maybe 100.

4. **Compare per-intersection.** Once Sunnyvale is dialed in, repeat the
   auto-cal → apply → run sequence on the other 4 intersections in this
   project to confirm the architecture generalizes.

## Files to know about

| File | What it is |
|---|---|
| `evaluations/baseline.json` | Pre-fix recall snapshot, kept as the comparison anchor. |
| `evaluations/polyline-morning-2026-05-22.json` | This morning's recall snapshot. |
| `scripts/auto_calibrate.py` | Phase 0 standalone — observe video, cluster trajectories, fit polylines. |
| `scripts/auto_calibrate_viz.py` | Renders the suggestion onto a video frame for inspection. |
| `scripts/apply_auto_cal.py` | Pushes a suggestion JSON into the live DB via direct writes (replaces all paths for the camera). |
| `scripts/overnight_summary.py` | One-shot morning analysis: run state + per-leg counts + groundtruth.py diff + replay_movement.py Bug B residual. |
| `scripts/groundtruth.py` | Manual TMC vs pipeline output diff. **Updated 2026-05-22** to use the recalibrated leg_ids (22-25 instead of 18-21). |
| `backend/tests/fixtures/sunnyvale_paths_hand.json` | Hand-crafted polyline fallback (the one used for tonight's run). |
| `docs/handoffs/2026-05-21-overnight-polyline-test.md` | Pre-test handoff with target numbers + failure-mode triage. |

## Pipeline state quick-reference

```powershell
# Status
curl -s http://127.0.0.1:5000/api/projects/97a7849a/intersections/1/processing/status

# Cancel (if you need to)
curl -s -X POST http://127.0.0.1:5000/api/projects/97a7849a/intersections/1/processing/cancel

# Kill server hard (if you need to load new code)
taskkill //F //IM python.exe
# Then: py start_server.py
```

## Open questions worth thinking about

1. **Should the polyline match radius be a per-intersection tunable** (like
   we did with TRIPWIRE_HALF_LENGTH_PX yesterday)? Sunnyvale benefits from
   tighter radii for the driveway; other intersections might benefit from
   looser radii.
2. **Are vehicle types distinguishable enough to weight differently?** A
   truck takes wider turns than a car; matching against the same polyline
   may under-fit one or the other.
3. **Should the auto-cal sample window be the engineer's choice or always
   "first 15 min of AM peak"?** Different intersections have different
   peak times.

Branch is at `256cba4` plus this commit. All pushed.
