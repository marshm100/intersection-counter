from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import uuid
import shutil
from datetime import datetime, timezone

from backend.config import PROJECTS_DIR
from backend.database import (
    get_connection, get_project_dir,
    set_project_info, get_project_info, get_all_project_info
)
from backend.routers.processing import stop_pipeline

router = APIRouter()


class CreateProjectRequest(BaseModel):
    name: str


class RenameProjectRequest(BaseModel):
    name: str


class UpdateSettingsRequest(BaseModel):
    num_legs: int | None = None
    video_start_time: str | None = None


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
            projects.append({
                "project_id": d.name,
                "name": info.get("project_name", ""),
                "status": info.get("status", ""),
                "created_at": info.get("created_at", ""),
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


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    stop_pipeline(project_id)
    shutil.rmtree(project_dir)
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
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    if req.num_legs is not None:
        set_project_info(project_id, "num_legs", str(req.num_legs))
    if req.video_start_time is not None:
        set_project_info(project_id, "video_start_time", req.video_start_time)
    return {"status": "ok"}
