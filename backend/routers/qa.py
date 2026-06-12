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

from backend.config import PROJECTS_DIR
from backend.database import get_connection, get_intersection
from backend.services.conservation_qa import corridor_consistency, reverse_balance

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
