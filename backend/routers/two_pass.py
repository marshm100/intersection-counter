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
    # Explicit camera_id -> variant map (the stage-3.3 dev/driver form), or
    # None -> derive the windows from the card's trims (stage 3.4: the
    # operator surface — variant/frames come from the trim→window contract,
    # and missing dumps are produced first, detect-at-ingest included).
    windows: dict[int, str] | None = None
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
    from backend.services.pass2_replay import JobCancelled
    from backend.services.two_pass import (
        plan_intersection, rebuild_s5_union, run_pass1, run_pass2,
    )
    key = (project_id, f"i{intersection_id}")
    workdir = PROJECTS_DIR / project_id / "two_pass"
    results = []

    def should_cancel() -> bool:
        # Lock-free read of a bool under the GIL — this runs inside the hot
        # pass-1/replay frame loops.
        return bool(_jobs.get(key, {}).get("cancel_requested"))

    def _s5_union_if_needed():
        # One rebuild with ALL applied windows' S5 rows (plan_C_polish §B).
        # Single-window runs keep the per-window rebuild's identical result.
        # APPLIED only: a window the apply gate stood down on keeps its
        # incumbent's flags — its working DB's S5 rows must not leak in
        # (plan_v2_apply_gate_2026-08-07).
        applied = [r for r in results if r.get("applied")]
        if body.apply and len(applied) > 1:
            with _lock:
                j = _jobs.get(key)
                if j is not None:
                    j["stage"] = "s5-union"
            rebuild_s5_union(project_id, intersection_id, applied)

    try:
        set_v3_run_state(project_id, intersection_id, "running")
        if body.windows:
            # Explicit windows (dev form): dumps must already exist —
            # run_pass2 errors actionably when they don't.
            work: list[dict] = [{"camera_id": int(c), "variant": v}
                                for c, v in body.windows.items()]
        else:
            work = plan_intersection(project_id, intersection_id, workdir)
            if not work:
                raise ValueError("nothing to process — the card needs trims "
                                 "and at least one camera with video")
        for idx, item in enumerate(work):
            if should_cancel():
                raise JobCancelled("cancelled between windows")
            camera_id, variant = item["camera_id"], item["variant"]
            with _lock:
                _jobs[key].update(current_camera=camera_id,
                                  current_variant=variant, stage=None,
                                  window_index=idx + 1, window_total=len(work))
            dump = (item.get("dump") or {}).get("status")
            if dump == "mismatch":
                raise ValueError(
                    f"camera {camera_id} {variant}: the existing dump does not "
                    f"cover the trim window {item['start_frame']}–"
                    f"{item['end_frame']} — delete the dump or fix the trim")
            if dump in ("missing", "partial"):
                # Pass 1 first (detect-at-ingest when the cache is missing
                # too); partial dumps resume with the seam warm-up.
                with _lock:
                    _jobs[key]["stage"] = "pass1"

                def _prog(done, total, points, _c=camera_id, _v=variant):
                    with _lock:
                        j = _jobs.get(key)
                        if j is not None:
                            j["progress"] = {"camera": _c, "variant": _v,
                                             "frames": done, "total": total,
                                             "points": points}

                run_pass1(project_id, camera_id, variant=variant,
                          start_frame=item["start_frame"],
                          end_frame=item["end_frame"],
                          resume=True, progress=_prog,
                          should_cancel=should_cancel)
            if should_cancel():
                raise JobCancelled("cancelled between stages")
            with _lock:
                _jobs[key]["stage"] = "pass2"
            res = run_pass2(project_id, camera_id, variant=variant,
                            workdir=workdir, apply=body.apply,
                            should_cancel=should_cancel)
            results.append(res)
        _s5_union_if_needed()
        set_v3_run_state(project_id, intersection_id, "complete")
        with _lock:
            _jobs[key] = {"status": "complete", "kind": "process",
                          "results": results}
    except JobCancelled as exc:
        logger.info("two-pass process i%s cancelled: %s", intersection_id, exc)
        # Applied windows stay applied (each apply was atomic with its own
        # backup); keep their S5 rows coherent before parking the job.
        try:
            _s5_union_if_needed()
        except Exception:
            logger.exception("s5 union after cancel failed (queue keeps the "
                             "last per-window rebuild)")
        set_v3_run_state(project_id, intersection_id, "cancelled")
        with _lock:
            prior = _jobs.get(key, {})
            _jobs[key] = {"status": "cancelled", "kind": "process",
                          "detail": str(exc), "completed": results,
                          "completed_windows": len(results),
                          "window_index": prior.get("window_index"),
                          "window_total": prior.get("window_total")}
    except Exception as exc:
        logger.exception("two-pass process i%s failed", intersection_id)
        set_v3_run_state(project_id, intersection_id, "error", str(exc))
        with _lock:
            _jobs[key] = {"status": "error", "kind": "process", "error": str(exc),
                          "completed": results}


@router.post("/projects/{project_id}/intersections/{intersection_id}/two-pass/process")
def post_two_pass_process(project_id: str, intersection_id: int, body: ProcessBody):
    """The two-pass 'Confirm & process': for each camera window (named, or
    derived from the card's trims when body.windows is absent) ensure the
    pass-1 dump exists (detect-at-ingest for cache-less footage), then pass 2
    (+ apply + QA rebuild), sequentially, with progress via v3_run_state —
    the same status surface the card UI already polls."""
    _require_enabled()
    for camera_id in (body.windows or {}):
        if _require_camera(project_id, int(camera_id)) != intersection_id:
            raise HTTPException(status_code=409,
                detail=f"camera {camera_id} is not on intersection {intersection_id}")
    if body.windows is None:
        _require_intersection(project_id, intersection_id)
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


@router.post("/projects/{project_id}/intersections/{intersection_id}/two-pass/cancel")
def post_two_pass_cancel(project_id: str, intersection_id: int):
    """Request cancellation of the intersection's running two-pass process
    job. Coarse by design: the job stops at its next checkpoint (between
    windows/stages, or inside a pass-1/replay frame loop) — the corpus-bank
    build and the apply step always run to completion, so already-applied
    windows stay applied and everything on disk stays resumable."""
    _require_enabled()
    key = (project_id, f"i{intersection_id}")
    with _lock:
        j = _jobs.get(key)
        if j is None or j.get("status") != "running":
            raise HTTPException(status_code=409,
                                detail="no running two-pass job to cancel")
        j["cancel_requested"] = True
    return {"status": "cancelling",
            "detail": "stopping at the next checkpoint (current step finishes)"}


# Whitelist for the processing-status merge: the chip needs live progress,
# not the full per-window results payload.
_JOB_PUBLIC_KEYS = ("status", "kind", "stage", "current_camera",
                    "current_variant", "window_index", "window_total",
                    "completed_windows", "progress", "error", "detail",
                    "cancel_requested")


def get_process_job(project_id: str, intersection_id: int) -> dict | None:
    """Read-only snapshot of the intersection's two-pass process job for the
    legacy /processing/status merge (the chip's live subline). None when no
    job entry exists."""
    with _lock:
        j = _jobs.get((project_id, f"i{intersection_id}"))
        if j is None:
            return None
        return {k: j[k] for k in _JOB_PUBLIC_KEYS if k in j}


def _require_intersection(project_id: str, intersection_id: int) -> None:
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists() or not (project_dir / "project.db").exists():
        raise HTTPException(status_code=404, detail="Project not found")
    conn = get_connection(project_id)
    try:
        row = conn.execute(
            "SELECT intersection_id FROM intersections WHERE intersection_id = ?",
            (intersection_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404,
                            detail=f"intersection {intersection_id} not found")


@router.get("/projects/{project_id}/intersections/{intersection_id}/two-pass/plan")
def get_two_pass_plan(project_id: str, intersection_id: int):
    """The card's two-pass readiness view (stage 3.4): each derived window
    (trim→window contract) + cache/dump/pass-2 status. 404 when the flag is
    off — the frontend uses that as its feature probe and falls back to the
    legacy flow untouched."""
    _require_enabled()
    _require_intersection(project_id, intersection_id)
    from backend.services.two_pass import plan_intersection
    workdir = PROJECTS_DIR / project_id / "two_pass"
    return {"windows": plan_intersection(project_id, intersection_id, workdir)}
