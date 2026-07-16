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
            # merge-rejected fragments must never reach a deliverable
            # (stage-2a audit fix — the legacy query predated the turn merge)
            "FROM vehicle_events WHERE COALESCE(rejected, 0) = 0 "
            "ORDER BY timestamp_video"
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


def _load_export_data_v3(project_id: str, intersection_id: int) -> dict:
    """v3 intersection-day export frame (plan_deliverables_E stage 2a).

    Same keys as _load_export_data so BOTH artifact builders consume either
    frame — but built the v3 way: events scoped to ONE intersection's
    cameras, cross-camera dedup applied, rejected excluded, and wall-clock
    derived from EACH event's own video row. Events with no video start are
    excluded from the time-keyed frames (tmv/time_series/peaks) and counted
    in n_unstamped — never binned to an epoch fallback (the audit's
    year-2000 finding)."""
    from backend.database import get_intersection, list_cameras
    from backend.services.dedup import deduplicate
    from backend.services.v3_aggregator import (
        _camera_coverages_for_intersection, _load_events_for_dedup,
        _load_legs_by_camera)

    inter = get_intersection(project_id, intersection_id)
    if inter is None:
        raise ValueError(f"intersection {intersection_id} not found")
    cameras = list_cameras(project_id, intersection_id)
    camera_ids = [c["camera_id"] for c in cameras]

    coverages = _camera_coverages_for_intersection(project_id, intersection_id)
    events_for_dedup, raw_by_id = _load_events_for_dedup(project_id, camera_ids)
    kept_results, _dup_ids = deduplicate(events_for_dedup, coverages)
    kept_ids = {r.event_id for r in kept_results}
    # _load_events_for_dedup drops unstamped rows from the dedup input (no
    # wall-clock to compare) but keeps them in raw_by_id — they are still
    # real counted events for the count matrices.
    dedup_considered = {e.event_id for e in events_for_dedup}
    kept_rows = [row for eid, row in sorted(raw_by_id.items())
                 if eid in kept_ids or eid not in dedup_considered]

    # Legs merged across cameras by (label, cardinal) — one row per road,
    # not one per camera view of it (the audit's duplicate-leg finding).
    legs_by_camera = _load_legs_by_camera(project_id, camera_ids)
    seen: dict = {}
    for cam_legs in legs_by_camera.values():
        for lg in cam_legs:
            key = (lg["label"], (lg.get("cardinal_direction") or "").upper())
            seen.setdefault(key, len(seen))
    legs = [(idx, label, card, idx) for (label, card), idx in
            sorted(seen.items(), key=lambda kv: kv[1])]
    leg_id_by_key = {(label, card): idx for (label, card), idx in seen.items()}

    # destination leg -> cardinal (for the exits frame: Miovision's "O"
    # column = vehicles LEAVING via that road)
    dest_card = {lg["leg_id"]: (lg.get("cardinal_direction") or "").upper()
                 for cam_legs in legs_by_camera.values() for lg in cam_legs}

    tmc: dict = {lid: {"label": label, "through": 0, "left": 0, "right": 0,
                       "u_turn": 0, "total": 0} for lid, label, _c, _s in legs}
    tmv: dict = defaultdict(int)
    exits: dict = defaultdict(int)
    class_totals = {g: 0 for g in CLASS_GROUP_ORDER}
    events = []
    wallclocks = []
    n_unstamped = 0
    for row in kept_rows:
        key = (row.get("leg_label") or f"Leg {row['origin_leg_id']}",
               (row.get("cardinal_direction") or "").upper())
        lid = leg_id_by_key.setdefault(key, len(leg_id_by_key))
        if lid not in tmc:
            tmc[lid] = {"label": key[0], "through": 0, "left": 0, "right": 0,
                        "u_turn": 0, "total": 0}
            legs.append((lid, key[0], key[1], lid))
        mv = row.get("movement")
        if mv in ("through", "left", "right", "u_turn"):
            tmc[lid][mv] += 1
        tmc[lid]["total"] += 1
        grp = fhwa_to_class_group(row.get("fhwa_class"))
        class_totals[grp] += 1
        events.append((row["event_id"], row["vehicle_track_id"],
                       row["origin_leg_id"], row.get("movement"),
                       row.get("vehicle_class"), row.get("fhwa_class"),
                       row.get("detection_confidence"),
                       row.get("trajectory_confidence"),
                       row.get("timestamp_video"), row.get("frame_number"),
                       0))
        # wall-clock from THIS event's video row; unstamped -> excluded from
        # the time-keyed frames, counted.
        vstart = row.get("video_start")
        wc = None
        if vstart:
            try:
                wc = (datetime.fromisoformat(vstart)
                      + timedelta(seconds=float(row.get("timestamp_video") or 0)))
            except (ValueError, TypeError):
                wc = None
        if wc is None:
            n_unstamped += 1
            continue
        wallclocks.append(wc)
        mvl = _MV_LETTER.get(mv)
        if mvl is None:
            continue
        interval = wc.replace(minute=(wc.minute // 15) * 15, second=0,
                              microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        tmv[(interval, _approach_name(key[1]), mvl, grp)] += 1
        dcard = dest_card.get(row.get("destination_leg_id"))
        if dcard:
            exits[(interval, _approach_name(dcard), grp)] += 1

    time_series = []
    if wallclocks:
        interval_sec = 15 * 60
        t0 = min(wallclocks)
        t0 = t0.replace(minute=(t0.minute // 15) * 15, second=0, microsecond=0)
        t_max = max(wallclocks)
        t = t0
        while t <= t_max:
            end = t + timedelta(seconds=interval_sec)
            time_series.append(
                {"label": t.strftime("%H:%M"),
                 "vehicles": int(sum(1 for w in wallclocks if t <= w < end))})
            t = end

    video_start_time = min((row.get("video_start") for row in kept_rows
                            if row.get("video_start")), default="")
    date_str = (inter.get("date") or (video_start_time[:10] if video_start_time
                                      else datetime.now().strftime("%Y-%m-%d")))
    peaks = [("Peak 1 (AM)", _peak_analysis(tmv, 7, 9)),
             ("Peak 2 (PM)", _peak_analysis(tmv, 16, 18))]
    fmt = "%A, %B %d, %Y  %I:%M %p"
    study_start = min(wallclocks).strftime(fmt) if wallclocks else ""
    study_end = max(wallclocks).strftime(fmt) if wallclocks else ""

    return {"project_name": inter.get("name") or project_id,
            "video_start_time": video_start_time, "interval_minutes": 15,
            "legs": legs, "events": events,
            "leg_order": [lg[0] for lg in legs],
            "leg_labels": {lg[0]: lg[1] for lg in legs}, "tmc": tmc,
            "time_series": time_series, "tmv": tmv, "exits": exits,
            "class_totals": class_totals, "date_str": date_str,
            "peaks": peaks, "n_unstamped": n_unstamped,
            "study_start": study_start, "study_end": study_end,
            "site_code": ""}


def generate_tmc_excel(project_id: str, output_path: Path,
                       intersection_id: int | None = None) -> Path:
    """
    Queries vehicle_events, builds TMC matrix, writes xlsx.
    Returns the path to the written file.

    intersection_id given -> the v3 frame (one intersection-day, merged +
    cross-camera-deduped); omitted -> the legacy whole-project frame.

    Sheet 1 "TMC Summary"  — header rows + TMC matrix with column totals.
    Sheet 2 "Time Series"  — 15-min interval rows (vehicles only — pedestrians out of scope for v2).
    Sheet 3 "Raw Events"   — all vehicle_events rows for QA.

    All cell values are hard-coded integers (int()), no formulas.
    """
    d = (_load_export_data_v3(project_id, intersection_id)
         if intersection_id is not None else _load_export_data(project_id))
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


# --- Miovision-format workbook (plan_deliverables_E stage 2b) ----------------

def _hr12(h: int) -> str:
    return f"{(h - 1) % 12 + 1}:00 {'AM' if h % 24 < 12 else 'PM'}"


def _approach_letters(tmv: dict) -> dict:
    """{approach: [movement letters]} — geometry-aware: the letters observed
    for that approach across the FULL day, plus U always (Miovision lists the
    U column with zeros; a movement with zero volume all day is treated as
    geometrically absent, which reproduces the example's T-junction sets)."""
    seen: dict = defaultdict(set)
    for (_i, a, mv, _c) in tmv:
        seen[a].add(mv)
    return {a: [m for m in _MV_ORDER if m in (s | {"U"})]
            for a, s in seen.items()}


def _peak_block_data(tmv: dict, exits: dict, start_hour: int, end_hour: int,
                     approaches: list, letters: dict) -> Optional[dict]:
    """Everything one Summary peak block needs: per approach x movement x
    class volumes, per-approach In/Out (Out = exits via that road), PHFs per
    column, and the intersection grand column — all over the peak hour that
    _peak_analysis selects."""
    pk = _peak_analysis(tmv, start_hour, end_hour)
    if pk is None:
        return None
    win = [pk["start"] + timedelta(minutes=15 * k) for k in range(4)]
    win_iso = [w.strftime("%Y-%m-%d %H:%M:%S") for w in win]

    def _phf(subs):
        m = max(subs) if subs else 0
        return round(sum(subs) / (4 * m), 2) if m else 0.0

    data: dict = {}
    for a in approaches:
        cols = {}
        for m in letters.get(a, []):
            per_cls = {cls: sum(tmv.get((w, a, m, cls), 0) for w in win_iso)
                       for cls in CLASS_GROUP_ORDER}
            subs = [sum(tmv.get((w, a, m, cls), 0) for cls in CLASS_GROUP_ORDER)
                    for w in win_iso]
            cols[m] = {"cls": per_cls, "total": sum(subs), "phf": _phf(subs)}
        i_subs = [sum(tmv.get((w, a, m, cls), 0)
                      for m in letters.get(a, []) for cls in CLASS_GROUP_ORDER)
                  for w in win_iso]
        o_subs = [sum(exits.get((w, a, cls), 0) for cls in CLASS_GROUP_ORDER)
                  for w in win_iso]
        data[a] = {
            "cols": cols,
            "I": {"cls": {cls: sum(cols[m]["cls"][cls] for m in cols)
                          for cls in CLASS_GROUP_ORDER},
                  "total": sum(i_subs), "phf": _phf(i_subs)},
            "O": {"cls": {cls: sum(exits.get((w, a, cls), 0) for w in win_iso)
                          for cls in CLASS_GROUP_ORDER},
                  "total": sum(o_subs), "phf": _phf(o_subs)},
        }
    grand_subs = [sum(tmv.get((w, a, m, cls), 0) for a in approaches
                      for m in letters.get(a, []) for cls in CLASS_GROUP_ORDER)
                  for w in win_iso]
    grand_cls = {cls: sum(data[a]["cols"][m]["cls"][cls]
                          for a in approaches for m in data[a]["cols"])
                 for cls in CLASS_GROUP_ORDER}
    return {"start": pk["start"], "end": pk["end"],
            "period": (start_hour, end_hour), "data": data,
            "grand": {"cls": grand_cls, "total": sum(grand_subs),
                      "phf": _phf(grand_subs)}}


def _sheet_header(ws, d, title: Optional[str] = None) -> int:
    """The Study Name / Start / End / Site Code block every example sheet
    carries. Returns the first free row after the block (+ title row)."""
    for r, (label, value) in enumerate(
            [("Study Name", d["project_name"]), ("Start Date", d["study_start"]),
             ("End Date", d["study_end"]), ("Site Code", d["site_code"])], start=1):
        c = ws.cell(row=r, column=2, value=label)
        c.font = Font(bold=True)
        ws.cell(row=r, column=3, value=str(value))
    if title:
        t = ws.cell(row=6, column=2, value=title)
        t.font = Font(bold=True)
        return 8
    return 6


def _write_peak_block(ws, row: int, label_lines: list, blk: Optional[dict],
                      approaches: list, letters: dict) -> int:
    """One Summary peak block (approach column groups; class rows with %,
    Total, PHF, Approach %). Returns the next free row."""
    col = 4
    spans = {}
    for a in approaches:
        n = len(letters.get(a, [])) + 2          # movement letters + I + O
        spans[a] = (col, col + n - 1)
        ws.merge_cells(start_row=row, start_column=col,
                       end_row=row, end_column=col + n - 1)
        h = ws.cell(row=row, column=col, value=a)
        h.font = Font(bold=True)
        col += n
    total_col = col
    hdr = row + 1
    ws.cell(row=hdr, column=2, value="Time Period").font = Font(bold=True)
    ws.cell(row=hdr, column=3, value="Class.").font = Font(bold=True)
    colmap = []                                  # (approach, letter|I|O, col)
    for a in approaches:
        c0, _c1 = spans[a]
        for k, m in enumerate(letters.get(a, []) + ["I", "O"]):
            ws.cell(row=hdr, column=c0 + k, value=m).font = Font(bold=True)
            colmap.append((a, m, c0 + k))
    ws.cell(row=hdr, column=total_col, value="Total").font = Font(bold=True)

    if blk is None:
        ws.cell(row=hdr + 1, column=2, value=label_lines[0])
        ws.cell(row=hdr + 1, column=3, value="no data in period")
        return hdr + 3

    def _cell_val(a, m, cls):
        if m in ("I", "O"):
            return int(blk["data"][a][m]["cls"][cls])
        return int(blk["data"][a]["cols"][m]["cls"][cls])

    def _col_total(a, m):
        if m in ("I", "O"):
            return int(blk["data"][a][m]["total"])
        return int(blk["data"][a]["cols"][m]["total"])

    def _col_phf(a, m):
        if m in ("I", "O"):
            return float(blk["data"][a][m]["phf"])
        return float(blk["data"][a]["cols"][m]["phf"])

    r = hdr + 1
    rows_spec = []
    for cls in CLASS_GROUP_ORDER:
        rows_spec.append((cls, "cls"))
        rows_spec.append(("%", cls))
    rows_spec += [("Total", None), ("PHF", None), ("Approach %", None)]
    p0, p1 = blk["period"]
    start_lbl = blk["start"].strftime("%I:%M %p").lstrip("0")
    end_lbl = blk["end"].strftime("%I:%M %p").lstrip("0")
    left = [label_lines[0], "Specified Period",
            f"{_hr12(p0)} - {_hr12(p1)}", "One Hour Peak",
            f"{start_lbl} - {end_lbl}"]
    for i, (name, mode) in enumerate(rows_spec):
        if i < len(left):
            ws.cell(row=r, column=2, value=left[i])
        ws.cell(row=r, column=3, value=name).font = (
            Font(bold=True) if name in ("Total", "PHF") else Font())
        for a, m, c in colmap:
            if mode == "cls":
                ws.cell(row=r, column=c, value=_cell_val(a, m, name))
            elif mode is not None:                       # % row for class mode
                tot = _col_total(a, m)
                ws.cell(row=r, column=c,
                        value=(round(_cell_val(a, m, mode) / tot, 3)
                               if tot else 0))
            elif name == "Total":
                ws.cell(row=r, column=c, value=_col_total(a, m))
            elif name == "PHF":
                ws.cell(row=r, column=c, value=_col_phf(a, m))
            elif name == "Approach %" and m == "I":
                g = int(blk["grand"]["total"])
                ws.cell(row=r, column=c,
                        value=(round(blk["data"][a]["I"]["total"] / g, 3)
                               if g else 0))
        if mode == "cls":
            ws.cell(row=r, column=total_col,
                    value=int(blk["grand"]["cls"][name]))
        elif name == "Total":
            ws.cell(row=r, column=total_col, value=int(blk["grand"]["total"]))
        elif name == "PHF":
            ws.cell(row=r, column=total_col, value=float(blk["grand"]["phf"]))
        r += 1
    return r + 1


def generate_miovision_xlsx(project_id: str, output_path: Path,
                            intersection_id: int) -> Path:
    """The Miovision-parity deliverable workbook for one v3 intersection-day:
    Contents / Summary / TMV Table / TMV Data (+ Raw Events QA sheet).
    Layout per the stage-1 parity audit. Integers and literals only — no
    formulas (CLAUDE.md hard constraint)."""
    d = _load_export_data_v3(project_id, intersection_id)
    tmv, exits = d["tmv"], d["exits"]
    letters = _approach_letters(tmv)
    approaches = [a for a in _APPROACH_ORDER if a in letters]
    wb = openpyxl.Workbook()

    # ---- Contents ----
    ws = wb.active
    ws.title = "Contents"
    _sheet_header(ws, d)
    ws.cell(row=7, column=2, value="Overview").font = Font(bold=True)
    ws.cell(row=8, column=3, value=(
        "This report contains turning movement volume (TMV) data for the "
        "study intersection, produced from video by the intersection counter."))
    ws.cell(row=11, column=2, value="Content").font = Font(bold=True)
    for r, (name, desc) in enumerate([
            ("Summary", "Contains a TMV summary of the AM and PM peak hours"),
            ("TMV Table", "Contains a pivot table of the road volumes"),
            ("TMV Data", "Contains measured TMV data at 15-minute intervals"),
            ("Raw Events", "QA sheet: every counted vehicle event")], start=12):
        ws.cell(row=r, column=3, value=name)
        ws.cell(row=r, column=4, value=desc)
    ws.cell(row=17, column=2, value="Traffic Study").font = Font(bold=True)
    ws.cell(row=18, column=3, value="Start Date")
    ws.cell(row=18, column=4, value=d["study_start"])
    ws.cell(row=19, column=3, value="End Date")
    ws.cell(row=19, column=4, value=d["study_end"])
    ws.cell(row=20, column=3, value="Classification Categories")
    ws.cell(row=20, column=4, value=", ".join(CLASS_GROUP_ORDER))
    blocks = [("Peak 1 (AM)",
               _peak_block_data(tmv, exits, 7, 9, approaches, letters)),
              ("Peak 2 (PM)",
               _peak_block_data(tmv, exits, 16, 18, approaches, letters))]
    r = 21
    for name, blk in blocks:
        if blk:
            s_lbl = blk["start"].strftime("%I:%M %p").lstrip("0")
            e_lbl = blk["end"].strftime("%I:%M %p").lstrip("0")
            ws.cell(row=r, column=3, value=f"{d['date_str']} {name}")
            ws.cell(row=r, column=4, value=f"{s_lbl} - {e_lbl}")
            r += 1

    # ---- Summary ----
    ws = wb.create_sheet(f"({d['date_str'].replace('-', '_')}) Summary")
    row = _sheet_header(ws, d, "Report Summary")
    for name, blk in blocks:
        row = _write_peak_block(ws, row, [name.split(" (")[0]], blk,
                                approaches, letters)
        row += 1

    # ---- TMV Table (Road Volumes pivot, full day) ----
    ws = wb.create_sheet("TMV Table")
    row = _sheet_header(ws, d, "Road Volumes")
    day: dict = defaultdict(int)
    day_exits: dict = defaultdict(int)
    for (_i, a, m, _c), v in tmv.items():
        day[(a, m)] += v
    for (_i, a, _c), v in exits.items():
        day_exits[a] += v
    hdr_cells = ["Approach"] + list(_MV_ORDER) + ["Total In", "Total Out"]
    for k, h in enumerate(hdr_cells):
        ws.cell(row=row, column=2 + k, value=h).font = Font(bold=True)
    r = row + 1
    for a in approaches:
        ws.cell(row=r, column=2, value=a)
        for k, m in enumerate(_MV_ORDER):
            ws.cell(row=r, column=3 + k, value=int(day.get((a, m), 0)))
        ws.cell(row=r, column=3 + len(_MV_ORDER),
                value=int(sum(day.get((a, m), 0) for m in _MV_ORDER)))
        ws.cell(row=r, column=4 + len(_MV_ORDER),
                value=int(day_exits.get(a, 0)))
        r += 1

    # ---- TMV Data (long format, 15-min) ----
    ws = wb.create_sheet("TMV Data")
    row = _sheet_header(ws, d, "Turning Movement Volume Data")
    for k, h in enumerate(["Interval", "Approach", "Movement", "Class",
                           "Volume"]):
        ws.cell(row=row, column=2 + k, value=h).font = Font(bold=True)
    r = row + 1
    for (interval, a, m, cls) in sorted(tmv):
        ws.cell(row=r, column=2, value=interval)
        ws.cell(row=r, column=3, value=a)
        ws.cell(row=r, column=4, value=m)
        ws.cell(row=r, column=5, value=cls)
        ws.cell(row=r, column=6, value=int(tmv[(interval, a, m, cls)]))
        r += 1

    # ---- Raw Events (QA) ----
    ws = wb.create_sheet("Raw Events")
    for k, h in enumerate(["event_id", "track_id", "origin_leg_id", "movement",
                           "vehicle_class", "fhwa_class", "det_conf",
                           "traj_conf", "timestamp_video", "frame"]):
        ws.cell(row=1, column=1 + k, value=h).font = Font(bold=True)
    for r, evt in enumerate(d["events"], start=2):
        for k in range(10):
            v = evt[k]
            ws.cell(row=r, column=1 + k,
                    value=(round(float(v), 3) if isinstance(v, float) else v))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    return output_path
