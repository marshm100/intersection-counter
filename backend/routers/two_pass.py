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


class Pass1Body(BaseModel):
    variant: str
    start_frame: int
    end_frame: int
    backend: str | None = None         # None -> the camera's calib_pass1_backend
    resume: bool = True


class ProcessBody(BaseModel):
    # One entry per camera of the intersection: which dump window to count.
    # (Trim->window derivation is the stage-3.4 ingest generalization; today
    # the operator/driver names the windows, the corridor's study_* pattern.)
    windows: dict[int, str]            # camera_id -> variant
    apply: bool = True


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


def _run_pass1_job(project_id: str, camera_id: int, body: Pass1Body):
    from backend.services.two_pass import run_pass1
    key = (project_id, camera_id)

    def progress(done, total, points):
        with _lock:
            j = _jobs.get(key)
            if j is not None:
                j["progress"] = {"frames": done, "total": total, "points": points}

    try:
        res = run_pass1(project_id, camera_id, variant=body.variant,
                        start_frame=body.start_frame, end_frame=body.end_frame,
                        backend=body.backend, resume=body.resume,
                        progress=progress)
        with _lock:
            _jobs[key] = {"status": "complete", "kind": "pass1", "result": res}
    except Exception as exc:
        logger.exception("pass-1 cam%s failed", camera_id)
        with _lock:
            _jobs[key] = {"status": "error", "kind": "pass1", "error": str(exc)}


@router.post("/projects/{project_id}/cameras/{camera_id}/two-pass/pass1")
def post_pass1(project_id: str, camera_id: int, body: Pass1Body):
    """Run pass 1 (semantics-free raw-track dump) for one camera window.
    Calibration-independent — runnable the moment video + cache exist.
    Recipe from calib_pass1_backend unless overridden; resumable."""
    _require_enabled()
    _require_camera(project_id, camera_id)
    key = (project_id, camera_id)
    with _lock:
        if _jobs.get(key, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="a two-pass job is already running")
        _jobs[key] = {"status": "running", "kind": "pass1", "variant": body.variant}
    threading.Thread(target=_run_pass1_job, args=(project_id, camera_id, body),
                     daemon=True).start()
    return {"status": "running"}


def _run_process_job(project_id: str, intersection_id: int, body: ProcessBody):
    from backend.database import set_v3_run_state
    from backend.services.two_pass import run_pass2
    key = (project_id, f"i{intersection_id}")
    results, failed = [], None
    try:
        set_v3_run_state(project_id, intersection_id, "running")
        workdir = PROJECTS_DIR / project_id / "two_pass"
        for camera_id, variant in body.windows.items():
            with _lock:
                _jobs[key]["current_camera"] = camera_id
            res = run_pass2(project_id, int(camera_id), variant=variant,
                            workdir=workdir, apply=body.apply)
            results.append(res)
        set_v3_run_state(project_id, intersection_id, "complete")
        with _lock:
            _jobs[key] = {"status": "complete", "kind": "process",
                          "results": results}
    except Exception as exc:
        logger.exception("two-pass process i%s failed", intersection_id)
        set_v3_run_state(project_id, intersection_id, "error")
        with _lock:
            _jobs[key] = {"status": "error", "kind": "process", "error": str(exc),
                          "completed": results}


@router.post("/projects/{project_id}/intersections/{intersection_id}/two-pass/process")
def post_two_pass_process(project_id: str, intersection_id: int, body: ProcessBody):
    """The two-pass 'Confirm & process': pass 2 (+ apply + QA rebuild) for each
    named camera window of the intersection, sequentially, with progress via
    v3_run_state — the same status surface the card UI already polls."""
    _require_enabled()
    for camera_id in body.windows:
        if _require_camera(project_id, int(camera_id)) != intersection_id:
            raise HTTPException(status_code=409,
                detail=f"camera {camera_id} is not on intersection {intersection_id}")
    key = (project_id, f"i{intersection_id}")
    with _lock:
        if _jobs.get(key, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="two-pass processing already running")
        _jobs[key] = {"status": "running", "kind": "process"}
    threading.Thread(target=_run_process_job,
                     args=(project_id, intersection_id, body), daemon=True).start()
    return {"status": "running"}


@router.get("/projects/{project_id}/intersections/{intersection_id}/two-pass/status")
def get_two_pass_process_status(project_id: str, intersection_id: int):
    _require_enabled()
    return _jobs.get((project_id, f"i{intersection_id}"), {"status": "idle"})
