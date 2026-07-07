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
py start_server.py
# Runs on http://127.0.0.1:5000 — do NOT use port 8000 or any other port
# Optional desktop window wrapper: python run.pyw (requires pywebview)

## Testing
python -m pytest backend/tests/ -v

## Git
git commit -m "Step X.X — [title]"

## Screenshots
Ad-hoc UI screenshots (manual captures, before/after evidence) go in `screenshots/` at the
repo root — keep one place, no loose PNGs at the project root. When using the Playwright MCP
`browser_take_screenshot` tool, pass `filename` as an absolute path under `screenshots/` so
captures land there instead of the MCP's working directory. `.playwright-mcp/` (auto-generated
console/page traces) is gitignored — do not commit it.
