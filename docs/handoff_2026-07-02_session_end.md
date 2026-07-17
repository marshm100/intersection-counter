# Handoff — 2026-07-02 session end (COLD START after reboot)

**Read this first, then `docs/MASTER_PLAN.md`.** Branch
`claude/accuracy-impl-2026-05-27`. Two commits this session, **not pushed** (push
when ready): `9e8a95f` (spot-window fix) + the diagnostics commit on top of it.
Working tree otherwise clean. The scratchpad from the prior session is GONE (temp
dir is per-session); everything durable is in git + auto-memory.

---

## ⚠️ WE ARE MID-MACRO-PLAN — this is not a standalone task

The governing roadmap is **`docs/MASTER_PLAN.md`** ("from a validated counting stack
to an operator-ready Miovision replacement"). We are **inside §4 sequencing**, not
starting fresh. Macro status:

- **§4.1–4.3 DONE** — blind-QA flag queue (§3-B), review UX (§3-C), productized
  pipeline + export gating (§3-A). All shipped in prior sessions.
- **§4.4 partial** — §3-E deliverables (L/M/A, Excel, PDF) mostly done; **§3-D
  articulated classifier NOT done** (validation-blocked: aggregate-only GT = overfit
  trap; see [[project_fm51_audit_master_plan]]).
- **§4.5 DONE this session** — §3-D low-light: **disproved** as a fixable detection
  problem (640×480 source-resolution wall) and closed with the **spot-window
  stratification** mitigation. See [[project_lowlight_wall_spotwindow_2026_07_02]].
- **Cross-cutting §1b acceptance metric (per-approach ≤5%)** — the per-approach
  attribution lever. THIS is where the immediate resume task lives.

The governing principle throughout is **BLIND DEPLOYMENT** (Miovision/manual GT is
DEV data, never a deployment dependency; don't per-site-overfit) and **VALIDATE
BEFORE SHIPPING** (it has killed many "obviously correct" fixes — the corridor bank
is GT-informed = the §0 overfit surface).

---

## What shipped this session (committed)

1. **`9e8a95f` — spot-window stratification (the real win).** §3-D low-light lever
   taken from MASTER_PLAN §4, disproved (Tier-1 experiment: CLAHE enhancement HURTS
   −6%, yolo26l@1280 only +6% uniform — 640×480 source can't be upscaled to recover
   distant vehicles), and blind-QA proven unable to auto-catch the gradual FM51 PM
   sag. Fix: `spot_check.py` now stratifies spot-count windows by processed segment
   (trim/time-block) and the acceptance gate requires a spot count in EVERY segment
   before "pass" — so an all-AM sample can't ship a run whose PM was bad
   (MASTER_PLAN §5). Tested (14 spot + 61 dependent green), FM51-validated. Full
   detail: `docs/handoff_2026-07-02_lowlight_spotwindow.md`.
2. **Diagnostics commit** — `scripts/corridor_per_approach_baseline.py`,
   `audit_missing_cells.py`, `corridor_metric_sweep.py` (fast no-replay corridor
   tools) + `scripts/diagnose_cam2_eb.py` (the cam2 EB root-cause reproducer).

---

## ▶ IMMEDIATE RESUME TASK: cam2 EB entry-tiebreak (per-approach §1b)

**Now RAM-unblocked by the reboot** — this was diagnosed to the mechanism last
session but its fix VALIDATION needs `replay_fullchain`/retrack, which OOM'd at
264 MB free. Reboot should give the headroom.

**Airtight diagnosis** (reproduce with `py scripts/diagnose_cam2_eb.py`): cam2 EB is
OVER +25% while SB is UNDER −11% — a ~700-veh **SB↔EB attribution swap**.
**SB-thru (27→29) and EB-right (28→29) share the leg-29 exit** (1 px apart); EB-right
lies within **11 px** of SB-thru over its whole length while their **entries are
171 px apart**. `mdh` scores by `min(directed distances)` (fragment-robustness), so
it sees the two as ~11 px = the same shape, the shared exit makes the tail terms
identical, and the **entry — the only discriminator — is exactly what the min-
relaxation discards** → SB-thru matches EB-right → origin rewritten SB→EB. Likely a
second instance at the leg-26 exit (SB-left 27→26 vs EB-thru 28→26).

**THE FIX** (design): in `backend/services/trajectory_classifier.score_path_joint`,
when the top-2 candidate paths **share an exit** (endpoints within ~15 px) AND are
collinear near it (min-directed below a threshold), break the tie with the
**trajectory's ENTRY region vs each path's entry**, instead of the mdh score. Do NOT
globally trust entries (FOV clips approaches — that failed before, cam2 14.4→23.5);
this is a TARGETED tiebreak only for shared-exit collinear pairs.

**VALIDATION (mandatory, per-cam regression guard):**
- `py scripts/replay_fullchain.py --camera 2` reproduces live per-approach (validate
  the instrument tracks the metric FIRST — expect EB ~33 / SB ~12).
- Apply the scorer change, re-run: EB should drop toward Miovision (3020) and SB rise
  toward 6385, NB/WB unmoved.
- **Then run cams 1,3,4,5 the same way** — the change MUST NOT regress them (the
  memory is full of cam-specific regressions from "obvious" fixes). Use
  `scripts/corridor_metric_sweep.py`-style driving; each replay is minutes.
- Effect is entangled (multi shared-exit pair, ~700 veh) so the net may need the
  leg-26 pair handled too. Measure, don't assume.

**Do NOT** ship without the 5-camera replay validation. **Do NOT** re-attempt: the
mdh↔dtw metric choice (RESOLVED, keep mdh — `docs/mdh_vs_dtw_sweep_2026-06-30.md`);
bank completeness (EXHAUSTED — cam2 SB-left shipped, other cams' missing cells are
phantom/low-yield); a naive duplication/fragment-dedup (REFUTED — caught opposing-
traffic crossings). All three are dead ends already walked this session.

---

## Environment (the whole session fought this)

- **The box is 8 GB and the project DB is on OneDrive.** Free RAM hit **219–279 MB**;
  processes (replays, pandas imports, even a cam2 event scan) got **OOM-killed**.
  The reboot is to fix this. **OneDrive was set to PAUSE SYNC** — that did NOT free
  RAM (the process keeps its working set) but should reduce DB-read stalls. After
  reboot, expect OneDrive to re-consume RAM over time; do the replays early.
- **Low-RAM diagnostic pattern that WORKS even starved:** pure `sqlite3` (streams
  pages, tiny result via GROUP BY) + `parse_miovision_xml` (ElementTree). AVOID
  `triangulate_manual`/`interval_metric` import chains under pressure (they pull
  openpyxl/pandas → OOM). `diagnose_cam2_eb.py` follows this pattern.
- **Timing ops:** run in BACKGROUND, redirect to a file, `cat` it — a killed/timed-
  out foreground op loses output. Console is cp1252 → keep prints ASCII.
- **Lazy migrations:** first backend `get_connection` to each project DB runs
  index/backfill migrations (minutes on this box, sentinel-guarded, once). Corridor
  `97a7849a` + FM51 `0acb12c0` are already migrated.
- **App server:** `py start_server.py` on port 5000 (NOT 8000). It holds `project.db`
  (WAL) — stop it before DB writes; `tasklist` is authoritative for its PID
  ([[reference_server_process_kill]]). StatReload restart-loops under OneDrive; boot
  with reload disabled.

---

## Memory to load (auto-memory, persists across the restart)
- [[project_per_approach_attribution_2026_06_30]] — the per-approach thread; the
  2026-07-02 update has the airtight cam2 EB diagnosis + the refuted dead ends.
- [[project_lowlight_wall_spotwindow_2026_07_02]] — this session's shipped fix.
- [[project_fm51_audit_master_plan]] — the macro roadmap pointer (MASTER_PLAN.md).
- [[project_interval_metric_baseline]], [[project_cam2_nms_applied]],
  [[project_build_bank_recovery]] — cam2 context.

## Git
Branch `claude/accuracy-impl-2026-05-27`, 2 commits ahead of origin (unpushed):
`9e8a95f` spot-window + the diagnostics commit. Push when you're ready.
