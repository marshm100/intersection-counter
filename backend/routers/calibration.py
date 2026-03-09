import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from backend.database import get_connection

router = APIRouter()


class LegInput(BaseModel):
    label: str
    cardinal_direction: str
    sort_order: int
    origin_zone: List[List[float]]  # [[x1,y1],[x2,y2]]
    reference_heading: float


class CalibrationSaveRequest(BaseModel):
    legs: List[LegInput]


@router.get("/projects/{project_id}/calibration")
def get_calibration(project_id: str):
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT leg_id, label, cardinal_direction, sort_order, origin_zone, reference_heading "
            "FROM legs ORDER BY sort_order"
        ).fetchall()
    finally:
        conn.close()

    legs = []
    for row in rows:
        legs.append({
            "leg_id": row[0],
            "label": row[1],
            "cardinal_direction": row[2],
            "sort_order": row[3],
            "origin_zone": json.loads(row[4]) if row[4] else None,
            "reference_heading": row[5],
        })
    return {"legs": legs}


@router.put("/projects/{project_id}/calibration/legs")
def save_calibration(project_id: str, body: CalibrationSaveRequest):
    if not body.legs:
        raise HTTPException(status_code=422, detail="At least one leg is required.")

    conn = get_connection(project_id)
    try:
        conn.execute("DELETE FROM legs")
        for leg in body.legs:
            conn.execute(
                "INSERT INTO legs (label, cardinal_direction, sort_order, origin_zone, reference_heading) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    leg.label,
                    leg.cardinal_direction,
                    leg.sort_order,
                    json.dumps(leg.origin_zone),
                    leg.reference_heading,
                ),
            )
        conn.commit()
        rows = conn.execute(
            "SELECT leg_id, label, cardinal_direction, sort_order, origin_zone, reference_heading "
            "FROM legs ORDER BY sort_order"
        ).fetchall()
    finally:
        conn.close()

    saved = []
    for row in rows:
        saved.append({
            "leg_id": row[0],
            "label": row[1],
            "cardinal_direction": row[2],
            "sort_order": row[3],
            "origin_zone": json.loads(row[4]) if row[4] else None,
            "reference_heading": row[5],
        })
    return {"legs": saved}
