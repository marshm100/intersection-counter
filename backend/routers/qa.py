"""Conservation-QA endpoints (Phase 3 — zero-ground-truth validation).

GET /projects/{pid}/intersections/{iid}/qa/conservation
    Reverse-movement balance for one intersection (informational at short
    windows — directional peaking is real traffic, not error).

GET /projects/{pid}/qa/corridor?order=3,2,5&axis=NS
    Flow conservation between adjacent intersections. `order` is the
    geographic sequence of intersection_ids (first = southernmost for NS /
    westernmost for EW); defaults to the project's intersections by
    sort_order. This is the PRIMARY new-site check: it compares the same
    vehicle stream measured at two intersections minutes apart, so it is
    valid at any window length.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import PROJECTS_DIR
from backend.database import get_camera, get_connection, get_intersection
from backend.services.conservation_qa import corridor_consistency, reverse_balance
from backend.services.spot_check import (
    acceptance, compare_spot_count, list_spot_counts, propose_window,
    propose_windows, save_spot_count,
)

router = APIRouter()


def _require_project(project_id: str) -> None:
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists() or not (project_dir / "project.db").exists():
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/projects/{project_id}/intersections/{intersection_id}/qa/conservation")
def get_conservation_qa(project_id: str, intersection_id: int):
    _require_project(project_id)
    if get_intersection(project_id, intersection_id) is None:
        raise HTTPException(status_code=404,
            detail=f"intersection {intersection_id} not found")
    return reverse_balance(project_id, intersection_id)


@router.get("/projects/{project_id}/qa/corridor")
def get_corridor_qa(project_id: str, order: str | None = None, axis: str = "NS"):
    _require_project(project_id)
    if axis.upper() not in ("NS", "EW"):
        raise HTTPException(status_code=422, detail="axis must be NS or EW")
    if order:
        try:
            ids = [int(x) for x in order.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=422,
                detail="order must be comma-separated intersection ids")
    else:
        conn = get_connection(project_id)
        try:
            ids = [r[0] for r in conn.execute(
                "SELECT intersection_id FROM intersections "
                "ORDER BY sort_order, intersection_id").fetchall()]
        finally:
            conn.close()
    if len(ids) < 2:
        return {"check": "corridor_consistency", "axis": axis.upper(),
                "order": ids, "links": [],
                "note": "needs at least two intersections"}
    conn = get_connection(project_id)
    try:
        known = {r[0] for r in conn.execute(
            "SELECT intersection_id FROM intersections").fetchall()}
    finally:
        conn.close()
    bad = [i for i in ids if i not in known]
    if bad:
        raise HTTPException(status_code=422,
            detail=f"unknown intersection ids in order: {bad}")
    return corridor_consistency(project_id, ids, axis=axis.upper())


# ---------------------------------------------------------------------------
# Spot counts + acceptance gate (Phase 4)
# ---------------------------------------------------------------------------


class SpotCountBody(BaseModel):
    start_seconds: float
    duration_seconds: float
    manual_counts: dict[str, int]    # {"N through": 123, "E left": 4, ...}
    notes: str = ""


def _require_camera(project_id: str, camera_id: int) -> None:
    if get_camera(project_id, camera_id) is None:
        raise HTTPException(status_code=404,
            detail=f"camera {camera_id} not found")


@router.get("/projects/{project_id}/cameras/{camera_id}/qa/spot-window")
def get_spot_window(project_id: str, camera_id: int, minutes: float = 10.0):
    """Propose a single random spot-count window (legacy — use spot-windows)."""
    _require_project(project_id)
    _require_camera(project_id, camera_id)
    if not (1 <= minutes <= 120):
        raise HTTPException(status_code=422, detail="minutes must be in [1, 120]")
    return propose_window(project_id, camera_id, minutes)


@router.get("/projects/{project_id}/cameras/{camera_id}/qa/spot-windows")
def get_spot_windows(project_id: str, camera_id: int, minutes: float = 10.0):
    """Propose STRATIFIED spot-count windows — one per processed segment (trim /
    time-of-day block) so the sample covers the run's hardest conditions, not just
    an easy window (MASTER_PLAN §5). The acceptance gate requires a spot count in
    each segment before it certifies 'pass'."""
    _require_project(project_id)
    _require_camera(project_id, camera_id)
    if not (1 <= minutes <= 120):
        raise HTTPException(status_code=422, detail="minutes must be in [1, 120]")
    return propose_windows(project_id, camera_id, minutes)


@router.get("/projects/{project_id}/cameras/{camera_id}/qa/spot-counts")
def get_spot_counts(project_id: str, camera_id: int):
    """All recorded spot counts for this camera, newest first, each with its
    live comparison report (system counts re-queried, so a re-review of events
    updates the verdicts)."""
    _require_project(project_id)
    _require_camera(project_id, camera_id)
    spots = list_spot_counts(project_id, camera_id)
    for s in spots:
        s["report"] = compare_spot_count(
            project_id, camera_id, s["start_seconds"], s["duration_seconds"],
            s["manual_counts"])
    return {"spot_counts": spots}


@router.post("/projects/{project_id}/cameras/{camera_id}/qa/spot-counts")
def post_spot_count(project_id: str, camera_id: int, body: SpotCountBody):
    """Record a manual spot count; returns the manual-vs-system report."""
    _require_project(project_id)
    _require_camera(project_id, camera_id)
    if body.duration_seconds <= 0:
        raise HTTPException(status_code=422, detail="duration must be positive")
    if any(v < 0 for v in body.manual_counts.values()):
        raise HTTPException(status_code=422, detail="counts must be >= 0")
    return save_spot_count(project_id, camera_id, body.start_seconds,
                           body.duration_seconds, body.manual_counts, body.notes)


@router.get("/projects/{project_id}/intersections/{intersection_id}/qa/acceptance")
def get_acceptance(project_id: str, intersection_id: int):
    """The Phase-4 gate: conservation + spot-count status -> ship/review/fail."""
    _require_project(project_id)
    if get_intersection(project_id, intersection_id) is None:
        raise HTTPException(status_code=404,
            detail=f"intersection {intersection_id} not found")
    return acceptance(project_id, intersection_id)
