"""Two-pass counting endpoints (stage 3, plan_A4_stage3_2026-07-10).

Gated by config.TWO_PASS_ENABLED (default OFF — 404 when disabled, so the
legacy flow is bit-for-bit untouched). Job pattern mirrors the bank router:
one background thread per camera, poll via /two-pass/status.
"""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import PROJECTS_DIR, TWO_PASS_ENABLED
from backend.database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter()

_jobs: dict[tuple, dict] = {}
_lock = threading.Lock()


def _require_enabled():
    if not TWO_PASS_ENABLED:
        raise HTTPException(status_code=404,
            detail="two-pass flow is disabled (config.TWO_PASS_ENABLED)")


def _require_camera(project_id: str, camera_id: int) -> int:
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists() or not (project_dir / "project.db").exists():
        raise HTTPException(status_code=404, detail="Project not found")
    conn = get_connection(project_id)
    try:
        row = conn.execute(
            "SELECT intersection_id FROM cameras WHERE camera_id = ?",
            (camera_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"camera {camera_id} not found")
    return row[0]


class RunBody(BaseModel):
    variant: str                       # pass-1 dump variant, e.g. "study_0700"
    apply: bool = False                # swap into project.db (backup first)


def _run(project_id: str, camera_id: int, variant: str, apply: bool):
    from backend.services.two_pass import run_pass2
    key = (project_id, camera_id)
    workdir = PROJECTS_DIR / project_id / "two_pass"
    try:
        res = run_pass2(project_id, camera_id, variant=variant,
                        workdir=workdir, apply=apply)
        with _lock:
            _jobs[key] = {"status": "complete", "result": res}
    except Exception as exc:
        logger.exception("two-pass cam%s failed", camera_id)
        with _lock:
            _jobs[key] = {"status": "error", "error": str(exc)}


@router.post("/projects/{project_id}/cameras/{camera_id}/two-pass/run")
def post_two_pass_run(project_id: str, camera_id: int, body: RunBody):
    """Run pass 2 for one camera from its pass-1 dump: corpus bank build ->
    replay-classify -> volume-gated turn merge (-> apply + flag rebuild when
    body.apply). Requires a COMPLETE pass-1 dump for the variant."""
    _require_enabled()
    _require_camera(project_id, camera_id)
    key = (project_id, camera_id)
    with _lock:
        if _jobs.get(key, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="two-pass already running")
        _jobs[key] = {"status": "running", "variant": body.variant,
                      "apply": body.apply}
    threading.Thread(target=_run, args=(project_id, camera_id, body.variant,
                                        body.apply), daemon=True).start()
    return {"status": "running"}


@router.get("/projects/{project_id}/cameras/{camera_id}/two-pass/status")
def get_two_pass_status(project_id: str, camera_id: int):
    _require_enabled()
    _require_camera(project_id, camera_id)
    return _jobs.get((project_id, camera_id), {"status": "idle"})
