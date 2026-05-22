# 2026-05-22 PM — Resume verified, reference snapshot saved, what's next

Short session (~15 min of clock). The morning handoff
(`2026-05-22-polyline-validated.md`) is the substantive one — read that
first for the polyline architecture story. This doc only covers what
moved in the afternoon.

## What this session actually did

1. **Caught a false claim in the prior handoff.** The morning doc said
   the pipeline was still running (PID 9532, ETA ~5h). It wasn't —
   process was dead, port 5000 empty. The polyline run had completed
   on its own before the session opened.

2. **Verified resume-from-checkpoint end-to-end via Playwright.**
   The Sunnyvale TX intersection had a checkpoint at frame 612,582
   (video 1, camera 1, trim 2). Clicked **Continue** in the Processing
   tab; observed:
   - `v3_run_state.intersection_id=1` flipped `interrupted` → `running`
     → `complete`.
   - Trim 1 events (4,004) untouched — confirms no re-processing of
     completed segments.
   - Trim 2 events rewound from 2,901 → 2,802 (last durable checkpoint),
     then ran forward to **5,781**.
   - Final frame on trim 2: 647,980.
   - Final total: **9,785 vehicle_events**. Dashboard renders, Excel
     button exposed.

3. **Saved the completed run as a reference snapshot**:
   `evaluations/sunnyvale-northwestdr-complete-2026-05-22.json`.
   Captures run metadata + per-trim event counts + per-leg turn matrix.
   Sits next to `baseline.json` and `polyline-morning-2026-05-22.json`
   for future diffing.

4. **Added a "Headline" rule to the `/weekly-report` skill.** New
   section 0 at the top of every report — a one-line callout for a
   quotable result (metric jump, milestone, breakthrough, blocker
   resolved). New hard rule pointing the writer at handoff docs,
   evaluation snapshots, and keyword-rich commits/prompts to find it.

5. **Generated `weekly-reports/2026-05-22.txt`.** Led with the
   63% → 92% headline pulled from the morning handoff. Covers Mon
   5/18, Wed 5/20, Thu 5/21, Fri 5/22 — ~10.5h total.

## Side finding (worth tracking, not urgent)

The legacy `GET /api/projects/{project_id}/processing/status` endpoint
reads `project_info.status` (never set by the v3 orchestrator) instead
of `v3_run_state.status`. While the pipeline was actively running this
afternoon the endpoint still returned `{"status":"created",
"is_running":false}`. The UI doesn't use this endpoint for the
intersection cards, so it's harmless to users — but anything else
polling it will be wrong. Two options if/when you touch this:
- Update the endpoint to read `v3_run_state` and aggregate across
  intersection-days.
- Delete it if nothing else consumes it. (`frontend/js/processing.js`
  no longer calls it; double-check before removing.)

## What did NOT move (still open from morning handoff)

These are the original next steps from `2026-05-22-polyline-validated.md`
— none of them happened this session:

1. **Run auto-cal cleanly** on Sunnyvale. The hand-crafted polylines
   used for the overnight run have several wrong `movement_label`s
   (L22 "phantom lefts" 818 vs manual 3; L25 "fake lefts" 1199 vs 213;
   etc.). Auto-cal infers labels from polyline tangents and would not
   make those mistakes.
2. **Tighten L24 driveway match radius** — `max_avg_distance_px`
   currently 30 (origin) / 40 (destination), suggest 20 / 25.
3. **Re-run overnight** with auto-cal'd polylines + tighter L24.
4. **Generalize to the other 4 intersections** in the same project
   once Sunnyvale is dialed in.

Today's reference snapshot is the "before" for steps 1-3. After they
land, diff the new snapshot against
`evaluations/sunnyvale-northwestdr-complete-2026-05-22.json` to
confirm L22/L25/L24 numbers improved.

## State at session close

- **Branch:** `claude/bootstrap-project-structure-TC2A0`, pushed.
- **Uncommitted on disk:**
  - `.claude/commands/weekly-report.md` (modified — headline rule)
  - `evaluations/sunnyvale-northwestdr-complete-2026-05-22.json` (new)
  - `weekly-reports/2026-05-22.txt` (new)
  - `docs/handoffs/2026-05-22-pm-resume-verified.md` (this doc)
- **Server:** running at PID assigned during this session (started via
  `py start_server.py`). Will die on next reboot — restart with
  `py start_server.py` from project root.
- **Sunnyvale TX project (97a7849a) NBeltLineRd-NorthwestDr:** status
  `complete`. Dashboard works. Excel export ready but not exercised.
- **Tests:** 483 passing (unchanged from this morning).

## Quick-start for next session

```powershell
# Server
py start_server.py

# Confirm Sunnyvale completion (should still show 9,785 events)
curl -s http://127.0.0.1:5000/api/projects/97a7849a/intersections/1/processing/status

# Diff against today's snapshot after any change
# (manual diff for now — no script yet)
type evaluations\sunnyvale-northwestdr-complete-2026-05-22.json
```

The next big lever is **auto-cal on Sunnyvale**. The full incantation
is in section "Critical next steps" of
`docs/handoffs/2026-05-22-polyline-validated.md`.
