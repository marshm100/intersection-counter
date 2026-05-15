"""v3 intersection-card API.

CRUD on the three v3 grouping entities (intersections, cameras at an
intersection, trims at an intersection), plus a coverage-report endpoint
the frontend trim editor uses to show which sub-intervals are covered by
which cameras and where the gaps are.

Calibration is camera-scoped in v3, but the existing calibration router
still exposes its own per-project surface (for legacy single-intersection
projects). Camera-scoped calibration endpoints live in routers/calibration.py.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import PROJECTS_DIR
from backend.database import (
    add_trim, get_camera, get_connection, get_intersection,
    list_cameras, list_intersections, list_trims, list_videos_for_camera,
    remove_camera, remove_intersection, remove_trim,
    update_camera, update_intersection, update_trim,
)
from backend.services.coverage import (
    CameraCoverage, Interval, compute_coverage_report,
    wallclock_to_datetime,
)
from backend.services.v3_orchestrator import plan_intersection_day

router = APIRouter()


# Module-level state for in-flight intersection-day processing.
# Keyed by (project_id, intersection_id). Cleared on completion or cancel.
import asyncio
import queue
import threading
import time

_v3_jobs: dict[tuple[str, int], dict] = {}
_v3_jobs_lock = threading.Lock()

# Live preview state — mirrors the v2 pattern in routers/processing.py but
# scoped per (project, intersection) so multiple intersections can run.
_v3_preview_frames: dict[tuple[str, int], bytes] = {}
_v3_preview_queues: dict[tuple[str, int], queue.Queue] = {}
_v3_preview_workers: dict[tuple[str, int], threading.Thread] = {}
_v3_preview_lock = threading.Lock()


def _v3_preview_worker(key: tuple[str, int], q: queue.Queue) -> None:
    """Drain the queue, render the latest frame, stash the JPEG.
    Sentinel `None` ends the worker. Mirrors v2's _preview_worker."""
    from backend.services.frame_annotator import render_frame_preview
    import cv2

    while True:
        item = q.get()
        if item is None:
            break
        # Coalesce: keep only the most recent item so we never lag behind.
        while True:
            try:
                newer = q.get_nowait()
                if newer is None:
                    item = None
                    break
                item = newer
            except queue.Empty:
                break
        if item is None:
            break
        raw_frame, tracks, origin_zones, legs, active_traj, finalized_traj = item
        try:
            jpeg = render_frame_preview(
                raw_frame, tracks, origin_zones, legs,
                active_trajectories=active_traj,
                finalized_trajectories=finalized_traj,
            )
        except Exception as e:
            logger.warning("v3 preview annotation error: %s", e)
            try:
                _, buf = cv2.imencode(".jpg", raw_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                jpeg = buf.tobytes()
            except Exception:
                continue
        with _v3_preview_lock:
            _v3_preview_frames[key] = jpeg


def _ensure_v3_preview_worker(key: tuple[str, int]) -> queue.Queue:
    """Lazily start the preview worker for this intersection."""
    with _v3_preview_lock:
        q = _v3_preview_queues.get(key)
        if q is not None and _v3_preview_workers.get(key) and _v3_preview_workers[key].is_alive():
            return q
        q = queue.Queue(maxsize=2)
        _v3_preview_queues[key] = q
        t = threading.Thread(target=_v3_preview_worker, args=(key, q), daemon=True)
        _v3_preview_workers[key] = t
        t.start()
        return q


def _stop_v3_preview_worker(key: tuple[str, int]) -> None:
    with _v3_preview_lock:
        q = _v3_preview_queues.pop(key, None)
        _v3_preview_workers.pop(key, None)
    if q is not None:
        try:
            q.put_nowait(None)
        except queue.Full:
            pass


import logging
logger = logging.getLogger(__name__)


# --- Request models --------------------------------------------------------

class UpdateIntersectionBody(BaseModel):
    name: Optional[str] = None
    leg_count: Optional[int] = None
    sort_order: Optional[int] = None


class UpdateCameraBody(BaseModel):
    label: Optional[str] = None
    sort_order: Optional[int] = None


class TrimBody(BaseModel):
    start_wallclock: str
    end_wallclock: str


class UpdateTrimBody(BaseModel):
    start_wallclock: Optional[str] = None
    end_wallclock: Optional[str] = None
    sort_order: Optional[int] = None


# --- Helpers ---------------------------------------------------------------

def _require_project(project_id: str) -> None:
    project_dir = PROJECTS_DIR / project_id
    db_path = project_dir / "project.db"
    if not project_dir.exists() or not db_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")


def _require_intersection(project_id: str, intersection_id: int) -> dict:
    iid_row = get_intersection(project_id, intersection_id)
    if iid_row is None:
        raise HTTPException(status_code=404, detail="Intersection not found")
    return iid_row


def _require_camera(project_id: str, camera_id: int) -> dict:
    cam = get_camera(project_id, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


def _camera_coverages(project_id: str, intersection: dict) -> list[CameraCoverage]:
    """Build the list of CameraCoverage objects for an intersection-day.

    Each camera's wall-clock intervals come from its videos' recording start
    datetime + duration. Videos that don't carry a parseable start datetime
    are skipped (a v2-shaped legacy project may have some of these).
    """
    coverages: list[CameraCoverage] = []
    cams = list_cameras(project_id, intersection["intersection_id"])
    for c in cams:
        videos = list_videos_for_camera(project_id, c["camera_id"])
        ivs: list[Interval] = []
        for v in videos:
            start_str = v.get("recording_start_datetime") or v.get("recording_start_time")
            if not start_str:
                continue
            try:
                start = datetime.fromisoformat(start_str)
            except ValueError:
                continue
            dur = float(v.get("duration_seconds") or 0)
            if dur <= 0:
                continue
            ivs.append(Interval(start, start + timedelta(seconds=dur)))
        if ivs:
            coverages.append(CameraCoverage(camera_id=c["camera_id"], intervals=ivs))
    return coverages


def _trim_to_interval(date_str: str, trim: dict) -> Interval:
    return Interval(
        wallclock_to_datetime(date_str, trim["start_wallclock"]),
        wallclock_to_datetime(date_str, trim["end_wallclock"]),
    )


# --- Intersections ---------------------------------------------------------

@router.get("/projects/{project_id}/intersections")
def get_intersections(project_id: str):
    """List all intersection-day cards in the project."""
    _require_project(project_id)
    return list_intersections(project_id)


@router.get("/projects/{project_id}/intersections/{intersection_id}")
def get_one_intersection(project_id: str, intersection_id: int):
    """Detail for a single intersection-day: itself + cameras + trims."""
    _require_project(project_id)
    iid_row = _require_intersection(project_id, intersection_id)
    cams = list_cameras(project_id, intersection_id)
    # Attach each camera's video count for a quick UI summary
    for c in cams:
        c["videos"] = list_videos_for_camera(project_id, c["camera_id"])
    trims = list_trims(project_id, intersection_id)
    return {"intersection": iid_row, "cameras": cams, "trims": trims}


@router.patch("/projects/{project_id}/intersections/{intersection_id}")
def patch_intersection(
    project_id: str, intersection_id: int, body: UpdateIntersectionBody,
):
    """Rename, change leg count, or reorder an intersection card."""
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    if body.leg_count is not None and body.leg_count < 2:
        raise HTTPException(status_code=422, detail="leg_count must be >= 2")
    update_intersection(
        project_id, intersection_id,
        name=body.name, leg_count=body.leg_count, sort_order=body.sort_order,
    )
    return get_intersection(project_id, intersection_id)


@router.delete("/projects/{project_id}/intersections/{intersection_id}")
def delete_intersection(project_id: str, intersection_id: int):
    """Cascade-delete the intersection, all its cameras, all camera legs,
    all its trims. Videos formerly linked to those cameras are unlinked
    (returned to the project-level pool) — they aren't deleted from disk."""
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    remove_intersection(project_id, intersection_id)
    return {"deleted": True, "intersection_id": intersection_id}


# --- Cameras (scoped under an intersection) --------------------------------

@router.get("/projects/{project_id}/intersections/{intersection_id}/cameras")
def get_cameras(project_id: str, intersection_id: int):
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    cams = list_cameras(project_id, intersection_id)
    for c in cams:
        c["videos"] = list_videos_for_camera(project_id, c["camera_id"])
    return cams


@router.patch("/projects/{project_id}/intersections/{intersection_id}/cameras/{camera_id}")
def patch_camera(
    project_id: str, intersection_id: int, camera_id: int, body: UpdateCameraBody,
):
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    _require_camera(project_id, camera_id)
    update_camera(project_id, camera_id, label=body.label, sort_order=body.sort_order)
    return get_camera(project_id, camera_id)


@router.delete("/projects/{project_id}/intersections/{intersection_id}/cameras/{camera_id}")
def delete_camera(project_id: str, intersection_id: int, camera_id: int):
    """Remove a camera. Cascades to its legs; videos are unlinked."""
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    _require_camera(project_id, camera_id)
    remove_camera(project_id, camera_id)
    return {"deleted": True, "camera_id": camera_id}


# --- Trims -----------------------------------------------------------------

@router.get("/projects/{project_id}/intersections/{intersection_id}/trims")
def get_trims(project_id: str, intersection_id: int):
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    return list_trims(project_id, intersection_id)


def _validate_trim(start_wallclock: str, end_wallclock: str) -> None:
    """Basic HH:MM:SS shape + start < end check. Coverage validation runs
    separately in the coverage-report endpoint and at process time."""
    try:
        s_h, s_m, s_s = map(int, start_wallclock.split(":"))
        e_h, e_m, e_s = map(int, end_wallclock.split(":"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Trim times must be HH:MM:SS")
    if (s_h, s_m, s_s) >= (e_h, e_m, e_s):
        raise HTTPException(status_code=422, detail="Trim end must be after trim start")


@router.post("/projects/{project_id}/intersections/{intersection_id}/trims")
def post_trim(project_id: str, intersection_id: int, body: TrimBody):
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    _validate_trim(body.start_wallclock, body.end_wallclock)
    tid = add_trim(project_id, intersection_id, body.start_wallclock, body.end_wallclock)
    return {"trim_id": tid}


@router.patch("/projects/{project_id}/intersections/{intersection_id}/trims/{trim_id}")
def patch_trim(
    project_id: str, intersection_id: int, trim_id: int, body: UpdateTrimBody,
):
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    if body.start_wallclock and body.end_wallclock:
        _validate_trim(body.start_wallclock, body.end_wallclock)
    update_trim(
        project_id, trim_id,
        start_wallclock=body.start_wallclock,
        end_wallclock=body.end_wallclock,
        sort_order=body.sort_order,
    )
    return {"updated": True, "trim_id": trim_id}


@router.delete("/projects/{project_id}/intersections/{intersection_id}/trims/{trim_id}")
def delete_trim(project_id: str, intersection_id: int, trim_id: int):
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    remove_trim(project_id, trim_id)
    return {"deleted": True, "trim_id": trim_id}


# --- Coverage report -------------------------------------------------------

@router.get("/projects/{project_id}/intersections/{intersection_id}/coverage-report")
def get_coverage_report(project_id: str, intersection_id: int):
    """Per-trim breakdown of camera coverage at this intersection-day.

    The frontend trim editor uses this to (a) draw the Gantt-chart-like
    visualizer showing which camera covers each second of each trim, and
    (b) surface uncovered gaps as inline errors on the trim row.

    Each trim is reported with:
      - `sub_intervals`: list of (start, end, camera_ids) entries showing
        which cameras cover each piece of the trim
      - `gaps`: list of (start, end) entries with no camera coverage
      - `is_fully_covered`: boolean
    """
    _require_project(project_id)
    intersection = _require_intersection(project_id, intersection_id)
    coverages = _camera_coverages(project_id, intersection)
    date_str = intersection["date"]
    trims = list_trims(project_id, intersection_id)

    per_trim: list[dict] = []
    for t in trims:
        try:
            trim_iv = _trim_to_interval(date_str, t)
        except ValueError as e:
            per_trim.append({
                "trim_id": t["trim_id"],
                "error": f"Bad trim times: {e}",
            })
            continue
        report = compute_coverage_report(coverages, trim_iv)
        per_trim.append({
            "trim_id": t["trim_id"],
            "start_wallclock": t["start_wallclock"],
            "end_wallclock": t["end_wallclock"],
            "is_fully_covered": report.is_fully_covered(),
            "sub_intervals": [
                {
                    "start": iv.start.isoformat(timespec="seconds"),
                    "end": iv.end.isoformat(timespec="seconds"),
                    "camera_ids": cams,
                }
                for iv, cams in report.sub_intervals
            ],
            "gaps": [
                {
                    "start": iv.start.isoformat(timespec="seconds"),
                    "end": iv.end.isoformat(timespec="seconds"),
                }
                for iv in report.gaps
            ],
        })

    # Also include the per-camera coverage so the UI can draw the
    # Gantt-chart background (covered windows for each camera).
    per_camera = []
    for cov in coverages:
        per_camera.append({
            "camera_id": cov.camera_id,
            "intervals": [
                {
                    "start": iv.start.isoformat(timespec="seconds"),
                    "end": iv.end.isoformat(timespec="seconds"),
                }
                for iv in cov.intervals
            ],
        })

    return {
        "intersection_id": intersection_id,
        "date": date_str,
        "per_camera": per_camera,
        "per_trim": per_trim,
    }


# --- Processing orchestration ---------------------------------------------

def _plan_for_intersection(project_id: str, intersection: dict):
    """Build the segment plan for an intersection-day."""
    iid = intersection["intersection_id"]
    trims = list_trims(project_id, iid)
    cameras = list_cameras(project_id, iid)
    cameras_with_videos = [
        (c, list_videos_for_camera(project_id, c["camera_id"]))
        for c in cameras
    ]
    return plan_intersection_day(
        date_str=intersection["date"],
        trims=trims,
        cameras_with_videos=cameras_with_videos,
    )


@router.post("/projects/{project_id}/intersections/{intersection_id}/processing/preflight")
def processing_preflight(project_id: str, intersection_id: int):
    """Dry-run the orchestrator's planner. Returns the segment plan
    (or coverage errors) without actually starting the pipeline.

    The frontend Confirm popup uses this to show "we'll process N segments
    across M cameras and K trims" before the user clicks final start.
    """
    _require_project(project_id)
    intersection = _require_intersection(project_id, intersection_id)
    plan = _plan_for_intersection(project_id, intersection)
    return {
        "errors": plan.errors,
        "ok": len(plan.errors) == 0,
        "segment_count": len(plan.segments),
        "cameras_used": plan.cameras_used,
        "trims_used": plan.trims_used,
        "segments": [
            {
                "video_id": s.video_id,
                "camera_id": s.camera_id,
                "trim_id": s.trim_id,
                "start_offset_seconds": s.start_offset_seconds,
                "end_offset_seconds": s.end_offset_seconds,
                "start_frame": s.start_frame,
                "end_frame": s.end_frame,
            }
            for s in plan.segments
        ],
    }


def _run_v3_pipeline(
    project_id: str, intersection_id: int, segments: list,
):
    """Background thread: run the pipeline for each segment in turn.

    Imported lazily to avoid pulling the ProcessingPipeline (which loads
    torch/ultralytics) into the intersections module at import time —
    matters for test environments where torch DLLs are flaky.
    """
    from backend.database import get_db_path
    from backend.services.checkpoint import CheckpointManager
    from backend.services.pipeline import ProcessingPipeline
    from backend.config import DEFAULT_FRAME_SKIP
    import json as _json

    db_path = str(get_db_path(project_id))
    key = (project_id, intersection_id)

    try:
        with _v3_jobs_lock:
            _v3_jobs[key]["status"] = "running"

        for idx, seg in enumerate(segments):
            with _v3_jobs_lock:
                if _v3_jobs[key].get("cancel_requested"):
                    _v3_jobs[key]["status"] = "cancelled"
                    return
                _v3_jobs[key]["current_segment_index"] = idx
                _v3_jobs[key]["current_camera_id"] = seg.camera_id
                _v3_jobs[key]["current_trim_id"] = seg.trim_id
                _v3_jobs[key]["current_video_id"] = seg.video_id

            # Load legs for this camera (per-camera calibration).
            conn = get_connection(project_id)
            try:
                conn.row_factory = __import__("sqlite3").Row
                leg_rows = [dict(r) for r in conn.execute(
                    "SELECT * FROM legs WHERE camera_id = ? ORDER BY sort_order",
                    (seg.camera_id,),
                ).fetchall()]
                for leg in leg_rows:
                    oz = leg.get("origin_zone")
                    if isinstance(oz, str):
                        leg["origin_zone"] = _json.loads(oz)
            finally:
                conn.close()

            if not leg_rows:
                with _v3_jobs_lock:
                    _v3_jobs[key].setdefault("warnings", []).append(
                        f"Camera {seg.camera_id} has no legs — skipping segment."
                    )
                continue

            pipeline = ProcessingPipeline(
                project_id=project_id,
                db_path=db_path,
                video_path=seg.video_path,
                legs=leg_rows,
                fps=seg.fps,
                video_id=seg.video_id,
            )
            # Tag events with our trim_id + camera_id so the aggregator can
            # group correctly. The pipeline already writes video_id from
            # its constructor arg.
            pipeline._v3_trim_id = seg.trim_id
            pipeline._v3_camera_id = seg.camera_id

            # Live preview: push every callback's frame data into the
            # intersection-scoped preview queue so the MJPEG endpoint can
            # stream what the AI is currently seeing.
            preview_q = _ensure_v3_preview_worker(key)

            def _on_frame(data: dict, _q=preview_q):
                try:
                    _q.put_nowait((
                        data["raw_frame"],
                        data["tracks"],
                        data["origin_zones"],
                        leg_rows,
                        data["active_trajectories"],
                        data["finalized_trajectories"],
                    ))
                except queue.Full:
                    # Worker is still encoding the last frame — drop this one
                    # rather than block the pipeline.
                    pass
                except Exception:
                    pass

            # Stash the running pipeline on the job dict so the cancel
            # endpoint can flip its is_running flag and stop processing
            # mid-segment. Without this, cancel only takes effect at the
            # next segment boundary (potentially hours away).
            with _v3_jobs_lock:
                _v3_jobs[key]["pipeline"] = pipeline
            try:
                pipeline.process_video(
                    frame_skip=DEFAULT_FRAME_SKIP,
                    start_frame=seg.start_frame,
                    end_frame=seg.end_frame,
                    callback=_on_frame,
                )
            finally:
                # Drop the pipeline ref + check whether the run was
                # cancelled mid-segment, all under one lock.
                with _v3_jobs_lock:
                    _v3_jobs[key].pop("pipeline", None)
                    cancelled = bool(_v3_jobs[key].get("cancel_requested"))
                    if cancelled:
                        _v3_jobs[key]["status"] = "cancelled"
            if cancelled:
                return
            # Backfill camera_id + trim_id on events the pipeline wrote.
            # The pipeline currently writes only video_id; we patch the
            # rest here so the rest of v3 (aggregator, dedup) can use them.
            conn = get_connection(project_id)
            try:
                conn.execute(
                    """UPDATE vehicle_events
                       SET camera_id = ?, trim_id = ?
                       WHERE video_id = ?
                         AND frame_number >= ?
                         AND frame_number < ?
                         AND (camera_id IS NULL OR trim_id IS NULL)""",
                    (seg.camera_id, seg.trim_id, seg.video_id,
                     seg.start_frame, seg.end_frame),
                )
                conn.commit()
            finally:
                conn.close()

        with _v3_jobs_lock:
            _v3_jobs[key]["status"] = "complete"
    except Exception as exc:
        with _v3_jobs_lock:
            _v3_jobs[key]["status"] = "error"
            _v3_jobs[key]["error"] = str(exc)
    finally:
        # Tear down the live preview worker — keep the last frame stashed
        # briefly so the client's MJPEG stream sees a final frame before
        # the server stops yielding.
        _stop_v3_preview_worker(key)


@router.post("/projects/{project_id}/intersections/{intersection_id}/processing/start")
def processing_start(project_id: str, intersection_id: int):
    """Plan + kick off processing for an entire intersection-day.

    Refuses if the plan has coverage errors; the user must fix trims first.
    Runs in a daemon thread. Status visible via /processing/status.
    """
    _require_project(project_id)
    intersection = _require_intersection(project_id, intersection_id)

    plan = _plan_for_intersection(project_id, intersection)
    if plan.errors:
        raise HTTPException(status_code=422, detail={
            "message": "Cannot start: trim coverage errors",
            "errors": plan.errors,
        })
    if not plan.segments:
        raise HTTPException(status_code=400, detail="Nothing to process.")

    key = (project_id, intersection_id)
    with _v3_jobs_lock:
        existing = _v3_jobs.get(key)
        if existing and existing.get("status") == "running":
            raise HTTPException(
                status_code=409,
                detail="Processing already running for this intersection.",
            )
        _v3_jobs[key] = {
            "status": "queued",
            "segment_count": len(plan.segments),
            "current_segment_index": 0,
            "current_camera_id": None,
            "current_trim_id": None,
            "current_video_id": None,
            "error": None,
            "warnings": [],
            "cancel_requested": False,
        }

    t = threading.Thread(
        target=_run_v3_pipeline,
        args=(project_id, intersection_id, plan.segments),
        daemon=True,
    )
    t.start()
    return {"status": "queued", "segments": len(plan.segments)}


_JOB_NON_SERIALIZABLE_KEYS = {"pipeline"}


@router.get("/projects/{project_id}/intersections/{intersection_id}/processing/status")
def processing_status(project_id: str, intersection_id: int):
    """Poll the running orchestrator state for this intersection-day."""
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    key = (project_id, intersection_id)
    with _v3_jobs_lock:
        job = _v3_jobs.get(key)
        if not job:
            return {"status": "idle"}
        # Filter out internal refs that aren't JSON-encodable (e.g. the
        # ProcessingPipeline instance the cancel endpoint reaches through).
        return {k: v for k, v in job.items() if k not in _JOB_NON_SERIALIZABLE_KEYS}


@router.get("/projects/{project_id}/intersections/{intersection_id}/processing/preview-stream")
async def processing_preview_stream(project_id: str, intersection_id: int):
    """MJPEG multipart stream of the AI-annotated frame the orchestrator is
    currently processing. Closes a few seconds after processing stops."""
    from fastapi.responses import StreamingResponse

    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    key = (project_id, intersection_id)

    async def generate():
        last_sent: bytes | None = None
        idle_since: float | None = None
        while True:
            with _v3_preview_lock:
                frame = _v3_preview_frames.get(key)
            with _v3_jobs_lock:
                job = _v3_jobs.get(key)
                is_running = bool(job) and job.get("status") == "running"

            if frame is not None and frame is not last_sent:
                last_sent = frame
                idle_since = None
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )

            if not is_running:
                if idle_since is None:
                    idle_since = time.time()
                elif time.time() - idle_since > 2.0:
                    break

            await asyncio.sleep(0.033)  # 30 fps cap

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store"},
    )


@router.get("/projects/{project_id}/intersections/{intersection_id}/processing/preview-frame")
def processing_preview_frame(project_id: str, intersection_id: int):
    """Single-shot JPEG fallback when the MJPEG stream isn't usable."""
    from fastapi.responses import Response

    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    key = (project_id, intersection_id)
    with _v3_preview_lock:
        jpeg = _v3_preview_frames.get(key)
    if jpeg is None:
        raise HTTPException(status_code=404, detail="No preview frame yet.")
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, no-cache"},
    )


@router.post("/projects/{project_id}/intersections/{intersection_id}/processing/cancel")
def processing_cancel(project_id: str, intersection_id: int):
    """Signal cancellation. Stops mid-segment when a pipeline is active."""
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    key = (project_id, intersection_id)
    pipeline = None
    with _v3_jobs_lock:
        if key in _v3_jobs and _v3_jobs[key].get("status") == "running":
            _v3_jobs[key]["cancel_requested"] = True
            pipeline = _v3_jobs[key].get("pipeline")
    # Flip is_running on the currently-running pipeline so process_video()
    # exits its while loop within one frame, instead of waiting until the
    # next segment-boundary check.
    if pipeline is not None:
        pipeline.is_running = False
    return {"status": "cancel_requested"}


# --- Aggregation + Excel export ------------------------------------------

@router.get("/projects/{project_id}/intersections/{intersection_id}/summary")
def get_summary(project_id: str, intersection_id: int):
    """Per-intersection-day aggregated counts (dedup applied).

    Feeds the playback verification dashboard's count panels and the
    Excel export's preview.
    """
    from backend.services.v3_aggregator import aggregate_intersection_day

    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    return aggregate_intersection_day(project_id, intersection_id)


@router.get("/projects/{project_id}/intersections/{intersection_id}/export/xlsx")
def export_intersection_day(project_id: str, intersection_id: int):
    """Download the per-intersection-day TMC report as an .xlsx file."""
    import tempfile
    from datetime import datetime as _dt
    from fastapi.responses import FileResponse
    from backend.services.v3_aggregator import aggregate_intersection_day
    from backend.services.v3_excel_export import export_intersection_day_xlsx

    _require_project(project_id)
    intersection = _require_intersection(project_id, intersection_id)

    safe_name = "".join(
        c if c.isalnum() or c in " ._-" else "_" for c in intersection["name"]
    ).strip()
    filename = f"TMC_{safe_name}_{intersection['date']}_{_dt.now().strftime('%H%M%S')}.xlsx"
    output_path = Path(tempfile.gettempdir()) / filename

    try:
        export_intersection_day_xlsx(project_id, intersection_id, output_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}")

    return FileResponse(
        path=str(output_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
