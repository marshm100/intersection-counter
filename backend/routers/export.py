import logging
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

from backend.database import get_connection, get_all_project_info
from backend.services.excel_export import generate_tmc_excel
from backend.services.spot_check import export_gate

router = APIRouter()


@router.get("/projects/{project_id}/export/gate")
def export_gate_endpoint(project_id: str):
    """Project-level export readiness (MASTER_PLAN §3-A): the QA acceptance gate
    aggregated across intersections plus the bank/classification preconditions.
    The export page renders this; `blocking=true` means the download is withheld
    unless the operator passes ?override=true."""
    return export_gate(project_id)


@router.get("/projects/{project_id}/export/preview")
def export_preview(project_id: str):
    """Return the TMC matrix + metadata as JSON for preview before download."""
    info = get_all_project_info(project_id)

    conn = get_connection(project_id)
    try:
        legs = conn.execute(
            "SELECT leg_id, label, cardinal_direction, sort_order FROM legs ORDER BY sort_order"
        ).fetchall()
        # Aggregate in SQL rather than fetching every event row into Python: the
        # DB is on a OneDrive path where materializing ~90k rows took ~50s; the
        # grouped query returns a few dozen (origin_leg, movement) cells. Same
        # counting set as before (all events, no rejected filter).
        counts = conn.execute(
            "SELECT origin_leg_id, movement, COUNT(*) FROM vehicle_events "
            "GROUP BY origin_leg_id, movement"
        ).fetchall()
    finally:
        conn.close()

    tmc: dict = {}
    for row in legs:
        tmc[row[0]] = {"leg_id": row[0], "label": row[1], "through": 0, "left": 0, "right": 0, "u_turn": 0, "other": 0, "total": 0}

    for origin_leg_id, movement, n in counts:
        if origin_leg_id not in tmc:
            tmc[origin_leg_id] = {
                "leg_id": origin_leg_id,
                "label": f"Leg {origin_leg_id}",
                "through": 0, "left": 0, "right": 0, "u_turn": 0, "other": 0, "total": 0,
            }
        if movement in ("through", "left", "right", "u_turn"):
            tmc[origin_leg_id][movement] += n
        else:
            tmc[origin_leg_id]["other"] += n
        tmc[origin_leg_id]["total"] += n

    matrix = sorted(tmc.values(), key=lambda x: next(
        (r[3] for r in legs if r[0] == x["leg_id"]), 999
    ))

    return {
        "project_name": info.get("project_name", project_id),
        "video_start_time": info.get("video_start_time", ""),
        "tmc_matrix": matrix,
        "total_vehicles": int(sum(v["total"] for v in tmc.values())),
        "leg_count": int(len(legs)),
    }


@router.get("/projects/{project_id}/export/download")
def export_download(project_id: str, override: bool = False):
    """Generate and stream the TMC Excel file as a download attachment.

    Gated (MASTER_PLAN §3-A): if the export gate is blocking (a hard QA fail, a
    missing bank, or empty classification) the download is withheld with HTTP 409
    unless `override=true` — a `review` verdict (e.g. spot count pending) is NOT
    blocking and streams a draft."""
    gate = export_gate(project_id)
    if gate["blocking"] and not override:
        raise HTTPException(status_code=409, detail={
            "message": "Export withheld — the QA gate is not satisfied.",
            "overall": gate["overall"],
            "blocking_reasons": gate["blocking_reasons"],
        })

    info = get_all_project_info(project_id)
    project_name = info.get("project_name", project_id)
    date_str = datetime.now().strftime("%Y%m%d")
    safe_name = "".join(c if c.isalnum() or c in " ._-" else "_" for c in project_name).strip()
    filename = f"TMC_{safe_name}_{date_str}.xlsx"

    tmp_dir = Path(tempfile.gettempdir())
    output_path = tmp_dir / filename

    try:
        generate_tmc_excel(project_id, output_path)
    except Exception as exc:
        logger.error("Export failed for project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail="Export failed. See server logs for details.") from exc

    return FileResponse(
        path=str(output_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
