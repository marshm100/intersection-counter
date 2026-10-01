# Intersection Counter — Standing Instructions

## Project
Localhost web app: traffic video → AI detection/tracking → trajectory-based turn classification → Excel TMC output.
Replaces commercial tools (GoodVision, Miovision). Internal tool for traffic engineers.
Runs locally on the engineer's machine. No cloud, no auth, no internet required after install.

## Prime directive (2026-07-07)
Accuracy is the top priority — whatever it takes to match Miovision on a real study. The method must
work from the RAW VIDEO + operator calibration ALONE: no ground truth, no benchmark data, exactly as
a brand-new site is deployed. Miovision/manual counts are DEV-validation yardsticks only, never a
runtime dependency. Do not overfit to the Sunnyvale corridor's known answers.

## The default (2026-09-10)
Cams 1-5 are TEST FOOTAGE. The deliverable is what the software does UNAIDED on a blank
intersection. The unit of shipping is a DEFAULT: one configuration, all 12 corridor windows,
scored as a fleet against the all-off baseline (69.43) — never a per-window winner.
G-DEF-1 PASS: GATE_GROUND_ANCHOR, STRAIGHT_FRAGMENT_RULE, GATE_EVIDENCE_EITHER_CORNER and
JOURNEY_STATE_MACHINE default ON; G-DEF-4 PASS: STRAIGHT_FRAGMENT_INCLUDE_PATH_FITS default ON;
THE FRACTURE RULE FRACTURE_DEDUP default ON (2026-09-12, operator ruling after arm d17);
G-EX-2 GATE_EXIT_ONLY_BINDING + BOUND_CHAIN_CONSERVE default ON (2026-09-24, operator go
after arm gx2: "ship it"); THE GLOBAL TRACKLET LINKER TRACKLET_LINKER + TRACKLET_LINKER_EXCLUSIVE
default ON, moving levels only (LINKER_STOPPED_LEVEL off — it broke cam3) (2026-09-30, operator go
after arm lk2; it replaces the fracture rule, the bound-chain guard, the continuation rule and
the turn merge on the linked path); THE NO-CROSSING SIDE DOOR CLOSED NOCROSS_NO_FALLBACK default ON
(2026-10-01, operator go after arm nf1b: a track that crosses no gate and matches no path shape is
dropped, not given the nearest line's movement); THE THEFT SPLIT THEFT_SPLIT default ON (2026-10-01,
operator go after arm ts1: the linker first cuts a track that follows a car away, slows at a small box
and comes back with an oncoming car; labels 433 -> 438 of 512 with none worse; missed the camera clause
on cam1 -2.10 and shipped by ruling, as gx2 was); THE FULL-JOURNEY RESCUE FULL_JOURNEY_RESCUE default ON
(2026-10-01, operator go after arm fr3: a track witnessed entering one gate and leaving another is counted
instead of dropped by the u-turn branch; labels 438 -> 444 with none worse, approach +5.8; cam2 16:00 -3.7
missed the window clause on its far-band W line, shipped by ruling). THIRTEEN rules.
(fleet 88.84 / approach 82.03 after fr3 on 2026-10-01; 87.01 after ts1 on 2026-10-01; 86.87 after nf1b on 2026-10-01, approach 74.29; journey labels 521 vehicles, phantoms 47 -> 25,
real cars unchanged. Fleet 82.68 after the linker on 2026-09-30 — against the HONEST control 80.81, every camera on
the default tracker; the 83.50 below had cams 1-3 on one-off BoT-SORT recipes, which the
one-default ruling of 2026-09-29 retired: "we ship one default to all intersections and if it
cant handle it we need to make the default better". Fleet 83.50 after G-EX-2 + the guard on 2026-09-24; 77.97 after the fracture rule on
2026-09-12; 76.97 after G-BAR-1 on 09-11; 77.08 before it; 75.86 after the heading rulings;
75.70 on 09-10). Env vars are overrides for experiments
(X=0 turns a rule off); nothing in production needs them set.
NOTE on the gx2 ship: it MISSED the G-DEF-1 letter by 0.20 on one clause (cam1's camera mean
-1.20 against the -1.0 bar) and was shipped by operator ruling anyway — fleet +4.12, cam4
+15.20, no window worse than -1.3 against the -3.0 bar, FM 51 unchanged. The letter's camera
clause was written to stop a default that RUINS a window; that is not this. Do not treat the
miss as precedent for arguing a letter down without a ruling. Older plan docs' "operating
notes" that require env flags are superseded. To improve the default: change it, run all
12 windows (scripts/fleet_flags.py, FLEET_WORKERS parallel), compare to 88.84, ship on a
fleet PASS (docs/plan_default_2026-09-10.md). The four windows shipped by hand on 09-09
and the fleet reprocess on 09-10 are the last per-window applies. (cam4 1600's 70.2-by-ruling
note is SUPERSEDED: the recovery tracker plus G-EX-2 took that window to 84.9, and the
far-field NB deficit the ruling was about is what the observed-exit binding recovered.)

## The tracker (2026-09-12, operator: "improving the engineering of the tracker")
The default recipe's tracker (cam4, cam5, every blank site) is now the recovery tracker:
supervision ByteTrack forked in backend/services/tracker.py with position recovery,
confirmation by position, motion-state reset (motion kept), edge exit, >0.8 double-box
dedup, a stacked-box guard, a HELD-BOX GUARD on recovery (2026-09-15: a recovery may not take
a box that overlaps >= 0.6 a box another id took this frame; thefts 107/221/23 -> 83/196/18,
one-track and breaks better on all three sites), a KALMAN VELOCITY NOISE of 1/20 of the box
height per frame instead of the library's 1/160 (2026-09-19, from the miss log: the filter
followed a vehicle's growing pixel speed at a fifth to a half; one-track 4241/3738/1168 ->
4422/3952/1249, breaks 2918/4057/766 -> 2547/3637/624, thefts down too), and weak-box births
by inheritance (a car's weak early boxes
become its track's back-filled start; pass 1 merges them from a backfill.npy sidecar)
(docs/plan_basis_2026-09-11.md "Tracker engineering", "Phase A"). It is judged by
the tracking evidence — one track per vehicle against the detection chains
(scripts/research_tracker_break.py) — not by switching it on and off against fleet scores.
PRODUCTION DUMPS: cam4 and cam5's study_* dumps ARE the recovery tracker since 2026-09-24
(the vl3 dumps promoted at the gx2 ship; the old library-tracker basis is renamed aside as
pre_gx2_study_*). Since 2026-09-30 cams 1-3 are on it too: their per-camera tracker knobs were
cleared and the default-tracker rt_study_* dumps promoted to study_* (old basis renamed aside as
pre_lk2_study_*). cam3 still carries two one-off COUNTING knobs (track_quality_filter, dtw_mean)
to be tested out under the one-default ruling. Any pass-1 run uses the recovery tracker.

## Calibrating a blank site (operator ruling 2026-09-11, docs/plan_blank_site_2026-09-11.md)
Draw each gate LINE where vehicles are reliably TRACKED, inside the physical mouth — never at
the far mouth where boxes are first born. Use scripts/viz_track_density.py (heat of tracked
positions, births cyan, deaths orange, the lines) to see where that is. Aim each arrow along the
THROUGH direction of travel entering that approach, judged on moving video. The evidence channel
activates at coverage 0.20 (EVIDENCE_ACTIVATION_COVERAGE, G-BAR-1); a site drawn at its physical
mouths sits at ~0.1 and every counting default is then inert. Measured on FM 51 (held-out): lines
at the mouths 87.5 / 67.8; lines where the tracks are + channel on 91.9 / 79.3.

## Data model (v3)
Project → Intersection-Day (one card per intersection × date) → Camera (1+ per card) → Clip/Video (1+ per camera).
Legs are per-camera (each camera sees the intersection from its own angle). Trims are wall-clock processing
windows scoped to an intersection-day. Cross-camera dedup collapses parallel-overlap duplicates.
See docs/Implementation_Plan_v3.md.

## Instruments (read before building a new one)
- EVENT AUDIT (2026-10-01): /static/audit.html. The reverse of the journey labels: a stratified
  sample of COUNTED events (scripts/audit_sample.py BATCH [STEM]; strata = gate tag x posterior
  source), each judged on the video - correct / wrong movement / not a vehicle in the
  intersection / double / unsure (tables audit_items, audit_answers; backend/services/
  event_audit.py). scripts/audit_report.py BATCH = precision per decision path per camera: which
  rules misfire, and how. Dev-validation only.
- JOURNEY LABELS (2026-09-30): frontend/journeys.html (operator clicks each vehicle's way in and
  out, at the BACK TYRE crossing), tables journey_clips / journey_labels, scored by
  scripts/eval_journeys.py STEM[:prefixes] [STEM2] (backend/services/journey_eval.py: one-to-one
  click-to-track assignment, per-vehicle correct / wrong / double / missed / no_track, phantoms,
  McNemar). 5 clips, 521 complete journeys, one 3-min clip per camera. DEV-validation only. Judge
  arms car by car here as well as on the fleet: 5/95 totals let errors cancel (arm d2 failed the
  fleet yet won cam1 per vehicle).
- `track_fates` (backend/database.py, config TRACK_FATE_LEDGER, default ON) — THE JOURNEY
  FATE LEDGER: one row per finalized track, counted or dropped, with reason, place and time,
  written at all six silent-return sites in pipeline._finalize_vehicle_data plus the counted
  path. Diagnostics only. It is the counting analogue of the tracker's miss log and it is how
  the gx1 failure was diagnosed in one query with no dump re-read.

## Docs
- docs/PRD_v2.md — Requirements and business rules
- docs/Implementation_Plan_v2.md — Earlier multi-video plan (v2)
- docs/Implementation_Plan_v3.md — Current plan (multi-intersection, multi-camera, multi-trim)
- docs/TDD.md — Architecture, data flow, concurrency design

## Hard Constraints
- Frontend: Vanilla HTML/CSS/JS. NO React, NO npm, NO build tools.
- Database: Raw sqlite3. NO ORM.
- Turn classification: full-frame tracking → clip each track to the operator-defined intersection
  box (perimeter = the leg mouths) → origin = the box side crossed entering, destination = the side
  crossed exiting, with the in-box shape matched to operator channels. (Revised 2026-07-07: this
  SUPERSEDES the earlier "Trajectory shape analysis. NO exit zones. NO turn matrix." rule — the box
  sides ARE origin/destination gates, intentionally. Rationale: far-field cars are detected late, so
  tracks truncated past the divergence made collinear-exit movements unrecoverable by shape alone;
  full-frame tracking + box-clip fixes it. The gates are operator-DRAWN geometry, not a hardcoded
  matrix, and need NO benchmark data.)
- Excel: Hard-coded integers. NO formulas.
- Processing: NEVER stop for single-frame errors.
- Python 3.11+ with type hints.
- Pedestrians OUT of scope for v2.

## Running
serve.bat
# or: .venv\Scripts\python.exe start_server.py
# Runs on http://127.0.0.1:5000 — do NOT use port 8000 or any other port
# Optional desktop window wrapper: python run.pyw (requires pywebview)

## Environment (machine transition 2026-08-22)
This project runs on **Python 3.12** and lives in a venv at `.venv`.
Do NOT use bare `py` / `python` — on this machine that is 3.12's successor 3.13,
which has no project dependencies and no wheels for the pinned numpy/scipy.
Rebuild with:
    %LOCALAPPDATA%\Programs\Python\Python312\python.exe -m venv .venv
    .venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
    .venv\Scripts\python.exe -m pip install -r requirements.txt
CUDA is required for practical run times (RTX 3500 Ada, 12 GB, cu124 verified).

WARNING — the environment is NOT part of the measurement basis and never has
been. requirements.txt pins numpy/scipy but leaves torch undeclared and
ultralytics at >=8.3, and no run artifact records the versions that produced it.
The controls scored before 2026-08-22 came from an environment that cannot be
reconstructed. Re-score one archived control on any new machine BEFORE trusting
a ctrl/arm comparison against it.

## Testing
.venv\Scripts\python.exe -m pytest backend/tests/ -q
# 1396 passing as of 2026-10-01

## Git
git commit -m "Step X.X — [title]"

## Screenshots
Ad-hoc UI screenshots (manual captures, before/after evidence) go in `screenshots/` at the
repo root — keep one place, no loose PNGs at the project root. When using the Playwright MCP
`browser_take_screenshot` tool, pass `filename` as an absolute path under `screenshots/` so
captures land there instead of the MCP's working directory. `.playwright-mcp/` (auto-generated
console/page traces) is gitignored — do not commit it.
