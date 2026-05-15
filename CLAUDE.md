# Intersection Counter — Standing Instructions

## Project
Localhost web app: traffic video → AI detection/tracking → trajectory-based turn classification → Excel TMC output.
Replaces commercial tools (GoodVision, Miovision). Internal tool for traffic engineers.
Runs locally on the engineer's machine. No cloud, no auth, no internet required after install.

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
- Turn classification: Trajectory shape analysis. NO exit zones. NO turn matrix.
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
