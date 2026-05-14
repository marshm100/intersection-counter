from fastapi import APIRouter, HTTPException
from backend.database import get_connection, get_project_info
from backend.config import DEFAULT_INTERVAL_MINUTES

router = APIRouter()


@router.get("/projects/{project_id}/dashboard")
def get_dashboard(project_id: str):
    interval_minutes = int(get_project_info(project_id, "interval_minutes") or DEFAULT_INTERVAL_MINUTES)

    conn = get_connection(project_id)
    try:
        # --- TMC matrix ---
        rows = conn.execute(
            """
            SELECT l.label AS leg_label, ve.movement, COUNT(*) AS cnt
            FROM vehicle_events ve
            JOIN legs l ON ve.origin_leg_id = l.leg_id
            GROUP BY ve.origin_leg_id, ve.movement
            ORDER BY l.sort_order
            """
        ).fetchall()

        # Pivot by leg
        leg_map: dict = {}
        for leg_label, movement, cnt in rows:
            if leg_label not in leg_map:
                leg_map[leg_label] = {"leg_label": leg_label, "through": 0, "left": 0, "right": 0, "u_turn": 0, "other": 0}
            key = movement if movement in ("through", "left", "right", "u_turn") else "other"
            leg_map[leg_label][key] += cnt

        tmc_matrix = []
        for entry in leg_map.values():
            entry["total"] = entry["through"] + entry["left"] + entry["right"] + entry["u_turn"] + entry["other"]
            tmc_matrix.append(entry)

        # --- Vehicle time series ---
        v_rows = conn.execute(
            """
            SELECT CAST(timestamp_video / (? * 60) AS INTEGER) AS bucket, COUNT(*) AS cnt
            FROM vehicle_events GROUP BY bucket ORDER BY bucket
            """,
            (interval_minutes,),
        ).fetchall()

        # --- Totals ---
        total_vehicles = conn.execute("SELECT COUNT(*) FROM vehicle_events").fetchone()[0]
    finally:
        conn.close()

    # Build aligned time series
    v_dict = {bucket: cnt for bucket, cnt in v_rows}

    all_buckets = sorted(v_dict.keys())

    # Determine label format from max bucket value
    max_seconds = (max(all_buckets) + 1) * interval_minutes * 60 if all_buckets else 0
    use_hhmm = max_seconds >= 3600

    def _bucket_label(b: int) -> str:
        total_sec = b * interval_minutes * 60
        if use_hhmm:
            h = total_sec // 3600
            m = (total_sec % 3600) // 60
            return f"{h:02d}:{m:02d}"
        else:
            m = total_sec // 60
            s = total_sec % 60
            return f"{m:02d}:{s:02d}"

    time_series = [
        {
            "interval_start": _bucket_label(b),
            "vehicle_count": v_dict.get(b, 0),
        }
        for b in all_buckets
    ]

    return {
        "tmc_matrix": tmc_matrix,
        "time_series": time_series,
        "totals": {"vehicles": total_vehicles},
        "interval_minutes": interval_minutes,
    }
