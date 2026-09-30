"""Journey-label API for the labelling page (/static/journeys.html).

Clips are defined by scripts/journey_clips.py; the page lists them, plays
the clip, and posts one row per labelled vehicle. Dev-validation only
(docs/research_tracking_2026-09-29.md phase 0).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import PROJECTS_DIR
from backend.database import get_video
from backend.services import journey_labels as jl

router = APIRouter()


def _require_project(project_id: str) -> None:
    d = PROJECTS_DIR / project_id
    if not d.exists() or not (d / "project.db").exists():
        raise HTTPException(status_code=404, detail="Project not found")


def _require_clip(project_id: str, clip_id: str) -> dict:
    _require_project(project_id)
    clip = jl.get_clip(project_id, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip


class JourneyIn(BaseModel):
    entry_leg_id: Optional[int] = None
    entry_leg_label: Optional[str] = None
    entry_frame: Optional[int] = None
    entry_x: Optional[float] = None
    entry_y: Optional[float] = None
    exit_leg_id: Optional[int] = None
    exit_leg_label: Optional[str] = None
    exit_frame: Optional[int] = None
    exit_x: Optional[float] = None
    exit_y: Optional[float] = None
    vehicle_class: str = "car"
    note: str = ""


@router.get("/projects/{project_id}/journey-clips")
def list_journey_clips(project_id: str):
    _require_project(project_id)
    clips = jl.list_clips(project_id)
    for c in clips:
        v = get_video(project_id, c["video_id"]) or {}
        c["video_width"] = v.get("width")
        c["video_height"] = v.get("height")
    return {"clips": clips, "classes": list(jl.CLASSES)}


@router.get("/projects/{project_id}/journey-clips/{clip_id}")
def get_journey_clip(project_id: str, clip_id: str):
    return _require_clip(project_id, clip_id)


@router.get("/projects/{project_id}/journey-clips/{clip_id}/labels")
def list_journey_labels(project_id: str, clip_id: str):
    _require_clip(project_id, clip_id)
    return {"labels": jl.list_labels(project_id, clip_id)}


@router.post("/projects/{project_id}/journey-clips/{clip_id}/labels")
def add_journey_label(project_id: str, clip_id: str, body: JourneyIn):
    _require_clip(project_id, clip_id)
    try:
        return jl.add_label(project_id, clip_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/projects/{project_id}/journey-clips/{clip_id}/labels/{label_id}")
def delete_journey_label(project_id: str, clip_id: str, label_id: int):
    _require_clip(project_id, clip_id)
    if not jl.delete_label(project_id, clip_id, label_id):
        raise HTTPException(status_code=404, detail="Label not found")
    return {"deleted": label_id}
