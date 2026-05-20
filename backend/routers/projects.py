from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
import sqlite3
import time
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path

from backend.config import PROJECTS_DIR
from backend.database import (
    get_connection, get_project_dir,
    set_project_info, get_project_info, get_all_project_info
)
from backend.routers.processing import stop_pipeline
from backend.services.video_service import get_video_info

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateProjectRequest(BaseModel):
    name: str


class RenameProjectRequest(BaseModel):
    name: str


class UpdateSettingsRequest(BaseModel):
    num_legs: int | None = None
    video_start_time: str | None = None
    processing_mode: str | None = None   # any key in PROCESSING_MODES (fast | balanced | accurate)


@router.get("/projects")
async def list_projects():
    projects = []
    if not PROJECTS_DIR.exists():
        return projects
    for d in PROJECTS_DIR.iterdir():
        if not d.is_dir():
            continue
        db_file = d / "project.db"
        if not db_file.exists():
            continue
        try:
            info = get_all_project_info(d.name)
            conn = get_connection(d.name)
            try:
                # v3 stores videos in the videos table; v2 stored the path in
                # project_info["video_path"]. A project has video if either is
                # populated — without the videos-table check, every v3 project
                # was tagged 'needs video' on the home screen.
                video_count = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
                has_video = bool(info.get("video_path")) or video_count > 0
                has_legs = conn.execute("SELECT COUNT(*) FROM legs").fetchone()[0] > 0
            finally:
                conn.close()
            projects.append({
                "project_id": d.name,
                "name": info.get("project_name", ""),
                "status": info.get("status", ""),
                "created_at": info.get("created_at", ""),
                "has_video": has_video,
                "has_legs": has_legs,
            })
        except Exception:
            continue
    projects.sort(key=lambda p: p["created_at"], reverse=True)
    return projects


@router.post("/projects")
async def create_project(req: CreateProjectRequest):
    project_id = uuid.uuid4().hex[:8]
    conn = get_connection(project_id)
    conn.close()
    now = datetime.now(timezone.utc).isoformat()
    set_project_info(project_id, "project_name", req.name)
    set_project_info(project_id, "created_at", now)
    set_project_info(project_id, "status", "created")
    return {"project_id": project_id, "name": req.name}


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    info = get_all_project_info(project_id)
    info["project_id"] = project_id
    return info


def _release_sqlite_wal(db_path: Path) -> None:
    """Drop WAL/SHM sidecars so Windows will let us rmtree the project dir.

    Why: sqlite WAL memory-maps `.db-wal` and `.db-shm` and Windows defers
    unlink until the maps are gone — naive rmtree leaves an empty directory
    that can't be removed. Checkpointing + switching to DELETE journal mode
    closes the maps deterministically.
    """
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("WAL checkpoint failed for %s: %s", db_path, e)


def _rmtree_with_retry(path: Path, attempts: int = 4, backoff_s: float = 0.1) -> None:
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except (PermissionError, OSError) as e:
            last_exc = e
            time.sleep(backoff_s * (2 ** i))
    if path.exists():
        try:
            path.rmdir()
            return
        except OSError:
            pass
        raise last_exc if last_exc else OSError(f"Could not remove {path}")


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    stop_pipeline(project_id)
    _release_sqlite_wal(project_dir / "project.db")
    try:
        _rmtree_with_retry(project_dir)
    except OSError as e:
        logger.error("Failed to delete project dir %s: %s", project_dir, e)
        raise HTTPException(status_code=500, detail=f"Could not remove project directory: {e}")
    return {"deleted": True}


@router.put("/projects/{project_id}/name")
async def rename_project(project_id: str, req: RenameProjectRequest):
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    set_project_info(project_id, "project_name", req.name)
    return {"project_id": project_id, "name": req.name}


@router.put("/projects/{project_id}/settings")
async def update_settings(project_id: str, req: UpdateSettingsRequest):
    from backend.config import PROCESSING_MODES

    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    if req.num_legs is not None:
        set_project_info(project_id, "num_legs", str(req.num_legs))
    if req.video_start_time is not None:
        set_project_info(project_id, "video_start_time", req.video_start_time)
    if req.processing_mode is not None:
        if req.processing_mode not in PROCESSING_MODES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown processing_mode '{req.processing_mode}'. "
                       f"Expected one of: {sorted(PROCESSING_MODES.keys())}",
            )
        set_project_info(project_id, "processing_mode", req.processing_mode)
    return {"status": "ok"}


@router.get("/processing-modes")
async def list_processing_modes():
    """Return the list of available processing modes for the frontend selector.

    Stripped down to the fields the UI needs (label, description) — we don't
    expose model/imgsz/detection_skip via the API since those are
    implementation details the user shouldn't tune directly.
    """
    from backend.config import DEFAULT_PROCESSING_MODE, PROCESSING_MODES

    return {
        "default": DEFAULT_PROCESSING_MODE,
        "modes": [
            {
                "key": key,
                "label": cfg["label"],
                "description": cfg["description"],
            }
            for key, cfg in PROCESSING_MODES.items()
        ],
    }


class BulkImportRequest(BaseModel):
    paths: list[str]


@router.post("/projects/bulk-import")
async def bulk_import(req: BulkImportRequest):
    """Create one project per video file. Returns created projects and errors."""
    created: list[dict] = []
    errors: list[dict] = []
    used_names: set[str] = set()

    for path in req.paths:
        stem = Path(path).stem
        name = stem
        counter = 2
        while name in used_names:
            name = f"{stem} ({counter})"
            counter += 1
        used_names.add(name)

        try:
            info = get_video_info(path)
        except Exception as e:
            errors.append({"path": path, "error": str(e)})
            continue

        project_id = uuid.uuid4().hex[:8]
        conn = get_connection(project_id)
        conn.close()
        now = datetime.now(timezone.utc).isoformat()
        set_project_info(project_id, "project_name", name)
        set_project_info(project_id, "created_at", now)
        set_project_info(project_id, "status", "created")

        # Store video metadata (same as video.py:set_video)
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
        if info.get("creation_time") is not None:
            set_project_info(project_id, "video_creation_time", info["creation_time"])

        set_project_info(project_id, "status", "idle")

        created.append({"project_id": project_id, "name": name, "video_path": path})
        logger.info("Bulk import: created project %s (%s) from %s", project_id, name, path)

    return {"created": created, "errors": errors}
