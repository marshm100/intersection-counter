import json
import math
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from backend.database import get_connection, get_project_info

router = APIRouter()

VALID_MOVEMENTS = {"through", "left", "right", "u_turn"}
VALID_CLASSES = {"car", "motorcycle", "bus", "truck", "unknown"}

_EVENT_FIELDS = (
    "event_id", "vehicle_track_id", "origin_leg_id", "leg_label",
    "movement", "vehicle_class", "fhwa_class", "detection_confidence",
    "trajectory_confidence", "timestamp_video", "timestamp_real",
    "frame_number", "manually_edited", "rejected",
)

_SELECT_EVENT = """
    ve.event_id, ve.vehicle_track_id, ve.origin_leg_id,
    l.label AS leg_label, ve.movement, ve.vehicle_class, ve.fhwa_class,
    ve.detection_confidence, ve.trajectory_confidence,
    ve.timestamp_video, ve.timestamp_real, ve.frame_number,
    ve.manually_edited, ve.rejected
"""


def _row_to_dict(row, fields=_EVENT_FIELDS) -> dict:
    return dict(zip(fields, row))


@router.get("/projects/{project_id}/review")
def get_review(
    project_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    leg_id: Optional[int] = Query(None),
    movement: Optional[str] = Query(None),
    vehicle_class: Optional[str] = Query(None),
    low_confidence: Optional[bool] = Query(None),
    manually_edited: Optional[bool] = Query(None),
    rejected: Optional[bool] = Query(None),
):
    conn = get_connection(project_id)
    try:
        conditions: list[str] = []
        params: list = []

        if leg_id is not None:
            conditions.append("ve.origin_leg_id = ?")
            params.append(leg_id)
        if movement is not None:
            conditions.append("ve.movement = ?")
            params.append(movement)
        if vehicle_class is not None:
            conditions.append("ve.vehicle_class = ?")
            params.append(vehicle_class)
        if low_confidence:
            conditions.append("ve.trajectory_confidence < 0.5")
        if manually_edited is not None:
            conditions.append("ve.manually_edited = ?")
            params.append(1 if manually_edited else 0)
        if rejected is not None:
            conditions.append("ve.rejected = ?")
            params.append(1 if rejected else 0)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        total = conn.execute(
            f"""SELECT COUNT(*) FROM vehicle_events ve
                JOIN legs l ON ve.origin_leg_id = l.leg_id
                {where}""",
            params,
        ).fetchone()[0]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""SELECT {_SELECT_EVENT}
                FROM vehicle_events ve
                JOIN legs l ON ve.origin_leg_id = l.leg_id
                {where}
                ORDER BY ve.event_id
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()
    finally:
        conn.close()

    events = [_row_to_dict(r) for r in rows]
    pages = max(1, math.ceil(total / page_size))

    return {"events": events, "total": total, "page": page, "page_size": page_size, "pages": pages}


class PatchEventBody(BaseModel):
    vehicle_class: Optional[str] = None
    movement: Optional[str] = None
    rejected: Optional[bool] = None


@router.patch("/projects/{project_id}/review/{event_id}")
def patch_event(project_id: str, event_id: int, body: PatchEventBody):
    if body.movement is not None and body.movement not in VALID_MOVEMENTS:
        raise HTTPException(status_code=422, detail=f"Invalid movement: {body.movement}")
    if body.vehicle_class is not None and body.vehicle_class not in VALID_CLASSES:
        raise HTTPException(status_code=422, detail=f"Invalid vehicle_class: {body.vehicle_class}")

    conn = get_connection(project_id)
    try:
        existing = conn.execute(
            "SELECT event_id FROM vehicle_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Event not found")

        updates: list[str] = []
        params: list = []
        if body.movement is not None:
            updates.append("movement = ?")
            params.append(body.movement)
        if body.vehicle_class is not None:
            updates.append("vehicle_class = ?")
            params.append(body.vehicle_class)
        if body.rejected is not None:
            updates.append("rejected = ?")
            params.append(1 if body.rejected else 0)

        if updates:
            updates.append("manually_edited = 1")
            params.append(event_id)
            conn.execute(
                f"UPDATE vehicle_events SET {', '.join(updates)} WHERE event_id = ?",
                params,
            )
            conn.commit()

        row = conn.execute(
            f"""SELECT {_SELECT_EVENT}
                FROM vehicle_events ve
                JOIN legs l ON ve.origin_leg_id = l.leg_id
                WHERE ve.event_id = ?""",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()

    return _row_to_dict(row)


@router.get("/projects/{project_id}/review/{event_id}/preview")
def event_preview(
    project_id: str, event_id: int,
    width: int = Query(640, ge=160, le=1920),
):
    """Return a JPEG of the event's video frame with its trajectory drawn."""
    conn = get_connection(project_id)
    try:
        row = conn.execute(
            "SELECT frame_number, trajectory_data FROM vehicle_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    frame_number, trajectory_json = row

    video_path = get_project_info(project_id, "video_path")
    if not video_path:
        raise HTTPException(status_code=404, detail="No video set for this project")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail="Video file not accessible")
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_number))
        ret, frame = cap.read()
        if not ret or frame is None:
            raise HTTPException(status_code=400, detail="Could not read frame")
    finally:
        cap.release()

    try:
        trajectory = json.loads(trajectory_json) if trajectory_json else []
    except Exception:
        trajectory = []

    if len(trajectory) >= 2:
        pts = np.array([[int(p[0]), int(p[1])] for p in trajectory], dtype=np.int32)
        cv2.polylines(frame, [pts], isClosed=False, color=(255, 200, 0), thickness=3)
        last = trajectory[-1]
        cv2.circle(frame, (int(last[0]), int(last[1])), 8, (0, 0, 255), -1)

    h, w = frame.shape[:2]
    if w > width:
        new_h = int(h * width / w)
        frame = cv2.resize(frame, (width, new_h), interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode preview")
    return Response(content=buf.tobytes(), media_type="image/jpeg")
