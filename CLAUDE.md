# Intersection Counter — Standing Instructions

## Project
Localhost web app: traffic video → AI detection/tracking → trajectory-based turn classification → Excel TMC output.
Replaces commercial tools (GoodVision, Miovision). Internal tool for traffic engineers.
Runs locally on the engineer's machine. No cloud, no auth, no internet required after install.

## Docs
- docs/PRD_v2.md — Requirements and business rules
- docs/Implementation_Plan_v2.md — Step-by-step build order with function signatures
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
