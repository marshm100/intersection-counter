# Handoff: build the OC+BoT per-regime hybrid tracker — intersection-counter

## Goal
Build a **per-regime hybrid tracker for cam1**: take THROUGH events from **OC-SORT**
(it counts throughs best) and TURN events from **BoT-SORT** (it sustains the sharp
cross-street turns OC-SORT fragments), combined into one event stream. Target:
recover the ~60-vehicle missing-turn bucket while keeping OC-SORT's throughs →
push cam1 from **net 21.8% / per-minute gross 30.7%** toward production-grade
(~15% gross). Project `97a7849a`, camera 1 (N Belt Line Rd & Northwest Dr,
640×480, Sunnyvale corridor). Branch `claude/accuracy-impl-2026-05-27` (latest
commit `185281a`).

## READ FIRST (memory + docs)
- memory `project_leg_labels_swapped` — the live state of all this work (180° relabel,
  OC-SORT tuning, OD-direct turns, BoT-SORT finding, NN-recovery failure). **Most important.**
- memory `reference_miovision_perminute_od` — the ground truth + harness (`od_accuracy.py`).
- memory `project_gpu_openvino_deferred` — OpenVINO wired, 3.72× (speed only).
- memory `feedback_robust_production_fixes`, `feedback_diagnostic_style`, `user_hardware_constraints`.
- docs `accuracy_roadmap_2026-05-29.md`, `dedup_plan_2026-05-29.md`.

## Why OC+BoT (and not the hybrid that already failed)
A hybrid was already tried and FAILED: it was OC-SORT + **ByteTrack** — ByteTrack
under-detects throughs, so it lost. The CORRECT split, validated this week
(`scripts/probe_tracker_od.py`, OD-track counts on identical cached detections):
- **OC-SORT** (min_hits=3, inertia=0.4): throughs GOOD (NB-thru 529, SB-thru 486 vs
  manual 593/425); sharp turns BAD (EB-left 9, EB-right ~8).
- **BoT-SORT** (`backend="botsort"`, with_reid=False): sharp turns GOOD (EB-left 20,
  EB-right 11, SB-right exact 34 — near the greedy-NN ceiling 24/22); but throughs
  UNDER (NB 473-492, SB 346) because it's ByteTrack-family → loses low-conf glare throughs.
So neither single tracker wins. OC+BoT takes each tracker's STRENGTH. (A custom
OC + position-NN recovery was also tried and reverted — it over-merged the dense
arterial and didn't recover turns; position-based sequential recovery is a dead end.)

## Current validated state
- Best single tracker = OC-SORT, bank `evaluations/recal_cam1_odturns.json` (NB/SB
  through + NB-left + EB-left + SB-right; **NO EB-right path** — OC tracked too few).
  → net 21.8% / gross 30.7%.
- Detection cache = `balanced_960_skip1.parquet` (actually yolo26l@1280, conf 0.08),
  07:00–07:30 only, **bbox-only (no images)** — both trackers run on it (BoT-SORT uses
  cmc='ecc' on a static dummy frame = identity, so no images needed).
- Corrected leg→approach: **{22:NB, 23:SB, 24:EB, 25:WB}** (the 180° fix). The DB's
  `cardinal_direction` is fixed; the turn-path bank + groundtruth use these.

## Build steps
1. **Re-derive the turn bank from BoT-SORT events** so it includes an EB-right path
   (BoT tracks ~11 EB-right ≥ min_support, so `derive_turn_paths_od` in
   `recalibrate_camera.py` can emit it). recalibrate reads `PROJECT_DB` — either add a
   `--db` arg pointing at a BoT-SORT events DB, or retrack BoT-SORT into project.db
   (BACK IT UP first; see `apply_recal_updates`/backups). Confirm an EB-right path
   (origin L24→dest L22) appears.
2. **Build the OC+BoT combine.** Generalize `scripts/hybrid_prototype.py` (currently
   OC+ByteTrack with through-swap variants — repurpose, don't trust its old logic):
   - retrack OC-SORT and BoT-SORT separately on the cache (with the BoT-derived bank),
   - combined = {OC events where movement='through'} ∪ {BoT events where movement IN
     ('left','right','u_turn')},
   - cross-backend dedup at the boundary: a vehicle both trackers attribute (e.g. a
     turning vehicle OC saw as a through-stub) — dedup by time-overlap + start
     proximity. Movement classes are disjoint so false-merge risk is low.
   - measure with `scripts/od_accuracy.py --show-od` (per-minute GROSS is the metric).
3. **Validate:** gross < OC's 30.7% (target ~15%), EB cells recovered (EB-right toward
   36, EB-left ~27), throughs preserved (NB ~593, SB ~425), no new phantoms. Check a
   second sub-window (07:00–07:15 vs 07:15–07:30) for stability.

## GOTCHAS (hard-won this session)
- **RACE:** NEVER read a temp DB while its retrack is still writing — wrong numbers.
  Wait for the task-completion notification AND confirm event count is stable (~1430 for
  the 30-min window) before reading. (Burned multiple times.)
- DB stores movement as **'through'/'u_turn'** (NOT 'thru'/'uturn'); groundtruth
  normalizes only at counting. SQL filters must use 'through'.
- `intersection_paths` is UNIQUE on (camera, origin, dest) — a duplicate path in a bank
  silently ROLLS BACK the whole retrack transaction (→ stale paths, garbage result).
  Use INSERT OR REPLACE; emit one path per (origin,dest,movement).
- `od_accuracy.py` LEG_IDX derives from `groundtruth.LEG_TO_APPROACH` (corrected).
  Miovision files live in `docs/historic data/Sunnyvale, TX/camN .../`;
  `parse_miovision_xml.camera_xml(cam)` resolves them.
- Cache is 07:00–07:30 only; a second disjoint window needs an overnight cache build
  (OpenVINO `DEVICE=openvino` now ~4× faster if you build one).
- Iteration loop = retrack from cache (`measure_bank.py --backend <name> --suggestion
  <bank>`), minutes per run. `measure_bank` now takes `--backend`.

## Honest framing + fallback
This is the **last position-based robust lever**. Expected gain if the boundary dedup
is clean: recover the turn bucket → possibly ~15% gross. If the cross-backend dedup
hits a complexity wall (the earlier hybrid had subtle SQL/label bugs), THAT is the
honest signal to **stop at OC-SORT (21.8/30.7) and consolidate**: commit, do the
mandatory engineer visual gate, ship the strong automated cells + route the residual
(esp. EB-right) to human review, and treat ReID (heavy, uncertain at 20–40px) as a
separate future project. Nothing is applied to production yet (engineer visual gate
pending); cam2–5 are seeded but not processed.

## How we work here
Diagnostic-first, data-driven, robust (no band-aids). Design/verify with Grok (read-only
plan mode): `"C:\Users\onkar\.grok\bin\grok.exe" --permission-mode plan --no-alt-screen
-p "<prompt>"` (do NOT pass --effort). (NB: Grok returned empty twice on the last long
prompt — retry or proceed on own analysis if it fails.)

START BY: confirming the OC-SORT baseline reproduces (`measure_bank.py --backend ocsort
--suggestion evaluations/recal_cam1_odturns.json --minutes 30` → ~21.8/30.7), then
step 1 (re-derive bank from BoT-SORT events).
