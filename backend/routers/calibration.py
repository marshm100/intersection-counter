import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from backend.config import PROJECTS_DIR
from backend.database import (
    clear_paths_for_camera, delete_path, get_calibration_suggestion,
    get_camera, get_connection, get_project_info,
    list_paths_for_camera, list_videos, list_videos_for_camera,
    mark_suggestion_applied, mark_suggestion_rejected,
    upsert_path,
)
from backend.services import auto_calibrator_v2

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


# --- Path (polyline) CRUD models ---

VALID_MOVEMENTS = {"through", "left", "right", "u_turn"}


class PathInput(BaseModel):
    """One (origin_leg, destination_leg) path with a polyline through the
    intersection. movement_label must be one of through|left|right|u_turn."""
    origin_leg_id: int
    destination_leg_id: int
    polyline: List[List[float]]      # [[x, y], ...] in image coords
    movement_label: str
    supporting_count: int = 0
    source: str = "manual"           # manual|auto


class PathsReplaceRequest(BaseModel):
    """Bulk-replace ALL paths for a camera (used when applying an auto-cal
    suggestion in one shot, or when the engineer wants to start over)."""
    paths: List[PathInput]


def _require_project(project_id: str) -> None:
    project_dir = PROJECTS_DIR / project_id
    db_path = project_dir / "project.db"
    if not project_dir.exists() or not db_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")

# OLD auto-cal endpoints (project-scoped + camera-scoped variants that
# returned a frame_jpeg + leg suggestions in a single response) have been
# removed. They depended on backend/services/auto_calibrator.py, which
# was the sklearn DBSCAN-based implementation. Phase 3 replaced them with
# the camera-scoped /calibration/suggestion/* endpoints below, which use
# the scipy-based scripts/auto_calibrate.py via auto_calibrator_v2.


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


# OLD project-scoped auto-cal endpoints removed (Phase 3 replacement
# is /api/projects/{p}/cameras/{c}/calibration/suggestion/start below).


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

    # Refuse if a v3 pipeline is mid-run on this camera. The pipeline thread
    # has the current leg_ids cached and writes events against them; deleting
    # those legs out from under it would FK-fail the very next event insert.
    # User must cancel processing first.
    from backend.routers.intersections import _v3_jobs, _v3_jobs_lock
    with _v3_jobs_lock:
        for (pid, _iid), job in _v3_jobs.items():
            if (pid == project_id
                    and job.get("status") == "running"
                    and job.get("current_camera_id") == camera_id):
                raise HTTPException(
                    status_code=409,
                    detail="Processing is currently running on this camera. "
                           "Cancel processing before recalibrating.",
                )

    conn = get_connection(project_id)
    try:
        with conn:
            # Wipe this camera's vehicle events. Match on camera_id when set
            # AND on origin_leg_id IN (this camera's legs) so we also catch
            # orphan events written before the camera_id inline-write fix —
            # those rows have camera_id=NULL but their origin_leg_id still
            # FK-references a leg we're about to delete, so a plain
            # `camera_id = ?` wipe leaves them dangling and the leg DELETE
            # then trips a FOREIGN KEY constraint failure.
            conn.execute(
                """DELETE FROM vehicle_events
                   WHERE camera_id = ?
                      OR origin_leg_id IN (
                          SELECT leg_id FROM legs WHERE camera_id = ?
                      )""",
                (camera_id, camera_id),
            )
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


# OLD camera-scoped auto-cal endpoints removed — see /calibration/suggestion/* below.


# ---------------------------------------------------------------------------
# Path (polyline) CRUD — Phase 2.
#
# A path = one (origin_leg, destination_leg) road centerline through the
# intersection, stored as a polyline. The pipeline uses these to do
# curve-aware origin attribution + destination scoring + movement labeling
# in a single match pass. When a camera has zero paths, the pipeline
# falls back to the legacy tripwire+heading+softmax tiers (auto-upgrade).
# ---------------------------------------------------------------------------


def _validate_path(
    project_id: str, camera_id: int, body: PathInput, frame_size=(640, 480),
) -> None:
    """Range + referential checks. Raises HTTPException(422) on failure."""
    if body.movement_label not in VALID_MOVEMENTS:
        raise HTTPException(status_code=422,
            detail=f"movement_label must be one of {sorted(VALID_MOVEMENTS)}")
    if len(body.polyline) < 2:
        raise HTTPException(status_code=422,
            detail="polyline must have at least 2 control points")
    if len(body.polyline) > 50:
        raise HTTPException(status_code=422,
            detail="polyline capped at 50 control points")
    fw, fh = frame_size
    for i, pt in enumerate(body.polyline):
        if len(pt) != 2:
            raise HTTPException(status_code=422,
                detail=f"polyline[{i}] must be [x, y]")
        x, y = pt
        if not (-50 <= x <= fw + 50 and -50 <= y <= fh + 50):
            raise HTTPException(status_code=422,
                detail=f"polyline[{i}]=({x},{y}) outside expected range")
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT leg_id FROM legs WHERE camera_id = ?", (camera_id,),
        ).fetchall()
    finally:
        conn.close()
    valid_lids = {r[0] for r in rows}
    for which, lid in (("origin_leg_id", body.origin_leg_id),
                       ("destination_leg_id", body.destination_leg_id)):
        if lid not in valid_lids:
            raise HTTPException(status_code=422,
                detail=f"{which}={lid} is not a leg of camera {camera_id}")


def _frame_size_for_camera(project_id: str, camera_id: int) -> tuple[int, int]:
    """Look up frame width/height from one of the camera's videos.
    Falls back to (640, 480) when no videos are attached yet."""
    videos = list_videos_for_camera(project_id, camera_id)
    if videos and videos[0].get("width") and videos[0].get("height"):
        return int(videos[0]["width"]), int(videos[0]["height"])
    return (640, 480)


@router.get("/projects/{project_id}/cameras/{camera_id}/paths")
def get_camera_paths(project_id: str, camera_id: int):
    """List all paths for this camera, ordered by (origin, destination)."""
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    return {"paths": list_paths_for_camera(project_id, camera_id)}


@router.post("/projects/{project_id}/cameras/{camera_id}/paths")
def upsert_camera_path(
    project_id: str, camera_id: int, body: PathInput,
):
    """Insert-or-update a single path keyed by (camera_id, origin_leg,
    destination_leg). Returns the saved row."""
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    _validate_path(project_id, camera_id, body,
                   frame_size=_frame_size_for_camera(project_id, camera_id))
    path_id = upsert_path(
        project_id, camera_id,
        body.origin_leg_id, body.destination_leg_id,
        body.polyline, body.movement_label,
        source=body.source, supporting_count=body.supporting_count,
    )
    rows = [p for p in list_paths_for_camera(project_id, camera_id)
            if p["path_id"] == path_id]
    return rows[0] if rows else {"path_id": path_id}


@router.put("/projects/{project_id}/cameras/{camera_id}/paths")
def replace_camera_paths(
    project_id: str, camera_id: int, body: PathsReplaceRequest,
):
    """Bulk replace: delete all existing paths for this camera, then
    insert the new list. Used for 'apply auto-cal suggestion in one
    shot' flows and 'engineer redrew everything from scratch'."""
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    fs = _frame_size_for_camera(project_id, camera_id)
    for p in body.paths:
        _validate_path(project_id, camera_id, p, frame_size=fs)
    clear_paths_for_camera(project_id, camera_id)
    for p in body.paths:
        upsert_path(
            project_id, camera_id,
            p.origin_leg_id, p.destination_leg_id,
            p.polyline, p.movement_label,
            source=p.source, supporting_count=p.supporting_count,
        )
    return {"paths": list_paths_for_camera(project_id, camera_id)}


@router.delete("/projects/{project_id}/cameras/{camera_id}/paths/{path_id}")
def delete_camera_path(project_id: str, camera_id: int, path_id: int):
    """Delete a single path. 404 if not found OR if it belongs to a
    different camera (defensive — prevents cross-camera deletes)."""
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    existing = [p for p in list_paths_for_camera(project_id, camera_id)
                if p["path_id"] == path_id]
    if not existing:
        raise HTTPException(status_code=404,
            detail=f"path {path_id} not found for camera {camera_id}")
    delete_path(project_id, path_id)
    return {"deleted": True, "path_id": path_id}


@router.delete("/projects/{project_id}/cameras/{camera_id}/paths")
def clear_camera_paths(project_id: str, camera_id: int):
    """Delete ALL paths for this camera. Returns count deleted."""
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    n = clear_paths_for_camera(project_id, camera_id)
    return {"deleted": True, "count": n}


# ---------------------------------------------------------------------------
# Auto-calibration suggestion endpoints — Phase 3.
#
# Engineer kicks off an auto-cal job; worker runs in background; when
# done the result is in calibration_suggestions. Engineer can preview,
# apply (copies paths into intersection_paths), or reject.
# ---------------------------------------------------------------------------


class StartAutoCalBody(BaseModel):
    video_id: int | None = None              # default: first video on camera
    sample_start_sec: float = 0.0
    sample_end_sec: float | None = None      # default: start + 15 min


@router.post("/projects/{project_id}/cameras/{camera_id}/calibration/suggestion/start")
def start_camera_auto_cal_v2(
    project_id: str, camera_id: int, body: StartAutoCalBody,
):
    """Kick off an auto-cal job in the background. Returns the job_id;
    poll /status for progress. Replaces any prior in-flight job for this
    camera. Single-job global concurrency — see service module."""
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    job_id = auto_calibrator_v2.enqueue(
        project_id, camera_id,
        video_id=body.video_id,
        sample_start_sec=body.sample_start_sec,
        sample_end_sec=body.sample_end_sec,
    )
    return {"job_id": job_id, "camera_id": camera_id, "status": "queued"}


@router.get("/projects/{project_id}/cameras/{camera_id}/calibration/suggestion/status")
def get_camera_auto_cal_status_v2(project_id: str, camera_id: int):
    """Polled by the UI while the job runs. Returns running/complete/error
    + progress + phase. Returns 404 if no job has been started for this
    camera in this process lifetime."""
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    status = auto_calibrator_v2.get_status(camera_id)
    if status is None:
        raise HTTPException(status_code=404,
                            detail="No auto-cal job for this camera yet")
    return status


@router.post("/projects/{project_id}/cameras/{camera_id}/calibration/suggestion/cancel")
def cancel_camera_auto_cal_v2(project_id: str, camera_id: int):
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    ok = auto_calibrator_v2.cancel(camera_id)
    return {"cancel_requested": ok}


@router.get("/projects/{project_id}/cameras/{camera_id}/calibration/suggestion")
def get_camera_suggestion(project_id: str, camera_id: int):
    """The latest stored suggestion for this camera (any status). Empty
    object when none exists. UI uses this to render the review banner."""
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    sug = get_calibration_suggestion(project_id, camera_id)
    return sug or {}


def _zone_id_to_leg_id(payload: dict, camera_id: int, project_id: str) -> dict[int, int]:
    """Map suggestion zone_ids to real leg_ids. Strategy: find the existing
    leg whose origin_zone[0] is closest to each suggested zone's
    origin_point. Suggestion zones with no nearby leg are dropped (the
    engineer can extend calibration to add legs first).

    Returns {zone_id: leg_id}. Missing zones absent from the dict.
    """
    import math
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT leg_id, origin_zone FROM legs WHERE camera_id=?", (camera_id,),
        ).fetchall()
    finally:
        conn.close()
    legs = []
    for r in rows:
        try:
            zone = json.loads(r[1]) if r[1] else []
            if zone and len(zone) >= 1:
                legs.append((r[0], float(zone[0][0]), float(zone[0][1])))
        except Exception:
            pass
    out = {}
    for z in payload.get("leg_zones", []):
        zid = z["zone_id"]
        ox, oy = z["origin_point"]
        if not legs:
            continue
        # Nearest leg by Euclidean distance, within 80 px tolerance.
        best, best_d = None, float("inf")
        for lid, lx, ly in legs:
            d = math.hypot(ox - lx, oy - ly)
            if d < best_d:
                best_d, best = d, lid
        if best is not None and best_d <= 80.0:
            out[zid] = best
    return out


@router.post("/projects/{project_id}/cameras/{camera_id}/calibration/suggestion/apply")
def apply_camera_suggestion(project_id: str, camera_id: int):
    """Copy the suggestion's paths into intersection_paths.

    For each suggested path, look up the actual leg_id by spatial match
    (zone_id -> nearest leg's leg_id within 80 px). Paths whose origin
    or destination zone can't be matched are skipped — the engineer
    can manually adjust calibration legs first and re-apply.

    Replaces any existing paths for this camera (you're saying "use the
    auto-cal output, throw away whatever was there"). Marks the
    suggestion as applied."""
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    sug = get_calibration_suggestion(project_id, camera_id)
    if not sug or not sug.get("payload"):
        raise HTTPException(status_code=404,
                            detail="No suggestion to apply")
    payload = sug["payload"]
    zone_to_leg = _zone_id_to_leg_id(payload, camera_id, project_id)

    applied = 0
    skipped = []
    clear_paths_for_camera(project_id, camera_id)
    for p in payload.get("paths", []):
        ozid = p.get("origin_zone_id")
        dzid = p.get("destination_zone_id")
        o_lid = zone_to_leg.get(ozid)
        d_lid = zone_to_leg.get(dzid)
        if o_lid is None or d_lid is None:
            skipped.append({"origin_zone_id": ozid,
                            "destination_zone_id": dzid,
                            "reason": "no matching leg within 80 px"})
            continue
        upsert_path(
            project_id, camera_id, o_lid, d_lid,
            p["polyline"], p["movement_label"],
            source="auto", supporting_count=p.get("supporting_count", 0),
        )
        applied += 1
    mark_suggestion_applied(project_id, camera_id)
    return {
        "applied_paths": applied,
        "skipped": skipped,
        "current_paths": list_paths_for_camera(project_id, camera_id),
    }


@router.post("/projects/{project_id}/cameras/{camera_id}/calibration/suggestion/reject")
def reject_camera_suggestion(project_id: str, camera_id: int):
    _require_project(project_id)
    _require_camera_404(project_id, camera_id)
    mark_suggestion_rejected(project_id, camera_id)
    return {"status": "rejected"}
