import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Font

from backend.database import get_connection, get_all_project_info
from backend.config import DEFAULT_INTERVAL_MINUTES
from backend.services.cardinals import bound_approach
from backend.services.classifier import CLASS_GROUP_ORDER, fhwa_to_class_group

# Miovision-format helpers: approach = full bound-direction name; movement letter.
_BOUND_FULL = {"N": "Northbound", "S": "Southbound", "E": "Eastbound", "W": "Westbound",
               "NE": "Northeastbound", "NW": "Northwestbound",
               "SE": "Southeastbound", "SW": "Southwestbound"}
_MV_LETTER = {"through": "T", "left": "L", "right": "R", "u_turn": "U"}


def _approach_name(cardinal: Optional[str]) -> str:
    b = bound_approach(cardinal)
    return _BOUND_FULL.get(b, b or "Unknown")


def _interval_15(ts_video: float, video_start_time: str) -> str:
    """15-min interval label (Miovision 'YYYY-MM-DD HH:MM:SS') for a video-time
    offset, anchored to the recording start when known."""
    try:
        base = datetime.fromisoformat(video_start_time) if video_start_time else None
    except (ValueError, TypeError):
        base = None
    if base is None:
        base = datetime(2000, 1, 1)
    dt = base + timedelta(seconds=float(ts_video or 0))
    floored = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
    return floored.strftime("%Y-%m-%d %H:%M:%S")


def generate_tmc_excel(project_id: str, output_path: Path) -> Path:
    """
    Queries vehicle_events, builds TMC matrix, writes xlsx.
    Returns the path to the written file.

    Sheet 1 "TMC Summary"  — header rows + TMC matrix with column totals.
    Sheet 2 "Time Series"  — 15-min interval rows (vehicles only — pedestrians out of scope for v2).
    Sheet 3 "Raw Events"   — all vehicle_events rows for QA.

    All cell values are hard-coded integers (int()), no formulas.
    """
    info = get_all_project_info(project_id)
    project_name: str = info.get("project_name", project_id)
    video_start_time: str = info.get("video_start_time", "")
    interval_minutes: int = max(1, int(info.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)))

    conn = get_connection(project_id)
    try:
        legs = conn.execute(
            "SELECT leg_id, label, cardinal_direction, sort_order FROM legs ORDER BY sort_order"
        ).fetchall()

        events = conn.execute(
            "SELECT event_id, vehicle_track_id, origin_leg_id, movement, vehicle_class, "
            "fhwa_class, detection_confidence, trajectory_confidence, "
            "timestamp_video, frame_number, manually_edited "
            "FROM vehicle_events ORDER BY timestamp_video"
        ).fetchall()
    finally:
        conn.close()

    # --- Build TMC matrix ---
    leg_order = [row[0] for row in legs]
    leg_labels = {row[0]: row[1] for row in legs}

    tmc: dict = {}
    for row in legs:
        tmc[row[0]] = {"label": row[1], "through": 0, "left": 0, "right": 0, "u_turn": 0, "total": 0}

    for evt in events:
        leg_id = evt[2]
        movement = evt[3]
        if leg_id not in tmc:
            tmc[leg_id] = {"label": f"Leg {leg_id}", "through": 0, "left": 0, "right": 0, "u_turn": 0, "total": 0}
        if movement in ("through", "left", "right", "u_turn"):
            tmc[leg_id][movement] += 1
        tmc[leg_id]["total"] += 1

    # --- Build time series ---
    vehicle_times = [evt[8] for evt in events]

    time_series = []
    if vehicle_times:
        min_t = min(vehicle_times)
        interval_sec = interval_minutes * 60
        max_t = max(vehicle_times)
        t = min_t
        while t <= max_t:
            end_t = t + interval_sec
            veh_count = int(sum(1 for ts in vehicle_times if t <= ts < end_t))
            label = _format_time(t, video_start_time)
            time_series.append({"label": label, "vehicles": veh_count})
            t = end_t

    # --- Build Miovision-format class-aware data (TMV Data sheet) ---
    # Long format: (interval, approach, movement, class) -> volume, aggregated
    # from the events already in memory (no extra query). Approach = bound
    # direction name; class = Miovision Light/Medium/Articulated bucket.
    leg_card = {row[0]: row[2] for row in legs}    # leg_id -> cardinal (position)
    tmv: dict = defaultdict(int)
    class_totals = {g: 0 for g in CLASS_GROUP_ORDER}
    for evt in events:
        mv = _MV_LETTER.get(evt[3])
        if mv is None:                              # skip non-standard movements
            continue
        approach = _approach_name(leg_card.get(evt[2]))
        cls = fhwa_to_class_group(evt[5])
        tmv[(_interval_15(evt[8], video_start_time), approach, mv, cls)] += 1
        class_totals[cls] += 1

    # --- Build workbook ---
    wb = openpyxl.Workbook()

    # ---- Sheet 1: TMC Summary ----
    ws1 = wb.active
    ws1.title = "TMC Summary"

    ws1["A1"] = "Location"
    ws1["B1"] = project_name
    ws1["A2"] = "Date"
    ws1["B2"] = video_start_time[:10] if video_start_time else datetime.now().strftime("%Y-%m-%d")
    ws1["A3"] = "Study Period"
    ws1["B3"] = "Full Video"

    ws1.append([])  # blank row

    col_headers = ["Leg", "Through", "Left", "Right", "U-Turn", "Total"]
    ws1.append(col_headers)
    header_row_idx = ws1.max_row
    for col in range(1, 7):
        ws1.cell(row=header_row_idx, column=col).font = Font(bold=True)

    col_through = col_left = col_right = col_uturn = col_total = 0
    for leg_id in leg_order:
        if leg_id not in tmc:
            continue
        d = tmc[leg_id]
        ws1.append([
            d["label"],
            int(d["through"]),
            int(d["left"]),
            int(d["right"]),
            int(d["u_turn"]),
            int(d["total"]),
        ])
        col_through += d["through"]
        col_left += d["left"]
        col_right += d["right"]
        col_uturn += d["u_turn"]
        col_total += d["total"]

    # Add any leg_ids seen in events but not in legs table
    for leg_id, d in tmc.items():
        if leg_id not in {row[0] for row in legs}:
            ws1.append([d["label"], int(d["through"]), int(d["left"]), int(d["right"]), int(d["u_turn"]), int(d["total"])])
            col_through += d["through"]
            col_left += d["left"]
            col_right += d["right"]
            col_uturn += d["u_turn"]
            col_total += d["total"]

    ws1.append(["Total", int(col_through), int(col_left), int(col_right), int(col_uturn), int(col_total)])
    totals_idx = ws1.max_row
    for col in range(1, 7):
        ws1.cell(row=totals_idx, column=col).font = Font(bold=True)

    # Vehicle-class (Light/Medium/Articulated) totals — Miovision parity.
    ws1.append([])
    ws1.append(["Vehicle Classes"])
    ws1.cell(row=ws1.max_row, column=1).font = Font(bold=True)
    for g in CLASS_GROUP_ORDER:
        ws1.append([g, int(class_totals[g])])

    # ---- Sheet 2: Time Series ----
    ws2 = wb.create_sheet("Time Series")
    ws2.append(["Time", "Vehicles"])
    for col in range(1, 3):
        ws2.cell(row=1, column=col).font = Font(bold=True)
    for row in time_series:
        ws2.append([row["label"], int(row["vehicles"])])

    # ---- Sheet 3: TMV Data (Miovision long format) ----
    ws_tmv = wb.create_sheet("TMV Data")
    tmv_headers = ["Interval", "Approach", "Movement", "Class", "Volume"]
    ws_tmv.append(tmv_headers)
    for col in range(1, len(tmv_headers) + 1):
        ws_tmv.cell(row=1, column=col).font = Font(bold=True)
    for key in sorted(tmv):
        interval, approach, mv, cls = key
        ws_tmv.append([interval, approach, mv, cls, int(tmv[key])])

    # ---- Sheet 4: Raw Events ----
    ws3 = wb.create_sheet("Raw Events")
    raw_headers = [
        "event_id", "vehicle_track_id", "origin_leg_id", "movement", "vehicle_class",
        "fhwa_class", "detection_confidence", "trajectory_confidence",
        "timestamp_video", "frame_number", "manually_edited",
    ]
    ws3.append(raw_headers)
    for col in range(1, len(raw_headers) + 1):
        ws3.cell(row=1, column=col).font = Font(bold=True)
    for evt in events:
        ws3.append([
            int(evt[0]),
            int(evt[1]),
            int(evt[2]),
            evt[3],
            evt[4],
            int(evt[5]) if evt[5] is not None else None,
            float(evt[6]),
            float(evt[7]),
            float(evt[8]),
            int(evt[9]),
            int(evt[10]),
        ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    return output_path


def _format_time(timestamp_video: float, video_start_time: str) -> str:
    """Format a video timestamp as HH:MM using the recording start time if available."""
    if video_start_time:
        try:
            base = datetime.fromisoformat(video_start_time)
            return (base + timedelta(seconds=timestamp_video)).strftime("%H:%M")
        except (ValueError, TypeError):
            pass
    total_sec = int(timestamp_video)
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    if h > 0:
        return f"{h:02d}:{m:02d}"
    return f"{m:02d}:{total_sec % 60:02d}"
