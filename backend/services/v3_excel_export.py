"""v3 Excel export for an intersection-day.

Sheets:
  1. "TMC Summary"        — merged (cross-camera-deduped) TMC matrix
  2. "Per-Camera Breakdown" — same matrix grouped by camera (QA view)
  3. "Dedup Audit"        — summary of merged/kept counts

All cells are int() / str() literals — no formulas (per CLAUDE.md
hard constraint).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

from backend.services.cardinals import bound_approach
from backend.services.v3_aggregator import MOVEMENTS, aggregate_intersection_day


def _bold(cell):
    cell.font = Font(bold=True)


def export_intersection_day_xlsx(
    project_id: str, intersection_id: int, output_path: Path,
) -> Path:
    """Write the per-intersection-day TMC report. Returns output_path."""
    agg = aggregate_intersection_day(project_id, intersection_id)
    if "error" in agg:
        raise ValueError(agg["error"])

    intersection = agg["intersection"]
    wb = openpyxl.Workbook()

    # --- Sheet 1: TMC Summary (merged, deduped) -----------------------
    ws1 = wb.active
    ws1.title = "TMC Summary"

    ws1["A1"] = "Intersection"
    ws1["B1"] = intersection["name"]
    ws1["A2"] = "Date"
    ws1["B2"] = intersection["date"]
    ws1["A3"] = "Leg count"
    ws1["B3"] = int(intersection["leg_count"])
    ws1["A4"] = "Total vehicles (deduped)"
    ws1["B4"] = int(agg["totals"]["vehicles"])

    ws1.append([])  # blank row separator

    header = ["Leg", "Through", "Left", "Right", "U-Turn", "Other", "Total"]
    ws1.append(header)
    header_row = ws1.max_row
    for col in range(1, len(header) + 1):
        _bold(ws1.cell(row=header_row, column=col))

    col_totals = {m: 0 for m in MOVEMENTS}
    col_totals["other"] = 0
    col_totals["total"] = 0
    for r in agg["tmc_matrix"]:
        ws1.append([
            str(r["leg_label"]),
            int(r["through"]),
            int(r["left"]),
            int(r["right"]),
            int(r["u_turn"]),
            int(r["other"]),
            int(r["total"]),
        ])
        for m in MOVEMENTS:
            col_totals[m] += int(r[m])
        col_totals["other"] += int(r["other"])
        col_totals["total"] += int(r["total"])

    ws1.append([
        "Total",
        int(col_totals["through"]),
        int(col_totals["left"]),
        int(col_totals["right"]),
        int(col_totals["u_turn"]),
        int(col_totals["other"]),
        int(col_totals["total"]),
    ])
    totals_row = ws1.max_row
    for col in range(1, len(header) + 1):
        _bold(ws1.cell(row=totals_row, column=col))

    # --- Sheet 2: Per-Camera Breakdown --------------------------------
    ws2 = wb.create_sheet("Per-Camera Breakdown")
    row_idx = 1
    for camera_block in agg["per_camera_breakdown"]:
        ws2.cell(row=row_idx, column=1, value=f"Camera: {camera_block['camera_label']}").font = Font(bold=True)
        ws2.cell(row=row_idx, column=2, value=f"raw events: {camera_block['raw_event_count']}")
        row_idx += 1

        # Header
        for ci, h in enumerate(header, start=1):
            c = ws2.cell(row=row_idx, column=ci, value=h)
            _bold(c)
        row_idx += 1

        for r in camera_block["matrix"]:
            ws2.cell(row=row_idx, column=1, value=str(r["leg_label"]))
            ws2.cell(row=row_idx, column=2, value=int(r["through"]))
            ws2.cell(row=row_idx, column=3, value=int(r["left"]))
            ws2.cell(row=row_idx, column=4, value=int(r["right"]))
            ws2.cell(row=row_idx, column=5, value=int(r["u_turn"]))
            ws2.cell(row=row_idx, column=6, value=int(r["other"]))
            ws2.cell(row=row_idx, column=7, value=int(r["total"]))
            row_idx += 1
        row_idx += 1  # blank row between cameras

    if not agg["per_camera_breakdown"]:
        ws2["A1"] = "(no cameras yet)"

    # --- Sheet 3: Per-interval TMC (Phase 4 full-study deliverable) ----
    # Standard study format: one row per wall-clock interval, columns grouped
    # per APPROACH (the bound direction of travel = opposite of the leg's
    # cardinal POSITION, via bound_approach) x Thru/Left/Right/U.
    # Only intervals with traffic appear, so a 07-09/11-13/16-18 peak
    # study shows its three segments; a 24h study shows the full day.
    wsi = wb.create_sheet(f"{int(agg.get('interval_minutes', 15))}-min Intervals")
    intervals = agg.get("intervals", [])
    cardinals_present = []
    for itv in intervals:
        for c in itv["counts"]:
            if c not in cardinals_present:
                cardinals_present.append(c)
    card_order = [c for c in ("N", "S", "E", "W") if c in cardinals_present] + \
                 [c for c in cardinals_present if c not in ("N", "S", "E", "W")]
    mv_cols = ["through", "left", "right", "u_turn"]
    mv_short = {"through": "Thru", "left": "Left", "right": "Right", "u_turn": "U"}

    # Two header rows: approach group, then movement.
    wsi.cell(row=1, column=1, value="Interval")
    col = 2
    for c in card_order:
        gc = wsi.cell(row=1, column=col, value=f"{bound_approach(c)}B approach")
        _bold(gc)
        for k, m in enumerate(mv_cols):
            _bold(wsi.cell(row=2, column=col + k, value=mv_short[m]))
        col += len(mv_cols)
    _bold(wsi.cell(row=1, column=col, value="Total"))
    _bold(wsi.cell(row=2, column=1, value="start"))

    grand = {c: {m: 0 for m in mv_cols} for c in card_order}
    grand_total = 0
    r_idx = 3
    for itv in intervals:
        wsi.cell(row=r_idx, column=1, value=str(itv["label"]))
        col = 2
        for c in card_order:
            cb = itv["counts"].get(c, {})
            for k, m in enumerate(mv_cols):
                n = int(cb.get(m, 0))
                wsi.cell(row=r_idx, column=col + k, value=n)
                grand[c][m] += n
            col += len(mv_cols)
        wsi.cell(row=r_idx, column=col, value=int(itv["total"]))
        grand_total += int(itv["total"])
        r_idx += 1

    wsi.cell(row=r_idx, column=1, value="Total")
    col = 2
    for c in card_order:
        for k, m in enumerate(mv_cols):
            wsi.cell(row=r_idx, column=col + k, value=int(grand[c][m]))
        col += len(mv_cols)
    wsi.cell(row=r_idx, column=col, value=grand_total)
    for ci in range(1, col + 1):
        _bold(wsi.cell(row=r_idx, column=ci))
    if not intervals:
        wsi["A3"] = "(no events yet)"

    # --- Sheet 4: Dedup Audit -----------------------------------------
    ws3 = wb.create_sheet("Dedup Audit")
    audit_rows = [
        ("Raw event total", int(agg["dedup_summary"]["raw_total"])),
        ("Merged duplicates", int(agg["dedup_summary"]["merged"])),
        ("Kept (after dedup)", int(agg["dedup_summary"]["kept"])),
    ]
    for i, (label, value) in enumerate(audit_rows, start=1):
        c = ws3.cell(row=i, column=1, value=label)
        _bold(c)
        ws3.cell(row=i, column=2, value=value)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    return output_path
