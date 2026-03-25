import math
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.database import get_connection

router = APIRouter()

VALID_MOVEMENTS = {"through", "left", "right", "u_turn"}
VALID_CLASSES = {"car", "motorcycle", "bus", "truck", "unknown"}
_PATCH_COLUMNS = {"movement": "movement", "vehicle_class": "vehicle_class"}

_EVENT_FIELDS = (
    "event_id", "vehicle_track_id", "origin_leg_id", "leg_label",
    "movement", "vehicle_class", "fhwa_class", "detection_confidence",
    "trajectory_confidence", "timestamp_video", "timestamp_real",
    "frame_number", "manually_edited",
)


def _row_to_dict(row, fields=_EVENT_FIELDS) -> dict:
    return dict(zip(fields, row))


@router.get("/projects/{project_id}/review")
def get_review(
    project_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    leg_id: Optional[int] = Query(None),
    movement: Optional[str] = Query(None),
    low_confidence: Optional[bool] = Query(None),
):
    conn = get_connection(project_id)
    try:
        conditions = []
        params: list = []

        if leg_id is not None:
            conditions.append("ve.origin_leg_id = ?")
            params.append(leg_id)
        if movement is not None:
            conditions.append("ve.movement = ?")
            params.append(movement)
        if low_confidence:
            conditions.append("ve.trajectory_confidence < 0.5")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        total = conn.execute(
            f"""
            SELECT COUNT(*) FROM vehicle_events ve
            JOIN legs l ON ve.origin_leg_id = l.leg_id
            {where}
            """,
            params,
        ).fetchone()[0]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT ve.event_id, ve.vehicle_track_id, ve.origin_leg_id, l.label AS leg_label,
                   ve.movement, ve.vehicle_class, ve.fhwa_class, ve.detection_confidence,
                   ve.trajectory_confidence, ve.timestamp_video, ve.timestamp_real,
                   ve.frame_number, ve.manually_edited
            FROM vehicle_events ve
            JOIN legs l ON ve.origin_leg_id = l.leg_id
            {where}
            ORDER BY ve.event_id
            LIMIT ? OFFSET ?
            """,
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


@router.patch("/projects/{project_id}/review/{event_id}")
def patch_event(project_id: str, event_id: int, body: PatchEventBody):
    if body.movement is not None and body.movement not in VALID_MOVEMENTS:
        raise HTTPException(status_code=422, detail=f"Invalid movement: {body.movement}")
    if body.vehicle_class is not None and body.vehicle_class not in VALID_CLASSES:
        raise HTTPException(status_code=422, detail=f"Invalid vehicle_class: {body.vehicle_class}")

    conn = get_connection(project_id)
    try:
        # Check event exists
        existing = conn.execute("SELECT event_id FROM vehicle_events WHERE event_id = ?", (event_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Event not found")

        sets = []
        params = []
        for field, column in _PATCH_COLUMNS.items():
            value = getattr(body, field)
            if value is not None:
                sets.append(f"{column} = ?")
                params.append(value)

        if sets:
            sets.append("manually_edited = 1")
            params.append(event_id)
            conn.execute(
                "UPDATE vehicle_events SET " + ", ".join(sets) + " WHERE event_id = ?",
                params,
            )
            conn.commit()

        row = conn.execute(
            """
            SELECT ve.event_id, ve.vehicle_track_id, ve.origin_leg_id, l.label AS leg_label,
                   ve.movement, ve.vehicle_class, ve.fhwa_class, ve.detection_confidence,
                   ve.trajectory_confidence, ve.timestamp_video, ve.timestamp_real,
                   ve.frame_number, ve.manually_edited
            FROM vehicle_events ve
            JOIN legs l ON ve.origin_leg_id = l.leg_id
            WHERE ve.event_id = ?
            """,
            (event_id,),
        ).fetchone()
    finally:
        conn.close()

    return _row_to_dict(row)
