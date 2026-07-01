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


# Canonical ordering for the Summary sheet columns.
_APPROACH_ORDER = ["Northbound", "Southbound", "Eastbound", "Westbound",
                   "Northeastbound", "Northwestbound", "Southeastbound", "Southwestbound"]
_MV_ORDER = ["L", "T", "R", "U"]


def _peak_analysis(tmv: dict, start_hour: int, end_hour: int) -> Optional[dict]:
    """Peak 1-hour window within [start_hour, end_hour) + per-(approach, movement)
    class volumes and Peak Hour Factors. `tmv` is keyed
    (interval_iso, approach, movement, class) -> volume. Returns None when the
    study window covers no data in the period.

    PHF (standard) = hour volume / (4 * max 15-min volume in the hour); computed
    per column and for the intersection total. The peak hour is the 1-hour window
    (rolling 15-min) with the greatest total volume within the specified period."""
    from datetime import time as _time
    from collections import defaultdict as _dd
    bt: dict = _dd(int)                       # bin_dt -> total volume
    bc: dict = _dd(lambda: _dd(int))          # bin_dt -> {(approach, mv): vol}
    bcl: dict = _dd(lambda: _dd(int))         # bin_dt -> {(approach, mv, cls): vol}
    for (iso, approach, mv, cls), v in tmv.items():
        try:
            dt = datetime.fromisoformat(iso)
        except (ValueError, TypeError):
            continue
        if not (start_hour <= dt.hour < end_hour):
            continue
        bt[dt] += v
        bc[dt][(approach, mv)] += v
        bcl[dt][(approach, mv, cls)] += v
    if not bt:
        return None
    day = min(bt).date()
    last_start = datetime.combine(day, _time(min(end_hour, 23), 0)) - timedelta(hours=1)
    starts = [datetime.combine(day, _time(h, m))
              for h in range(start_hour, end_hour) for m in (0, 15, 30, 45)]
    starts = [s for s in starts if s <= last_start]
    if not starts:
        return None

    def _win(s):
        return [s + timedelta(minutes=15 * k) for k in range(4)]

    def _phf(total, subs):
        m = max(subs) if subs else 0
        return round(total / (4 * m), 2) if m else 0.0

    best = max(starts, key=lambda s: sum(bt.get(w, 0) for w in _win(s)))
    win = _win(best)
    col_keys = sorted(
        {k for w in win for k in bc.get(w, {})},
        key=lambda k: (_APPROACH_ORDER.index(k[0]) if k[0] in _APPROACH_ORDER else 99,
                       _MV_ORDER.index(k[1]) if k[1] in _MV_ORDER else 99))
    cols = {}
    for ck in col_keys:
        subs = [bc.get(w, {}).get(ck, 0) for w in win]
        entry = {"Total": sum(subs), "PHF": _phf(sum(subs), subs)}
        for cls in CLASS_GROUP_ORDER:
            entry[cls] = sum(bcl.get(w, {}).get((ck[0], ck[1], cls), 0) for w in win)
        cols[ck] = entry
    grand_subs = [bt.get(w, 0) for w in win]
    grand = {"Total": sum(grand_subs), "PHF": _phf(sum(grand_subs), grand_subs)}
    for cls in CLASS_GROUP_ORDER:
        grand[cls] = sum(cols[ck][cls] for ck in cols)
    return {"start": best, "end": best + timedelta(hours=1),
            "period": (start_hour, end_hour), "col_keys": col_keys,
            "cols": cols, "grand": grand}


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


def _load_export_data(project_id: str) -> dict:
    """Query + aggregate the export data once. Shared by the Excel and PDF
    exporters (DRY) so a request makes a single 90k-event pass. Returns the TMC
    matrix, 15-min time series, Miovision TMV aggregation, class totals, and the
    AM/PM peak-hour analyses."""
    info = get_all_project_info(project_id)
    project_name = info.get("project_name", project_id)
    video_start_time = info.get("video_start_time", "")
    interval_minutes = max(1, int(info.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)))

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

    leg_order = [row[0] for row in legs]
    leg_labels = {row[0]: row[1] for row in legs}
    tmc: dict = {}
    for row in legs:
        tmc[row[0]] = {"label": row[1], "through": 0, "left": 0, "right": 0, "u_turn": 0, "total": 0}
    for evt in events:
        leg_id, movement = evt[2], evt[3]
        if leg_id not in tmc:
            tmc[leg_id] = {"label": f"Leg {leg_id}", "through": 0, "left": 0, "right": 0, "u_turn": 0, "total": 0}
        if movement in ("through", "left", "right", "u_turn"):
            tmc[leg_id][movement] += 1
        tmc[leg_id]["total"] += 1

    vehicle_times = [evt[8] for evt in events]
    time_series = []
    if vehicle_times:
        interval_sec = interval_minutes * 60
        t, max_t = min(vehicle_times), max(vehicle_times)
        while t <= max_t:
            end_t = t + interval_sec
            time_series.append({"label": _format_time(t, video_start_time),
                                "vehicles": int(sum(1 for ts in vehicle_times if t <= ts < end_t))})
            t = end_t

    # Miovision-format class-aware long data: (interval, approach, movement, class) -> volume.
    leg_card = {row[0]: row[2] for row in legs}
    tmv: dict = defaultdict(int)
    class_totals = {g: 0 for g in CLASS_GROUP_ORDER}
    for evt in events:
        mv = _MV_LETTER.get(evt[3])
        if mv is None:
            continue
        tmv[(_interval_15(evt[8], video_start_time),
             _approach_name(leg_card.get(evt[2])), mv, fhwa_to_class_group(evt[5]))] += 1
        class_totals[fhwa_to_class_group(evt[5])] += 1

    date_str = video_start_time[:10] if video_start_time else datetime.now().strftime("%Y-%m-%d")
    peaks = [("Peak 1 (AM)", _peak_analysis(tmv, 7, 9)),
             ("Peak 2 (PM)", _peak_analysis(tmv, 16, 18))]

    return {"project_name": project_name, "video_start_time": video_start_time,
            "interval_minutes": interval_minutes, "legs": legs, "events": events,
            "leg_order": leg_order, "leg_labels": leg_labels, "tmc": tmc,
            "time_series": time_series, "tmv": tmv, "class_totals": class_totals,
            "date_str": date_str, "peaks": peaks}


def generate_tmc_excel(project_id: str, output_path: Path) -> Path:
    """
    Queries vehicle_events, builds TMC matrix, writes xlsx.
    Returns the path to the written file.

    Sheet 1 "TMC Summary"  — header rows + TMC matrix with column totals.
    Sheet 2 "Time Series"  — 15-min interval rows (vehicles only — pedestrians out of scope for v2).
    Sheet 3 "Raw Events"   — all vehicle_events rows for QA.

    All cell values are hard-coded integers (int()), no formulas.
    """
    d = _load_export_data(project_id)
    project_name = d["project_name"]
    video_start_time = d["video_start_time"]
    legs = d["legs"]
    events = d["events"]
    leg_order = d["leg_order"]
    tmc = d["tmc"]
    time_series = d["time_series"]
    tmv = d["tmv"]
    class_totals = d["class_totals"]
    date_str = d["date_str"]
    peaks = d["peaks"]

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

    # ---- Summary (Miovision-format peak-hour analysis) + Contents ----
    # date_str + peaks come from _load_export_data (shared with the PDF report).
    ws_sum = wb.create_sheet("Summary")
    ws_sum.append(["Study Name", project_name])
    ws_sum.append(["Date", date_str])
    ws_sum.append([])
    ws_sum.append(["Report Summary - peak-hour turning-movement volumes by class"])
    ws_sum.cell(row=ws_sum.max_row, column=1).font = Font(bold=True)
    ws_sum.append([])
    any_peak = False
    for label, pk in peaks:
        if pk is None:
            continue
        any_peak = True
        ws_sum.append([f"{label}: one-hour peak {pk['start'].strftime('%H:%M')}-"
                       f"{pk['end'].strftime('%H:%M')} (within "
                       f"{pk['period'][0]:02d}:00-{pk['period'][1]:02d}:00)"])
        ws_sum.cell(row=ws_sum.max_row, column=1).font = Font(bold=True)
        header = ["Approach", "Mvt"] + list(CLASS_GROUP_ORDER) + ["Total", "PHF"]
        ws_sum.append(header)
        for c in range(1, len(header) + 1):
            ws_sum.cell(row=ws_sum.max_row, column=c).font = Font(bold=True)
        for ck in pk["col_keys"]:
            e = pk["cols"][ck]
            ws_sum.append([ck[0], ck[1]] + [int(e[cls]) for cls in CLASS_GROUP_ORDER]
                          + [int(e["Total"]), e["PHF"]])
        g = pk["grand"]
        ws_sum.append(["Total", ""] + [int(g[cls]) for cls in CLASS_GROUP_ORDER]
                      + [int(g["Total"]), g["PHF"]])
        ws_sum.cell(row=ws_sum.max_row, column=1).font = Font(bold=True)
        ws_sum.append([])
    if not any_peak:
        ws_sum.append(["(No AM/PM peak period is covered by the processed window.)"])

    ws_contents = wb.create_sheet("Contents")
    ws_contents.append(["Study Name", project_name])
    ws_contents.append(["Date", date_str])
    ws_contents.append([])
    ws_contents.append(["Contents"])
    ws_contents.cell(row=ws_contents.max_row, column=1).font = Font(bold=True)
    for name, desc in [
        ("Summary", "Peak-hour turning-movement volumes by class + Peak Hour Factor"),
        ("TMV Data", "Per-15-min volumes: Interval / Approach / Movement / Class / Volume"),
        ("TMC Summary", "Turning-movement totals by leg + Light/Medium/Articulated totals"),
        ("Time Series", "Total vehicles per interval"),
        ("Raw Events", "Every counted vehicle event (QA)"),
    ]:
        ws_contents.append([name, desc])

    # Order sheets Miovision-style: Contents, Summary, then the rest.
    _order = ["Contents", "Summary", "TMC Summary", "Time Series", "TMV Data", "Raw Events"]
    wb._sheets.sort(key=lambda s: _order.index(s.title) if s.title in _order else 99)

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
