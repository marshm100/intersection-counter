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

router = APIRouter()


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
