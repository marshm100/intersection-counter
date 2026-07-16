"""Miovision-style PDF turning-movement report (Phase 3E.3 — MASTER_PLAN §3-E).

Renders from the shared export data (excel_export._load_export_data) via
matplotlib's PdfPages backend. matplotlib is already installed (an ultralytics/YOLO
dependency), so this adds NO new package — important for a tool that runs locally
with no internet after install.

Page 1: letterhead + study metadata + the peak-hour summary (per approach x
movement x class {Lights/Mediums/Articulated} + Total + PHF), mirroring Miovision's
Summary. Following pages: the 15-min turning-movement table (Interval x
approach-movement + Int. Total), paginated.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # headless — never open a GUI window on the server
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from backend.services.classifier import CLASS_GROUP_ORDER
from backend.services.excel_export import _APPROACH_ORDER, _MV_ORDER, _load_export_data

_FIRM = "DeShazo"                    # letterhead firm name (configurable)
_ABBR = {"Northbound": "NB", "Southbound": "SB", "Eastbound": "EB", "Westbound": "WB",
         "Northeastbound": "NEB", "Northwestbound": "NWB",
         "Southeastbound": "SEB", "Southwestbound": "SWB"}
_ROWS_PER_PAGE = 34


def _fig():
    fig = plt.figure(figsize=(11, 8.5))   # landscape US Letter
    return fig


def _header(fig, project_name: str, date_str: str, page_title: str):
    fig.text(0.03, 0.955, _FIRM, fontsize=15, fontweight="bold")
    fig.text(0.03, 0.93, "Turning Movement Count Report", fontsize=9, color="#555555")
    fig.text(0.97, 0.955, project_name, fontsize=10, fontweight="bold", ha="right")
    fig.text(0.97, 0.93, f"Date: {date_str}", fontsize=9, color="#555555", ha="right")
    fig.text(0.03, 0.90, page_title, fontsize=12, fontweight="bold")


def _draw_table(fig, rect, col_labels, rows, header_bg="#1f2937"):
    ax = fig.add_axes(rect)
    ax.axis("off")
    if not rows:
        ax.text(0.5, 0.5, "(no data)", ha="center", va="center", color="#9ca3af")
        return
    tbl = ax.table(cellText=rows, colLabels=col_labels, loc="upper center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7)
    tbl.scale(1, 1.3)
    for (r, _c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#d1d5db")
        if r == 0:
            cell.set_facecolor(header_bg)
            cell.set_text_props(color="white", fontweight="bold")
    return tbl


def _summary_page(pdf, d):
    fig = _fig()
    _header(fig, d["project_name"], d["date_str"], "Peak-Hour Summary")
    col_labels = ["Approach", "Mvt"] + list(CLASS_GROUP_ORDER) + ["Total", "PHF"]
    y = 0.86
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
        h = min(0.36, 0.03 + 0.022 * len(rows))
        _draw_table(fig, [0.03, y - h - 0.01, 0.94, h], col_labels, rows)
        y -= h + 0.06
    if not any_peak:
        fig.text(0.03, 0.8, "No AM (07:00-09:00) or PM (16:00-18:00) peak period is "
                 "covered by the processed window.", fontsize=9, color="#b45309")
    pdf.savefig(fig)
    plt.close(fig)


def _tmc_pages(pdf, d):
    # aggregate the class-split tmv down to (interval, approach, mv) volumes
    per = defaultdict(int)
    intervals, colset = set(), set()
    for (iso, approach, mv, _cls), v in d["tmv"].items():
        per[(iso, approach, mv)] += v
        intervals.add(iso)
        colset.add((approach, mv))
    if not intervals:
        return
    cols = sorted(colset, key=lambda k: (_APPROACH_ORDER.index(k[0]) if k[0] in _APPROACH_ORDER else 99,
                                         _MV_ORDER.index(k[1]) if k[1] in _MV_ORDER else 99))
    col_labels = ["Interval"] + [f"{_ABBR.get(a, a)} {m}" for a, m in cols] + ["Int. Total"]
    all_rows = []
    for iso in sorted(intervals):
        vals = [per.get((iso, a, m), 0) for a, m in cols]
        label = iso[11:16] if len(iso) >= 16 else iso   # HH:MM
        all_rows.append([label] + [str(v) for v in vals] + [str(sum(vals))])

    for i in range(0, len(all_rows), _ROWS_PER_PAGE):
        chunk = all_rows[i:i + _ROWS_PER_PAGE]
        fig = _fig()
        pg = i // _ROWS_PER_PAGE + 1
        _header(fig, d["project_name"], d["date_str"],
                f"Turning Movement Data (15-min)  —  page {pg}")
        _draw_table(fig, [0.02, 0.04, 0.96, 0.84], col_labels, chunk)
        pdf.savefig(fig)
        plt.close(fig)


def generate_report_pdf(project_id: str, output_path: Path,
                        intersection_id: int | None = None) -> Path:
    """Render the turning-movement PDF report to output_path. Returns the path.
    intersection_id given -> the v3 intersection-day frame (merged, deduped);
    omitted -> the legacy whole-project frame."""
    from backend.services.excel_export import _load_export_data_v3
    d = (_load_export_data_v3(project_id, intersection_id)
         if intersection_id is not None else _load_export_data(project_id))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(str(output_path)) as pdf:
        _summary_page(pdf, d)
        _tmc_pages(pdf, d)
    return output_path
