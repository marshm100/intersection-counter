"""Multi-video router — per-project video CRUD (plural endpoint).

This router runs ALONGSIDE the legacy singular /video router during the
multi-video migration. The legacy router writes video_path to project_info;
this router writes proper rows to the videos table. Pipeline and frontend
will migrate to videos-table reads in subsequent phases.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from backend.config import PROJECTS_DIR
from backend.database import (
    add_video, find_video_by_path, get_connection, get_video,
    list_videos, list_intersections, list_cameras,
    remove_video, set_project_info, set_video_recording_start_time,
    update_video_labels, link_video_to_camera,
    upsert_intersection, upsert_camera,
)
from backend.services.filename_parser import parse_with_fallback
from backend.services.video_service import get_frame_at_time, get_video_info

router = APIRouter()


class AddVideoBody(BaseModel):
    path: str


class BulkAddBody(BaseModel):
    paths: list[str]


class StartTimeBody(BaseModel):
    recording_start_time: Optional[str] = None


class OrderBody(BaseModel):
    sort_order: int


class LabelsBody(BaseModel):
    intersection_name: Optional[str] = None
    recording_start_datetime: Optional[str] = None
    camera_label: Optional[str] = None


def _enrich_with_parse(metadata: dict) -> dict:
    """Augment a video_service.get_video_info() dict with filename-parse fields."""
    parsed = parse_with_fallback(metadata["path"], metadata.get("duration_seconds"))
    metadata = dict(metadata)
    metadata["camera_label_parsed"] = parsed.camera_label
    metadata["intersection_name_label"] = parsed.intersection_hint
    metadata["recording_start_datetime"] = parsed.recording_start_datetime.isoformat(timespec="seconds")
    metadata["parse_confidence"] = parsed.parse_confidence
    return metadata


def _require_project(project_id: str) -> None:
    project_dir = PROJECTS_DIR / project_id
    db_path = project_dir / "project.db"
    if not project_dir.exists() or not db_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")


def _require_video(project_id: str, video_id: int) -> dict:
    v = get_video(project_id, video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return v


def _open_file_dialog() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            filetypes=[
                ("Video Files", "*.mp4 *.mov *.avi *.mkv"),
                ("All Files", "*.*"),
            ]
        )
        root.destroy()
        return path if path else None
    except Exception:
        return None


def _open_multi_file_dialog() -> list[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        paths = filedialog.askopenfilenames(
            filetypes=[
                ("Video Files", "*.mp4 *.mov *.avi *.mkv"),
                ("All Files", "*.*"),
            ]
        )
        root.destroy()
        return list(paths) if paths else []
    except Exception:
        return []


@router.get("/projects/{project_id}/videos")
def get_videos(project_id: str):
    """List all videos attached to the project, in sort order."""
    _require_project(project_id)
    return list_videos(project_id)


@router.post("/projects/{project_id}/videos/browse")
async def browse_video(project_id: str):
    """Open a native single-file dialog. Returns the chosen path or None."""
    _require_project(project_id)
    path = await asyncio.to_thread(_open_file_dialog)
    return {"path": path}


@router.post("/projects/{project_id}/videos/browse-multi")
async def browse_videos_multi(project_id: str):
    """Open a native multi-file dialog. Returns the chosen paths."""
    _require_project(project_id)
    paths = await asyncio.to_thread(_open_multi_file_dialog)
    return {"paths": paths}


@router.post("/projects/{project_id}/videos")
def post_video(project_id: str, body: AddVideoBody):
    """Attach a single video file. Idempotent — same path returns existing row.

    Filename is parsed on attach to pre-populate camera_label, recording
    start datetime, intersection hint, and parse_confidence.
    """
    _require_project(project_id)

    try:
        info = get_video_info(body.path)
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="Video file not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = find_video_by_path(project_id, info["path"])
    if existing:
        return existing

    info = _enrich_with_parse(info)
    vid = add_video(project_id, info)
    return get_video(project_id, vid)


@router.post("/projects/{project_id}/videos/bulk")
def post_videos_bulk(project_id: str, body: BulkAddBody):
    """Attach many videos at once. Returns per-path results.

    Each result is either an attached video row (success) or
    {"path": ..., "error": "..."} for files that couldn't be opened.
    The bulk operation never aborts on a single failure — partial success
    is the norm for drag-drop batches.
    """
    _require_project(project_id)
    results: list[dict] = []
    for path in body.paths:
        try:
            info = get_video_info(path)
        except FileNotFoundError:
            results.append({"path": path, "error": "Video file not found"})
            continue
        except ValueError as e:
            results.append({"path": path, "error": str(e)})
            continue
        except Exception as e:
            results.append({"path": path, "error": f"Unexpected: {e}"})
            continue

        existing = find_video_by_path(project_id, info["path"])
        if existing:
            results.append(existing)
            continue

        info = _enrich_with_parse(info)
        vid = add_video(project_id, info)
        row = get_video(project_id, vid)
        if row:
            results.append(row)
    return {"results": results}


@router.patch("/projects/{project_id}/videos/{video_id}/labels")
def patch_video_labels(project_id: str, video_id: int, body: LabelsBody):
    """User-edits to the v3 label fields on a single video.

    Allowed fields: intersection_name, recording_start_datetime, camera_label.
    A successful patch invalidates the previously-derived intersection grouping
    (the user must re-run save-labels to apply changes to the hierarchy).
    """
    _require_project(project_id)
    _require_video(project_id, video_id)
    update_video_labels(
        project_id, video_id,
        intersection_name=body.intersection_name,
        recording_start_datetime=body.recording_start_datetime,
        camera_label=body.camera_label,
    )
    return get_video(project_id, video_id)


@router.post("/projects/{project_id}/videos/save-labels")
def save_labels(project_id: str):
    """Derive intersections + cameras from the videos' current labels.

    Grouping: groupby(intersection_name_label, date_part(recording_start_datetime)),
    then groupby(camera_label_parsed) within each intersection-day. Each unique
    group becomes (or reuses) an intersection row and a camera row, and each
    video is linked to its camera.

    Videos with no intersection_name_label are skipped (the user must fill
    that field for them to participate).

    Returns the resulting list of intersections plus 'created' / 'existed'
    counts so the frontend can give honest feedback ('Built 3 new, kept 2
    existing') instead of leaving the CTA looking like it might duplicate.
    """
    _require_project(project_id)
    videos = list_videos(project_id)

    # Snapshot pre-existing rows so we can report what's new vs reused.
    before_intersection_ids = {
        i["intersection_id"] for i in list_intersections(project_id)
    }
    before_camera_ids: set[int] = set()
    for i in list_intersections(project_id):
        for c in list_cameras(project_id, i["intersection_id"]):
            before_camera_ids.add(c["camera_id"])

    skipped = 0
    for v in videos:
        intersection_name = (v.get("intersection_name_label") or "").strip()
        camera_label = (v.get("camera_label_parsed") or "").strip() or "Camera 1"
        start_dt = v.get("recording_start_datetime") or v.get("recording_start_time")
        if not intersection_name or not start_dt:
            skipped += 1
            continue
        date_part = start_dt[:10]   # YYYY-MM-DD
        iid = upsert_intersection(project_id, intersection_name, date_part)
        cid = upsert_camera(project_id, iid, camera_label)
        link_video_to_camera(project_id, v["video_id"], cid)

    # Mark the project as v3-initialized so the legacy auto-bootstrap never
    # fires for it (e.g. after a user deletes an intersection and its videos
    # become unlinked). Only when at least one video was actually linked.
    if len(videos) - skipped > 0:
        set_project_info(project_id, "v3_initialized", "1")

    after_intersections = list_intersections(project_id)
    after_camera_ids: set[int] = set()
    for i in after_intersections:
        for c in list_cameras(project_id, i["intersection_id"]):
            after_camera_ids.add(c["camera_id"])

    created_intersection_ids = sorted(
        {i["intersection_id"] for i in after_intersections} - before_intersection_ids
    )
    created_camera_ids = sorted(after_camera_ids - before_camera_ids)

    return {
        "intersections": after_intersections,
        "intersections_created": len(created_intersection_ids),
        "intersections_existed": len(before_intersection_ids & {
            i["intersection_id"] for i in after_intersections
        }),
        "cameras_created": len(created_camera_ids),
        "cameras_existed": len(before_camera_ids & after_camera_ids),
        "videos_attached": len(videos) - skipped,
        "videos_skipped": skipped,
    }


@router.delete("/projects/{project_id}/videos/{video_id}")
def delete_video(
    project_id: str,
    video_id: int,
    confirm: bool = Query(False),
):
    """Remove a video. If it has processed events, requires confirm=true."""
    _require_project(project_id)
    v = _require_video(project_id, video_id)

    conn = get_connection(project_id)
    try:
        event_count = conn.execute(
            "SELECT COUNT(*) FROM vehicle_events WHERE video_id = ?",
            (video_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    if event_count > 0 and not confirm:
        return {
            "warning": f"This will delete {event_count} processed event(s).",
            "confirm_required": True,
            "event_count": event_count,
            "video_id": video_id,
            "filename": v["filename"],
        }

    remove_video(project_id, video_id)
    return {"deleted": True, "video_id": video_id}


@router.put("/projects/{project_id}/videos/{video_id}/start_time")
def put_start_time(project_id: str, video_id: int, body: StartTimeBody):
    """Set or clear the recording_start_time for a video."""
    _require_project(project_id)
    _require_video(project_id, video_id)
    set_video_recording_start_time(project_id, video_id, body.recording_start_time)
    return get_video(project_id, video_id)


@router.get("/projects/{project_id}/videos/{video_id}/frame")
def get_video_frame(
    project_id: str,
    video_id: int,
    seconds: float = Query(default=0.0, ge=0),
):
    """Return a JPEG of the video at the requested time offset."""
    _require_project(project_id)
    v = _require_video(project_id, video_id)

    try:
        jpeg_bytes = get_frame_at_time(v["path"], seconds)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Video file no longer accessible")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return Response(content=jpeg_bytes, media_type="image/jpeg")


@router.put("/projects/{project_id}/videos/{video_id}/order")
def put_order(project_id: str, video_id: int, body: OrderBody):
    """Reassign the sort_order of a video (used to reorder the processing sequence)."""
    _require_project(project_id)
    _require_video(project_id, video_id)

    conn = get_connection(project_id)
    try:
        conn.execute(
            "UPDATE videos SET sort_order = ? WHERE video_id = ?",
            (body.sort_order, video_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_video(project_id, video_id)
