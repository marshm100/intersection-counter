"""Hand-count API for /static/handcount.html. DEV-validation only (a person counts one movement on the video to
check a reference count). One JSON file per session at data/projects/<pid>/hand_counts/<session>.json; no DB schema."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import backend.config as config

router = APIRouter()
_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _project_dir(project_id: str) -> Path:
    d = config.PROJECTS_DIR / project_id
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id) or not (d / "project.db").exists():
        raise HTTPException(status_code=404, detail="Project not found")
    return d


def _session_path(project_id: str, session: str) -> Path:
    if not _SESSION.fullmatch(session):
        raise HTTPException(status_code=400, detail="session: letters, digits, - and _ only")
    return _project_dir(project_id) / "hand_counts" / f"{session}.json"


class Tap(BaseModel):
    t: float                 # video currentTime, seconds from the file start
    kind: str
    x: float | None = None   # pointer on the frame (video pixels) when the key was pressed, if over the video
    y: float | None = None


class SessionIn(BaseModel):
    video_id: int
    from_wall: str
    to_wall: str
    taps: list[Tap]
    note: str = ""


@router.get("/projects/{project_id}/hand-counts/video/{video_id}")
def hand_count_video(project_id: str, video_id: int):
    d = _project_dir(project_id)
    con = sqlite3.connect(f"file:{d / 'project.db'}?mode=ro", uri=True)
    try:
        r = con.execute("SELECT camera_id, fps, recording_start_datetime, recording_start_time FROM videos "
                        "WHERE video_id=?", (video_id,)).fetchone()
    finally:
        con.close()
    if r is None:
        raise HTTPException(status_code=404, detail="Video not found")
    start = r[2] or r[3]
    if not start:
        raise HTTPException(status_code=409, detail="Video has no recording start time")
    return {"video_id": video_id, "camera_id": r[0], "fps": r[1], "recording_start": start}


@router.get("/projects/{project_id}/hand-counts/{session}")
def get_hand_count(project_id: str, session: str):
    p = _session_path(project_id, session)
    if not p.exists():
        return {"session": session, "taps": [], "exists": False}
    return {**json.loads(p.read_text(encoding="utf-8")), "exists": True}


@router.put("/projects/{project_id}/hand-counts/{session}")
def put_hand_count(project_id: str, session: str, body: SessionIn):
    p = _session_path(project_id, session)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"session": session, **body.model_dump(), "saved_at": datetime.now(timezone.utc).isoformat()}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    tmp.replace(p)
    return {"saved": len(body.taps), "saved_at": doc["saved_at"]}
