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
THE FRACTURE RULE FRACTURE_DEDUP default ON (2026-09-12, operator ruling after arm d17)
(fleet 77.97 after the fracture rule on 2026-09-12; 76.97 after G-BAR-1 on 09-11; 77.08 before it; 75.86 after the heading rulings; 75.70 on 09-10). Env vars are overrides for experiments
(X=0 turns a rule off); nothing in production needs them set. Older plan docs' "operating
notes" that require env flags are superseded. To improve the default: change it, run all
12 windows (scripts/fleet_flags.py, FLEET_WORKERS parallel), compare to 77.97, ship on a
fleet PASS (docs/plan_default_2026-09-10.md). The four windows shipped by hand on 09-09
and the fleet reprocess on 09-10 are the last per-window applies. cam4 1600 stands at 70.2
by ruling: its old 75.4 was ~366 duplicate NB throughs cancelling an equal far-field detection
deficit that is not in the dump (instrument-limited), so a future drop there is read against
70.2, not 75.4.

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
# 1200 passing as of 2026-09-10

## Git
git commit -m "Step X.X — [title]"

## Screenshots
Ad-hoc UI screenshots (manual captures, before/after evidence) go in `screenshots/` at the
repo root — keep one place, no loose PNGs at the project root. When using the Playwright MCP
`browser_take_screenshot` tool, pass `filename` as an absolute path under `screenshots/` so
captures land there instead of the MCP's working directory. `.playwright-mcp/` (auto-generated
console/page traces) is gitignored — do not commit it.
