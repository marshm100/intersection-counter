import base64
import json
import logging
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from backend.config import PROJECTS_DIR
from backend.database import (
    get_camera, get_connection, get_project_info,
    list_videos, list_videos_for_camera,
)
from backend.services.auto_calibrator import auto_calibrate

logger = logging.getLogger(__name__)
router = APIRouter()


class LegInput(BaseModel):
    label: str
    cardinal_direction: str
    sort_order: int
    origin_zone: List[List[float]]   # [[x, y]] — one point
    reference_heading: float


class CalibrationSaveRequest(BaseModel):
    legs: List[LegInput]


class StartAutoBody(BaseModel):
    prescan_seconds: int = 300
    screen_north_direction: str = "up"
    num_legs_hint: int | None = None


# In-memory job registry: job_id -> {status, project_id, progress_pct, result, error, updated_at}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_current_job_per_project: dict[str, str] = {}


def _require_project(project_id: str) -> None:
    project_dir = PROJECTS_DIR / project_id
    db_path = project_dir / "project.db"
    if not project_dir.exists() or not db_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")


def _update_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)
            _jobs[job_id]["updated_at"] = time.time()


def _run_auto_calibration(
    job_id: str,
    project_id: str,
    video_path: str,
    prescan_seconds: int,
    screen_north_direction: str,
    num_legs_hint: int | None,
) -> None:
    """Background worker for auto-calibration. Updates job state as it runs."""
    def progress_callback(info: dict) -> None:
        _update_job(job_id, progress_pct=info.get("progress_pct", 0.0))

    try:
        _update_job(job_id, status="running", progress_pct=0.0)
        result = auto_calibrate(
            video_path=video_path,
            prescan_seconds=prescan_seconds,
            screen_north_direction=screen_north_direction,
            num_legs_hint=num_legs_hint,
            progress_callback=progress_callback,
        )
        result_dict = result.to_dict()
        if result.frame_jpeg:
            result_dict["frame_jpeg_b64"] = base64.b64encode(result.frame_jpeg).decode("ascii")
        _update_job(job_id, status="completed", progress_pct=100.0, result=result_dict)
    except Exception as e:
        logger.exception("Auto-calibration job %s failed", job_id)
        _update_job(job_id, status="failed", error=str(e))


@router.get("/projects/{project_id}/calibration")
def get_calibration(project_id: str):
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT leg_id, label, cardinal_direction, sort_order, origin_zone, reference_heading "
            "FROM legs ORDER BY sort_order"
        ).fetchall()
    finally:
        conn.close()

    legs = []
    for row in rows:
        legs.append({
            "leg_id": row[0],
            "label": row[1],
            "cardinal_direction": row[2],
            "sort_order": row[3],
            "origin_zone": json.loads(row[4]) if row[4] else None,
            "reference_heading": row[5],
        })
    return {"legs": legs}


@router.put("/projects/{project_id}/calibration/legs")
def save_calibration(project_id: str, body: CalibrationSaveRequest):
    if not body.legs:
        raise HTTPException(status_code=422, detail="At least one leg is required.")

    conn = get_connection(project_id)
    try:
        with conn:
            conn.execute("DELETE FROM vehicle_events")
            conn.execute("DELETE FROM low_confidence_segments")
            conn.execute("DELETE FROM checkpoint")
            conn.execute("DELETE FROM legs")
            for leg in body.legs:
                conn.execute(
                    "INSERT INTO legs (label, cardinal_direction, sort_order, origin_zone, reference_heading) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        leg.label,
                        leg.cardinal_direction,
                        leg.sort_order,
                        json.dumps(leg.origin_zone),
                        leg.reference_heading,
                    ),
                )
        rows = conn.execute(
            "SELECT leg_id, label, cardinal_direction, sort_order, origin_zone, reference_heading "
            "FROM legs ORDER BY sort_order"
        ).fetchall()
    finally:
        conn.close()

    saved = []
    for row in rows:
        saved.append({
            "leg_id": row[0],
            "label": row[1],
            "cardinal_direction": row[2],
            "sort_order": row[3],
            "origin_zone": json.loads(row[4]) if row[4] else None,
            "reference_heading": row[5],
        })

    # Warn if all reference headings are suspiciously close
    warnings = []
    headings = [l["reference_heading"] for l in saved if l["reference_heading"] is not None]
    if len(headings) >= 2:
        max_spread = max(
            abs((h1 - h2 + 180) % 360 - 180)
            for i, h1 in enumerate(headings)
            for h2 in headings[i + 1:]
        )
        if max_spread < 30:
            warnings.append(
                "All reference headings are within 30° of each other. "
                "This likely means all vehicles will be assigned to the same leg."
            )

    return {"legs": saved, "warnings": warnings}


@router.post("/projects/{project_id}/calibration/auto")
def start_auto_calibration(project_id: str, body: StartAutoBody):
    """Start an async auto-calibration job. Returns job_id for polling."""
    _require_project(project_id)

    # Prefer the multi-video table (first video by sort_order); fall back to
    # the legacy single-video project_info path so older projects still work.
    videos = list_videos(project_id)
    if videos:
        video_path = videos[0]["path"]
    else:
        video_path = get_project_info(project_id, "video_path")
    if not video_path:
        raise HTTPException(status_code=400, detail="No video set for this project")

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "project_id": project_id,
            "status": "queued",
            "progress_pct": 0.0,
            "result": None,
            "error": None,
            "updated_at": time.time(),
        }
        _current_job_per_project[project_id] = job_id

    thread = threading.Thread(
        target=_run_auto_calibration,
        args=(
            job_id, project_id, video_path,
            body.prescan_seconds, body.screen_north_direction, body.num_legs_hint,
        ),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id, "status": "queued"}


@router.get("/projects/{project_id}/calibration/auto/status")
def get_auto_calibration_status(project_id: str, job_id: str | None = None):
    """Poll the state of an auto-calibration job. If job_id is omitted,
    returns the most recent job for this project."""
    _require_project(project_id)

    if job_id is None:
        with _jobs_lock:
            job_id = _current_job_per_project.get(project_id)
        if job_id is None:
            raise HTTPException(status_code=404, detail="No auto-calibration job for this project")

    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(job)


# ---------------------------------------------------------------------------
# v3: camera-scoped calibration
#
# Each camera has its own set of legs (origin zones + headings) because two
# cameras at the same intersection see it from different angles. The
# project-scoped endpoints above are preserved for legacy single-camera
# projects and for the auto-cal job runner.
# ---------------------------------------------------------------------------

def _require_camera_404(project_id: str, camera_id: int) -> dict:
    cam = get_camera(project_id, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


@router.get("/projects/{project_id}/cameras/{camera_id}/calibration")
def get_camera_calibration(project_id: str, camera_id: int):
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT leg_id, label, cardinal_direction, sort_order, origin_zone, reference_heading "
            "FROM legs WHERE camera_id = ? ORDER BY sort_order",
            (camera_id,),
        ).fetchall()
    finally:
        conn.close()

    legs = []
    for row in rows:
        legs.append({
            "leg_id": row[0],
            "label": row[1],
            "cardinal_direction": row[2],
            "sort_order": row[3],
            "origin_zone": json.loads(row[4]) if row[4] else None,
            "reference_heading": row[5],
        })
    return {"legs": legs}


@router.put("/projects/{project_id}/cameras/{camera_id}/calibration/legs")
def save_camera_calibration(
    project_id: str, camera_id: int, body: CalibrationSaveRequest,
):
    """Replace this camera's legs. Does NOT wipe events from other cameras."""
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    if not body.legs:
        raise HTTPException(status_code=422, detail="At least one leg is required.")

    conn = get_connection(project_id)
    try:
        with conn:
            # Wipe only this camera's vehicle events + legs.
            conn.execute("DELETE FROM vehicle_events WHERE camera_id = ?", (camera_id,))
            conn.execute("DELETE FROM legs WHERE camera_id = ?", (camera_id,))
            for leg in body.legs:
                conn.execute(
                    "INSERT INTO legs (camera_id, label, cardinal_direction, "
                    "sort_order, origin_zone, reference_heading) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        camera_id,
                        leg.label,
                        leg.cardinal_direction,
                        leg.sort_order,
                        json.dumps(leg.origin_zone),
                        leg.reference_heading,
                    ),
                )
        rows = conn.execute(
            "SELECT leg_id, label, cardinal_direction, sort_order, origin_zone, reference_heading "
            "FROM legs WHERE camera_id = ? ORDER BY sort_order",
            (camera_id,),
        ).fetchall()
    finally:
        conn.close()

    saved = []
    for row in rows:
        saved.append({
            "leg_id": row[0],
            "label": row[1],
            "cardinal_direction": row[2],
            "sort_order": row[3],
            "origin_zone": json.loads(row[4]) if row[4] else None,
            "reference_heading": row[5],
        })
    return {"legs": saved}


@router.post("/projects/{project_id}/cameras/{camera_id}/calibration/auto")
def start_camera_auto_calibration(
    project_id: str, camera_id: int, body: StartAutoBody,
):
    """Start an auto-cal job using the first video attached to this camera.

    Same async pattern as the project-level endpoint, but the job runs on
    a camera's specific clip and writes results scoped to that camera.
    The legs aren't auto-saved — the user reviews + confirms via PUT.
    """
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)

    videos = list_videos_for_camera(project_id, camera_id)
    if not videos:
        raise HTTPException(
            status_code=400,
            detail="This camera has no videos attached. Add at least one video first.",
        )
    video_path = videos[0]["path"]

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "project_id": project_id,
            "camera_id": camera_id,
            "status": "queued",
            "progress_pct": 0.0,
            "result": None,
            "error": None,
            "updated_at": time.time(),
        }
        _current_job_per_project[f"{project_id}:cam{camera_id}"] = job_id

    thread = threading.Thread(
        target=_run_auto_calibration,
        args=(
            job_id, project_id, video_path,
            body.prescan_seconds, body.screen_north_direction, body.num_legs_hint,
        ),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id, "status": "queued"}


@router.get("/projects/{project_id}/cameras/{camera_id}/calibration/auto/status")
def get_camera_auto_calibration_status(
    project_id: str, camera_id: int, job_id: str | None = None,
):
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)

    if job_id is None:
        with _jobs_lock:
            job_id = _current_job_per_project.get(f"{project_id}:cam{camera_id}")
        if job_id is None:
            raise HTTPException(
                status_code=404,
                detail="No auto-calibration job for this camera",
            )
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(job)
