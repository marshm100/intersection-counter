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
    list_videos, remove_video, set_video_recording_start_time,
)
from backend.services.video_service import get_frame_at_time, get_video_info

router = APIRouter()


class AddVideoBody(BaseModel):
    path: str


class StartTimeBody(BaseModel):
    recording_start_time: Optional[str] = None


class OrderBody(BaseModel):
    sort_order: int


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
    """Attach a video file to the project. Idempotent: same path returns existing row."""
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

    vid = add_video(project_id, info)
    return get_video(project_id, vid)


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
