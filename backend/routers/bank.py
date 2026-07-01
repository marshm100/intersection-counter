"""GT-free path-bank build endpoints (Phase 2a — MASTER_PLAN §3-A).

Wires the CLI bank builder into the app so an operator builds a bank without the
CLI. Build runs as a background job; the operator polls status, reviews the QA
report, then applies (Phase 2b) — a guided flow with a human QA checkpoint, never
an auto-chain.

POST /projects/{pid}/cameras/{cid}/bank/build    kick off a background build
GET  /projects/{pid}/cameras/{cid}/bank/status   poll state + QA on completion
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import PROJECTS_DIR
from backend.database import get_connection
from backend.services.bank_builder import get_build_status, start_build

router = APIRouter()


def _require_camera(project_id: str, camera_id: int) -> None:
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists() or not (project_dir / "project.db").exists():
        raise HTTPException(status_code=404, detail="Project not found")
    conn = get_connection(project_id)
    try:
        row = conn.execute(
            "SELECT camera_id FROM cameras WHERE camera_id = ?", (camera_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"camera {camera_id} not found")


class BuildBody(BaseModel):
    start_hms: str = "07:00:00"
    minutes: float = 30.0
    channel_buffer_px: float = 20.0
    variant: str | None = None


@router.post("/projects/{project_id}/cameras/{camera_id}/bank/build")
def post_bank_build(project_id: str, camera_id: int, body: BuildBody | None = None):
    """Start a GT-free bank build for this camera on the given window. Requires a
    detection cache for the window (process a sample window first) — if absent the
    job fails with an operator-actionable message surfaced via /bank/status."""
    _require_camera(project_id, camera_id)
    body = body or BuildBody()
    return start_build(project_id, camera_id, start_hms=body.start_hms,
                       minutes=body.minutes, channel_buffer_px=body.channel_buffer_px,
                       variant=body.variant)


@router.get("/projects/{project_id}/cameras/{camera_id}/bank/status")
def get_bank_status(project_id: str, camera_id: int):
    """Poll the build job: {status: idle|running|complete|error}. On complete,
    includes the QA `summary` (paths, admitted/rejected, missing movements, leg-
    sanity + straight-turn warnings) for the operator's review before applying."""
    _require_camera(project_id, camera_id)
    return get_build_status(project_id, camera_id)
