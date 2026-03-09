import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from pathlib import Path

from backend.config import PROJECTS_DIR
from backend.database import (
    get_project_dir, get_db_path,
    set_project_info, get_project_info,
)
from backend.services.video_service import (
    get_video_info, get_frame_at_time,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SetVideoRequest(BaseModel):
    path: str
    confirm: bool = False


def _require_project(project_id: str) -> None:
    """Check project exists (directory + database). Raise 404 if not."""
    project_dir = PROJECTS_DIR / project_id
    db_path = project_dir / "project.db"
    if not project_dir.exists() or not db_path.exists():
        raise HTTPException(status_code=404, detail="Project not found")


def _open_file_dialog() -> str | None:
    """Open native file dialog. Returns path or None if unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            filetypes=[("MP4 Video", "*.mp4"), ("All Files", "*.*")]
        )
        root.destroy()
        return path if path else None
    except Exception:
        return None


@router.post("/projects/{project_id}/video")
async def set_video(project_id: str, req: SetVideoRequest):
    _require_project(project_id)

    try:
        info = get_video_info(req.path)
    except FileNotFoundError:
        logger.error("Video file not found: %s", req.path)
        raise HTTPException(status_code=400, detail=f"Video file not found: {req.path}")
    except ValueError as e:
        logger.error("Cannot open video %s: %s", req.path, e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error loading video %s", req.path)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

    existing_path = get_project_info(project_id, "video_path")
    if existing_path and existing_path != info["path"] and not req.confirm:
        return {
            "warning": "This will replace the existing video and all associated data",
            "confirm_required": True,
            "existing_path": existing_path,
            "new_path": info["path"],
        }

    set_project_info(project_id, "video_path", info["path"])
    set_project_info(project_id, "video_filename", info["filename"])
    set_project_info(project_id, "video_width", str(info["width"]))
    set_project_info(project_id, "video_height", str(info["height"]))
    set_project_info(project_id, "video_fps", str(info["fps"]))
    set_project_info(project_id, "video_total_frames", str(info["total_frames"]))
    set_project_info(project_id, "video_duration_seconds", str(info["duration_seconds"]))
    set_project_info(project_id, "video_duration_formatted", info["duration_formatted"])
    set_project_info(project_id, "video_file_size_bytes", str(info["file_size_bytes"]))
    set_project_info(project_id, "video_file_size_formatted", info["file_size_formatted"])
    set_project_info(project_id, "video_codec", info["codec"])
    if info["creation_time"] is not None:
        set_project_info(project_id, "video_creation_time", info["creation_time"])

    # Reset status to idle so stale error/complete states don't persist
    set_project_info(project_id, "status", "idle")

    return info


@router.get("/projects/{project_id}/video")
async def get_video(project_id: str):
    _require_project(project_id)

    video_path = get_project_info(project_id, "video_path")
    if not video_path:
        raise HTTPException(status_code=404, detail="No video set for this project")

    try:
        info = get_video_info(video_path)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Video file no longer accessible")

    return info


@router.get("/projects/{project_id}/video/frame")
async def get_frame(project_id: str, seconds: float = Query(default=0.0, ge=0)):
    _require_project(project_id)

    video_path = get_project_info(project_id, "video_path")
    if not video_path:
        raise HTTPException(status_code=404, detail="No video set for this project")

    try:
        jpeg_bytes = get_frame_at_time(video_path, seconds)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Video file no longer accessible")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return Response(content=jpeg_bytes, media_type="image/jpeg")


@router.post("/projects/{project_id}/video/browse")
async def browse_video(project_id: str):
    _require_project(project_id)

    path = await asyncio.to_thread(_open_file_dialog)
    return {"path": path}
