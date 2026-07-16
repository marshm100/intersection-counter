"""Miovision-style PDF turning-movement report (MASTER_PLAN §3-E; layout per
the stage-1 parity audit, plan_deliverables_E_2026-07-16).

Renders from the shared export frame (excel_export loaders) via matplotlib's
PdfPages backend — matplotlib is already installed (a YOLO dependency), so
this adds NO new package; the tool stays local, no internet after install.

Page order mirrors the example deliverable:
  1..N  "Turning Movement Data" — PER-MINUTE rows, approach column groups
        with road names, App. Total per approach, Int. Total (v3 frame only;
        the legacy frame has no minute data and skips to 15-min).
  N+1.. "Turning Movement Data - 15 Minute Intervals" — same layout.
  last  Peak-Hour Summary (AM + PM blocks with class rows and PHFs).

Every page carries the operating firm's letterhead (config REPORT_LETTERHEAD
— an empty firm name omits the block; placeholder branding is never
rendered) and the Count Name / Site Code / Start Date / Page No block.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # headless — never open a GUI window on the server
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from backend.config import REPORT_LETTERHEAD
from backend.services.classifier import CLASS_GROUP_ORDER
from backend.services.excel_export import (
    _APPROACH_ORDER, _MV_ORDER, _load_export_data,
)

_ABBR = {"Northbound": "NB", "Southbound": "SB", "Eastbound": "EB", "Westbound": "WB",
         "Northeastbound": "NEB", "Northwestbound": "NWB",
         "Southeastbound": "SEB", "Southwestbound": "SWB"}
_MV_FULL = {"L": "Left", "T": "Thru", "R": "Right", "U": "U-Turn"}
_ROWS_PER_PAGE = 38


def _fig():
    return plt.figure(figsize=(11, 8.5))   # landscape US Letter


def _header(fig, d, page_title: str, page_no: int):
    """Letterhead (when configured) + the Count Name / Site Code / Start Date
    / Page No block the example carries on every page."""
    y = 0.965
    lh = REPORT_LETTERHEAD
    if lh.get("name"):
        fig.text(0.03, y, lh["name"], fontsize=14, fontweight="bold")
        yy = y - 0.022
        for line in (lh.get("address_lines") or [])[:3]:
            fig.text(0.03, yy, line, fontsize=6.5, color="#555555")
            yy -= 0.014
        if lh.get("contact"):
            fig.text(0.03, yy, lh["contact"], fontsize=6.5, color="#555555")
            yy -= 0.014
        if lh.get("tagline"):
            fig.text(0.03, yy, lh["tagline"], fontsize=6.5, color="#777777",
                     style="italic")
    fig.text(0.97, y, f"Count Name: {d['project_name']}", fontsize=9,
             fontweight="bold", ha="right")
    fig.text(0.97, y - 0.020, f"Site Code: {d.get('site_code', '')}",
             fontsize=8, color="#555555", ha="right")
    fig.text(0.97, y - 0.038, f"Start Date: {d['date_str']}", fontsize=8,
             color="#555555", ha="right")
    fig.text(0.97, y - 0.056, f"Page No: {page_no}", fontsize=8,
             color="#555555", ha="right")
    fig.text(0.03, 0.875, page_title, fontsize=12, fontweight="bold")


def _draw_table(fig, rect, col_labels, rows, header_bg="#1f2937"):
    ax = fig.add_axes(rect)
    ax.axis("off")
    if not rows:
        ax.text(0.5, 0.5, "(no data)", ha="center", va="center", color="#9ca3af")
        return
    tbl = ax.table(cellText=rows, colLabels=col_labels, loc="upper center",
                   cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(6.5)
    tbl.scale(1, 1.25)
    for (r, _c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#d1d5db")
        if r == 0:
            cell.set_facecolor(header_bg)
            cell.set_text_props(color="white", fontweight="bold")
    return tbl


def _approach_columns(per: dict) -> tuple[list, list]:
    """(ordered approaches, ordered (approach, mv) columns) from a
    {(iso, approach, mv): n} frame."""
    colset = {(a, m) for (_i, a, m) in per}
    approaches = [a for a in _APPROACH_ORDER if any(c[0] == a for c in colset)]
    cols = []
    for a in approaches:
        cols += [(a, m) for m in _MV_ORDER if (a, m) in colset]
    return approaches, cols


def _movement_pages(pdf, d, per: dict, title: str, page_no: int) -> int:
    """The example's Turning Movement Data table: approach column groups
    (road name + bound), movement columns + App. Total per approach,
    Int. Total. `per` is {(iso, approach, mv): n}. Returns next page_no."""
    if not per:
        return page_no
    approaches, cols = _approach_columns(per)
    roads = d.get("road_by_approach", {})
    # two visual header lines folded into one label row (matplotlib table
    # supports a single header row): "FM 51\nSB Left" style.
    seen_app = set()
    labels_with_totals = ["Start Time"]
    for a, m in cols:
        labels_with_totals.append(f"{roads.get(a, '')}\n"
                                  f"{_ABBR.get(a, a)} {_MV_FULL.get(m, m)}")
        # append the App. Total column after the approach's last movement
        rest = [c for c in cols if c[0] == a]
        if (a, m) == rest[-1] and a not in seen_app:
            labels_with_totals.append(f"{_ABBR.get(a, a)}\nApp. Total")
            seen_app.add(a)
    labels_with_totals.append("Int.\nTotal")

    intervals = sorted({i for (i, _a, _m) in per})
    all_rows = []
    for iso in intervals:
        row = [iso[11:16] if len(iso) >= 16 else iso]
        int_total = 0
        for a in approaches:
            app_total = 0
            for aa, m in cols:
                if aa != a:
                    continue
                v = per.get((iso, a, m), 0)
                row.append(str(v))
                app_total += v
            row.append(str(app_total))
            int_total += app_total
        row.append(str(int_total))
        all_rows.append(row)

    for i in range(0, len(all_rows), _ROWS_PER_PAGE):
        chunk = all_rows[i:i + _ROWS_PER_PAGE]
        fig = _fig()
        _header(fig, d, title, page_no)
        _draw_table(fig, [0.02, 0.03, 0.96, 0.82], labels_with_totals, chunk)
        pdf.savefig(fig)
        plt.close(fig)
        page_no += 1
    return page_no


def _summary_page(pdf, d, page_no: int) -> int:
    fig = _fig()
    _header(fig, d, "Peak-Hour Summary", page_no)
    col_labels = ["Approach", "Mvt"] + list(CLASS_GROUP_ORDER) + ["Total", "PHF"]
    y = 0.84
    any_peak = False
    for label, pk in d["peaks"]:
        if pk is None:
            continue
        any_peak = True
        fig.text(0.03, y, f"{label}: one-hour peak "
                 f"{pk['start'].strftime('%H:%M')}-{pk['end'].strftime('%H:%M')} "
                 f"(within {pk['period'][0]:02d}:00-{pk['period'][1]:02d}:00)",
                 fontsize=9, fontweight="bold")
        rows = []
        for ck in pk["col_keys"]:
            e = pk["cols"][ck]
            rows.append([ck[0], ck[1]] + [str(int(e[c])) for c in CLASS_GROUP_ORDER]
                        + [str(int(e["Total"])), f"{e['PHF']:.2f}"])
        g = pk["grand"]
        rows.append(["Total", ""] + [str(int(g[c])) for c in CLASS_GROUP_ORDER]
                    + [str(int(g["Total"])), f"{g['PHF']:.2f}"])
        h = min(0.34, 0.03 + 0.022 * len(rows))
        _draw_table(fig, [0.03, y - h - 0.01, 0.94, h], col_labels, rows)
        y -= h + 0.06
    if not any_peak:
        fig.text(0.03, 0.8, "No AM (07:00-09:00) or PM (16:00-18:00) peak period is "
                 "covered by the processed window.", fontsize=9, color="#b45309")
    pdf.savefig(fig)
    plt.close(fig)
    return page_no + 1


def generate_report_pdf(project_id: str, output_path: Path,
                        intersection_id: int | None = None) -> Path:
    """Render the turning-movement PDF report to output_path. Returns the path.
    intersection_id given -> the v3 intersection-day frame (merged, deduped,
    with per-minute pages); omitted -> the legacy whole-project frame
    (15-min pages only)."""
    from backend.services.excel_export import _load_export_data_v3
    d = (_load_export_data_v3(project_id, intersection_id)
         if intersection_id is not None else _load_export_data(project_id))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    per15 = defaultdict(int)
    for (iso, approach, mv, _cls), v in d["tmv"].items():
        per15[(iso, approach, mv)] += v

    with PdfPages(str(output_path)) as pdf:
        page = 1
        per_min = d.get("tmv_minute") or {}
        if per_min:
            page = _movement_pages(pdf, d, per_min,
                                   "Turning Movement Data", page)
        page = _movement_pages(pdf, d, per15,
                               "Turning Movement Data - 15 Minute Intervals",
                               page)
        _summary_page(pdf, d, page)
    return output_path
