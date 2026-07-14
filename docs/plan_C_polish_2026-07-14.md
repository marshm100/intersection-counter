# Plan — §4 item 7: C review-UX polish (2026-07-14)

Driven by the stage-3.4 dry-run's feedback (plan_stage34 doc, residuals) plus
the two C-items MASTER_PLAN carried ("stopping rule surfacing + batch-card
ergonomics"). No accuracy mechanisms; no counting-path changes; frozen
constants throughout. The worklist already has cards/batch-keys/keyboard/
live-count — this is polish on real gaps, not a rebuild.

**Correction to the stage-3.4 residual list:** residual (3) "trims PATCH
endpoint missing" is WRONG — `PATCH .../trims/{trim_id}` exists
(intersections.py:570, with `_validate_trim`). The 405 was never actually
observed, only inferred from an incomplete grep. Struck from scope; the
stage-3.4 doc is amended alongside this plan.

## A. Two-pass job cancel (the one real dead-end)

Today the running chip's Cancel posts to the LEGACY `/processing/cancel`,
which knows nothing about two-pass jobs — the operator's only recourse is
killing the server.

- **Backend:** `cancel_requested` flag on the two-pass job dict
  (`_jobs[(pid, f"i{iid}")]`), set by new
  `POST /projects/{pid}/intersections/{iid}/two-pass/cancel` (404 when flag
  off, 409 when no running job). Check points, coarse by design:
  1. between windows and between stages (pass-1 → pass-2) in
     `_run_process_job`;
  2. inside `run_pass1`'s frame loop (it already has the progress hook —
     check every progress tick, i.e. ~5000 frames cached / 200 ingest);
  3. inside `replay_camera`'s frame loop (our code; check every ~1000
     frames) — threaded through `run_pass2` as an optional `should_cancel`
     callable.
  NOT cancellable: the corpus-bank build (scripts function, minutes) and
  `_finish_apply` (must stay atomic — backup → swap → rebuild runs to
  completion once entered). Cancel lands at the next checkpoint; the UI copy
  says so ("Cancelling after the current step…").
- **Semantics:** on cancel, `v3_run_state` → `cancelled`; job dict status →
  `cancelled` with `completed` results kept. Already-applied windows STAY
  applied (each was atomic with its own backup); working DBs/partial dumps
  stay on disk (resume/reuse handles them — a partial dump resumes with the
  seam warm-up, a computed sidecar reuses).
- **UI:** the chip's Cancel routes to the two-pass cancel when a two-pass
  job is running (the chip knows via the C-item below); `cancelled` chip
  state offers Restart (existing chip case).
- **Tests:** cancel between windows (job with 2 windows, cancel after the
  first → one applied, state cancelled); cancel mid-pass-1 via the hook
  (ingest stub from stage-3.4 tests); 404/409 endpoint guards.

## B. S5 flags must survive a multi-window apply

`_finish_apply` rebuilds the intersection queue with ONLY the current
window's merge-borderline rows — after the cam2 three-window apply, S5
reflects study_1600 alone (observed in the dry run: flags_s5 = 1). The
rebuild wipe-and-recreate is correct; the extras are just under-scoped.

- **Fix at the job level (exact for the product path):** `_run_process_job`
  collects each window's `result["borderline"]` and, after the LAST window,
  runs one final `rebuild_flags` with the UNION of s5 extras across all
  windows of the run, deduped by (camera, cell) keeping max impact.
  Per-window `_finish_apply` keeps its current behavior (its intermediate
  rebuild is transient); the final rebuild supersedes it.
- **Deliberately NOT the sidecar-union design** (gathering borderlines from
  all "current" sidecars at every rebuild): a computed-but-never-applied
  sidecar would then feed flags describing events that aren't in project.db.
  The job-level union only sees windows it actually applied. The
  single-camera `/two-pass/run` path keeps single-window semantics
  (documented; it's the dev surface).
- **Tests:** two-window synthetic process (monkeypatched run_pass2 returning
  distinct borderlines) → final queue holds both windows' S5 rows; dedup
  keeps max impact.

## C. Two-pass live progress on the chip

The job dict already carries stage/camera/variant/frames — the chip shows a
generic line because `/processing/status` falls back to bare `v3_run_state`.

- **Backend:** `get_process_job(project_id, intersection_id)` accessor in
  `routers/two_pass.py`; `processing_status` merges it as a `two_pass` key
  when present (running OR terminal-with-results). Add `window_index` /
  `window_total` to the job dict in `_run_process_job` (it knows both).
- **UI:** `_processingChipHtml` running case, when `status.two_pass`
  present: "Two-pass · camera 2 · study_1100 (window 2 of 3) · pass 2" +
  the pass-1 frames bar when `progress` is present (pass-2 has no
  incremental counter — window-level granularity is honest). Cancel button
  routes per item A.
- **Test:** processing_status returns the merged `two_pass` block while a
  (stubbed) job dict entry exists.

## D. Stopping rule surfacing (the worklist's "when am I done")

The sidebar shows the gate verdict but not the PATH to ship: an operator
sees "Gate: FAIL" with no idea which of the four items blocks or what
action closes it.

- **Sidebar gate breakdown:** render each acceptance item
  (corridor_consistency, reverse_balance, spot_count, review_flags) as a
  row: verdict badge + its `detail.note` + a one-line "what closes this"
  hint mapped per item (spot_count review → "record a spot count on the
  QA tab"; review_flags → "work the cards below"; conservation items →
  "investigate on the QA tab — flags alone won't clear these"). Pure
  render over the existing `/qa/acceptance` payload — no backend change.
- **Progress-to-done line:** "N cards (M flags, est. impact I) between you
  and a clean queue" using the summary the sidebar already fetches — plus
  the existing ship banner unchanged. No new math, no new thresholds; the
  ±5% logic stays inside the acceptance endpoint (single source of truth).
- **Refresh cadence:** gate + summary refetch after every terminal action
  (already happens via `_wlRefreshList`) — no polling added.

## E. Batch-card ergonomics

Two cheap, high-value keys; nothing structural:

1. **Undo last action (`Z`).** A mistaken `B` on a 40-flag card is
   currently unrecoverable except flag-by-flag hunting. Client-side undo
   stack of the session's terminal actions: for each action push
   `{flag_ids, prior_status, event_id?, prior_event_fields?}`;
   `Z` pops one entry and reverts via existing endpoints — flags PATCH
   back to `open` (allowed status; `resolved_at` clears on reopen —
   verified in `update_flag_status`), event edits PATCH back
   (`movement`, `rejected`) using the prior values captured from the
   enriched flag at display time. Batch actions revert the whole batch
   (the batch endpoint response doesn't list ids — capture the card's
   member flag_ids client-side before posting). Add-missed is NOT
   undoable (no event-delete endpoint; out of scope — the form is
   deliberate enough).
2. **`Shift+1–4` = batch movement** on `dest|` cards (the buttons exist;
   the keyboard model stops at per-item 1–4). Guard identical to the
   button visibility: batch_key starts with `dest|` and group > 1.

- **Tests:** endpoint-level none needed (no backend change); UI-level via
  the gate drive below.

## Stage 2 — implementation detail (planned 2026-07-14, post-stage-1)

All in `frontend/js/setup.js` except one two-line backend addition. Stage 1
already ships everything the chip needs via `/processing/status`'s
`two_pass` block.

### 2a. Chip render (`_processingChipHtml`)

- **`running` + `status.two_pass.status === 'running'`** (call it `tp`):
  - Subline: `Two-pass · camera {tp.current_camera} · {tp.current_variant}
    (window {tp.window_index} of {tp.window_total}) · {stage}` with stage
    labels: `pass1` → "pass 1 — tracking", `pass2` → "pass 2 — counting",
    `s5-union` → "finalizing QA flags", null → "starting".
  - Progress bar only when `tp.stage === 'pass1' && tp.progress?.total > 0`
    (frames/total; pass-2 has no incremental counter — window granularity
    is honest, per the plan's §C).
  - `tp.cancel_requested` → append "· cancelling after the current step…"
    and render Cancel disabled.
  - Buttons: **Cancel → `v3CancelTwoPass(iid)`** (new); **hide "View live"**
    — it feeds from the legacy preview queue, which a two-pass job never
    fills (same dead-end class this plan exists to fix).
  - Resilience: a server restart wipes `_jobs` → `two_pass` disappears and
    the chip falls back to the existing generic two-pass subline (the
    `segCount > 0` guard from the dry-run fix). No code needed; stated so
    nobody "fixes" it.
- **`cancelled` + `status.two_pass` present**: detail line "stopped at:
  {tp.detail} — {tp.completed_windows} of {tp.window_total} windows
  applied"; single **Restart → `v3StartProcessing(iid)`** button (its
  plan-endpoint probe routes two-pass vs legacy at click time — correct
  even after a restart wipes the block). When no `two_pass` block, the
  legacy cancelled buttons stay exactly as they are (`v3ReprocessFromStart`
  has legacy checkpoint semantics that must not be re-routed blindly).
- `error`/`complete` cases: unchanged (two-pass errors already land in
  `v3_run_state.error_message`; complete keeps dashboard/Excel).

### 2b. The one backend touch

The cancel handler parks `{status, kind, detail, completed}` — the chip
can't say "2 of 3 windows applied" because `window_total` is dropped and
`completed` is a heavy payload the whitelist strips. Keep
`window_index`/`window_total` in the parked dict, add
`completed_windows: len(results)`, and whitelist `completed_windows`.
Extend `test_cancel_between_windows` to assert them.

### 2c. Cancel routing (`v3CancelTwoPass`)

New function, used only by the chip's two-pass branch: `window.confirm`
copy states the semantics ("stops at the next checkpoint; the current step
finishes; already-applied windows stay applied") → POST
`/two-pass/cancel`; 409 → alert (job already finished between polls —
benign race); then force one chip refresh. `v3CancelProcessing` (legacy)
is untouched.

### 2d. Evidence gate (Playwright, corridor intersection 2)

Reuse makes this cheap: all three cam2 windows are pass-2-current, so a
re-run is ~apply-only per window (~1–2 min each: 360 MB backup copy +
window swap + flag rebuild) — long enough to screenshot, short enough to
finish. No artificial slowdowns, no sidecar deletions.

1. Snapshot pre-state (the dryrun_verify pre/post harness).
2. Card 2 → Confirm & process (dialog auto-accept) → Processing tab.
3. Screenshot the live subline (window 1, "pass 2 — counting").
4. When `window_index ≥ 2`: click Cancel → confirm → screenshot the
   cancelling/cancelled chip. Assert: `v3_run_state = cancelled`; applied
   windows' event counts Δ0; S5 rows = union of the APPLIED windows'
   sidecar borderlines (the stage-1 cancel handler runs the union).
5. Restart via the chip's new Restart button → run to completion →
   complete-chip screenshot.
6. Final assert: per-window event counts Δ0 vs pre-state, backups present.
   **Flag-count note:** the S5 rows may legitimately differ from
   yesterday's `flags_s5 = 1` — the union fix is SUPPOSED to change that.
   The gate asserts S5 == the deduped union of the three sidecars'
   borderline cells (computed from the sidecar files), not equality with
   the pre-fix count. Event counts stay strict-Δ0.
7. `node --check setup.js`; re-run the two-pass test files both flag
   states (the 2b field change touches the router).

Ops rails: server detached (Start-Process), Monitor for the run wait, no
`.py` edits while the job runs (the 2b edit lands BEFORE the drive).

## Sequencing, gates, evidence

1. **Stage 1 — backend (A cancel, B S5 union, C job accessor):** unit
   tests as listed; suite green with flag ON and `TWO_PASS_ENABLED=0`.
2. **Stage 2 — chip UI (C render + A cancel routing):** node syntax check;
   Playwright evidence on the corridor: start a small process run (a
   pass-2-current window — reuse makes it fast), screenshot the live
   subline, cancel it mid-run, screenshot the cancelled chip; then re-run
   to completion to leave the corridor state clean (reuse = minutes).
3. **Stage 3 — worklist (D + E):** Playwright drive on intersection 2's
   real 891-flag queue: resolve one, batch-resolve a small card, `Z` undo
   both, `Shift+2` a dest| card, screenshot the sidebar gate breakdown.
   DB assertion after the drive: flag statuses net-unchanged where undone
   (the drive must leave the queue as it found it — resolve/undo pairs).
4. Amend the stage-3.4 doc residual (3) correction. Commit per stage with
   numbers; update MASTER_PLAN item 7 on completion.

**Ops discipline during stage 2/3 drives:** server via Start-Process, no
`.py` edits while a job runs (reload watcher), Monitor for job waits.

## Out of scope (named, with reasons)

- **API starvation during bank build** (dry-run residual 1): the job thread
  holds the GIL through numpy-heavy stages; the real fix is a subprocess
  job runner — an architecture change shared with the legacy pipeline, not
  polish. Revisit only if operators actually collide with it.
- **Sidecar `applied` field semantics** (residual 4): cosmetic; apply
  evidence lives in backups + project.db.
- Add-missed undo (needs an event-delete endpoint — new mutation surface).
- Any flag-feeder threshold changes (S1 sensitivity is §4-3 residual work,
  not UX).
