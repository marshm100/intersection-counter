"""Review flag-queue endpoints (Phase B — MASTER_PLAN §3-B).

The two-feeder blind-QA queue. Feeders (backend/services/flag_feeders.py) write
review_flags; this router serves them to the keyboard review UX (Phase C) and
folds remaining work into the acceptance gate (Phase B4).

POST  /projects/{pid}/intersections/{iid}/flags/rebuild   re-derive open flags
GET   /projects/{pid}/intersections/{iid}/flags           the worklist (impact-ordered)
GET   /projects/{pid}/intersections/{iid}/flags/next      one enriched item to review
GET   /projects/{pid}/intersections/{iid}/flags/summary   counts + remaining open impact
PATCH /projects/{pid}/flags/{flag_id}                     set status (accept/dismiss/resolve)
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import PROJECTS_DIR
from backend.database import (
    flag_summary, get_connection, get_flag, get_intersection, list_flags,
    list_videos_for_camera, update_flag_status,
)
from backend.services.flag_feeders import rebuild_flags

router = APIRouter()

# Clip padding (seconds) around an event-anchored flag's timestamp — the looping
# window the review UX seeks to. Matches playback.js's EVENT_TIME_WINDOW_SECONDS.
_CLIP_PAD_SECONDS = 2.0

_ALLOWED_STATUSES = ("open", "accepted", "dismissed", "resolved")


def _require_project(project_id: str) -> None:
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.exists() or not (project_dir / "project.db").exists():
        raise HTTPException(status_code=404, detail="Project not found")


def _require_intersection(project_id: str, intersection_id: int) -> None:
    if get_intersection(project_id, intersection_id) is None:
        raise HTTPException(status_code=404,
            detail=f"intersection {intersection_id} not found")


class FlagStatusBody(BaseModel):
    status: str    # open | accepted | dismissed | resolved


def _enrich(project_id: str, flag: dict) -> dict:
    """Attach the everything-on-one-screen payload the review UX renders.

    For an event-anchored flag: the event's movement/class/confidences,
    trajectory polyline, origin-leg label, and a looping clip window. The event
    may have vanished (re-bank deletes vehicle_events) — then `event` is None and
    the flag is stale; the next rebuild clears it. For a gap flag: the implicated
    interval+approach (already on the flag)."""
    out = dict(flag)
    out["event"] = None
    out["clip"] = None
    eid = flag.get("event_id")
    if eid is not None:
        conn = get_connection(project_id)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT e.event_id, e.camera_id, e.video_id, e.origin_leg_id, "
                "l.label AS leg_label, e.movement, e.vehicle_class, e.fhwa_class, "
                "e.detection_confidence, e.trajectory_confidence, "
                "e.destination_leg_id, e.destination_confidence, "
                "e.destination_posterior_json, e.trajectory_data, "
                "e.timestamp_video, e.rejected "
                "FROM vehicle_events e LEFT JOIN legs l ON l.leg_id = e.origin_leg_id "
                "WHERE e.event_id = ?", (eid,)).fetchone()
        finally:
            conn.close()
        if row is not None:
            ev = {k: row[k] for k in row.keys()}
            out["event"] = ev
            ts = ev.get("timestamp_video")
            if ts is not None:
                out["clip"] = {
                    "video_id": ev.get("video_id"),
                    "start_seconds": max(0.0, float(ts) - _CLIP_PAD_SECONDS),
                    "end_seconds": float(ts) + _CLIP_PAD_SECONDS,
                    "center_seconds": float(ts),
                }
    elif flag.get("interval_start_seconds") is not None and flag.get("camera_id"):
        # Gap flag: no anchor event, so point the clip at the camera's video for
        # the flagged interval (the operator scrubs and adds missed vehicles).
        start = float(flag["interval_start_seconds"])
        end = float(flag.get("interval_end_seconds") or start)
        vids = list_videos_for_camera(project_id, flag["camera_id"])
        chosen = next((v for v in vids
                       if start < float(v.get("duration_seconds") or 1e12)), None)
        chosen = chosen or (vids[0] if vids else None)
        if chosen is not None:
            out["clip"] = {"video_id": chosen["video_id"], "start_seconds": start,
                           "end_seconds": end, "center_seconds": start}
    return out


@router.post("/projects/{project_id}/intersections/{intersection_id}/flags/rebuild")
def post_rebuild_flags(project_id: str, intersection_id: int):
    """Re-derive the open flags for this intersection from both feeders."""
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    return rebuild_flags(project_id, intersection_id)


@router.get("/projects/{project_id}/intersections/{intersection_id}/flags")
def get_flags(project_id: str, intersection_id: int, status: str = "open",
              kind: str | None = None, limit: int | None = None, offset: int = 0):
    """The worklist: flags for this intersection, impact-DESC then oldest-first.
    status='all' returns every status."""
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    flags = list_flags(project_id, intersection_id, status=status, kind=kind,
                       limit=limit, offset=offset)
    return {"flags": flags, "summary": flag_summary(project_id, intersection_id)}


@router.get("/projects/{project_id}/intersections/{intersection_id}/flags/next")
def get_next_flag(project_id: str, intersection_id: int, status: str = "open"):
    """Serve the single highest-impact flag, enriched with everything needed to
    decide it on one screen. `{flag: null}` when the queue is empty."""
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    flags = list_flags(project_id, intersection_id, status=status, limit=1)
    if not flags:
        return {"flag": None, "summary": flag_summary(project_id, intersection_id)}
    return {"flag": _enrich(project_id, flags[0]),
            "summary": flag_summary(project_id, intersection_id)}


@router.get("/projects/{project_id}/intersections/{intersection_id}/flags/summary")
def get_flag_summary(project_id: str, intersection_id: int):
    _require_project(project_id)
    _require_intersection(project_id, intersection_id)
    return flag_summary(project_id, intersection_id)


@router.get("/projects/{project_id}/flags/{flag_id}")
def get_one_flag(project_id: str, flag_id: int):
    """One flag, enriched (event clip / interval clip) — the worklist fetches the
    open LIST for ordering+skip and this per displayed item."""
    _require_project(project_id)
    flag = get_flag(project_id, flag_id)
    if flag is None:
        raise HTTPException(status_code=404, detail=f"flag {flag_id} not found")
    return _enrich(project_id, flag)


@router.patch("/projects/{project_id}/flags/{flag_id}")
def patch_flag(project_id: str, flag_id: int, body: FlagStatusBody):
    """Set a flag's status. Project-scoped (no intersection in the path), like
    /review/{event_id}."""
    _require_project(project_id)
    if body.status not in _ALLOWED_STATUSES:
        raise HTTPException(status_code=422,
            detail=f"status must be one of {_ALLOWED_STATUSES}")
    if get_flag(project_id, flag_id) is None:
        raise HTTPException(status_code=404, detail=f"flag {flag_id} not found")
    update_flag_status(project_id, flag_id, body.status)
    return get_flag(project_id, flag_id)
