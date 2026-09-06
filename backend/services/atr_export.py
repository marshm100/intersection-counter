"""ATR Excel deliverable — directional screenline volumes.

Plan: Deliver+ATR Part 2 (docs/plan_atr_2026-08-28.md). Sheets:
Contents / Summary (per-direction peak hour + PHF) / Directional
Volumes (15-min rows including zero bins, hourly subtotals, class
mix). No formulas (house rule) — every cell a literal.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font


def _bold(cell):
    cell.font = Font(bold=True)


def generate_atr_xlsx(project_id: str, output_path: Path,
                      intersection_id: int) -> Path:
    from backend.database import get_connection
    from backend.services.atr_counts import count_screenline_crossings
    from backend.services.two_pass import derive_windows

    conn = get_connection(project_id)
    try:
        row = conn.execute(
            "SELECT name, date FROM intersections WHERE intersection_id"
            " = ?", (intersection_id,)).fetchone()
        name, date_str = (row or ("Midblock", ""))
        cams = [int(r[0]) for r in conn.execute(
            "SELECT camera_id FROM cameras WHERE intersection_id = ?",
            (intersection_id,))]
    finally:
        conn.close()
    windows = derive_windows(project_id, intersection_id)

    wb = Workbook()
    contents = wb.active
    contents.title = "Contents"
    contents["A1"] = "ATR Directional Volume Study"
    _bold(contents["A1"])
    contents["A3"] = "Site"
    contents["B3"] = str(name)
    contents["A4"] = "Study date"
    contents["B4"] = str(date_str)
    contents["A5"] = "Generated"
    contents["B5"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    contents["A7"] = ("Counts are directional screenline crossings from "
                      "video tracking; classes are visual length classes "
                      "(video cannot measure axles).")

    for w in windows:
        cam = w["camera_id"]
        if cam not in cams:
            continue
        res = count_screenline_crossings(project_id, cam, w["variant"])
        if not res or not res["bins"]:
            continue
        # column set: (leg, dir) sorted by leg then in/out
        cols = sorted(res["totals"].keys())
        legs = res["legs"]
        cardinals = res.get("cardinals", {})
        # Travel-direction naming (operator spec 2026-09-06: one line on
        # the Northern leg captures BOTH Southbound and Northbound —
        # columns carry the direction of travel, not in/out):
        # crossing INWARD through the N leg = traveling south, etc.
        _IN_DIR = {"N": "Southbound", "S": "Northbound",
                   "E": "Westbound", "W": "Eastbound"}
        _OUT_DIR = {"N": "Northbound", "S": "Southbound",
                    "E": "Eastbound", "W": "Westbound"}

        def colname(key):
            lid, d = key.split(":")
            card = cardinals.get(int(lid))
            trav = (_IN_DIR if d == "in" else _OUT_DIR).get(card)
            base = legs.get(int(lid), lid)
            return f"{base} — {trav}" if trav else f"{base} ({d.upper()})"

        ws = wb.create_sheet(f"Volumes {w['variant'][-4:]}")
        ws["A1"] = f"{name} — {w['variant']} directional volumes"
        _bold(ws["A1"])
        hdr = 3
        ws.cell(row=hdr, column=1, value="Interval")
        for j, key in enumerate(cols):
            c = ws.cell(row=hdr, column=2 + j, value=colname(key))
            _bold(c)
        c = ws.cell(row=hdr, column=2 + len(cols), value="Total")
        _bold(c)
        r = hdr + 1
        hour_acc: dict = {}
        hour_lab = None
        for b in res["bins"]:
            if hour_lab is not None and b["label"][:2] != hour_lab:
                ws.cell(row=r, column=1, value=f"{hour_lab}:00 hour")
                _bold(ws.cell(row=r, column=1))
                for j, key in enumerate(cols):
                    cc = ws.cell(row=r, column=2 + j,
                                 value=int(hour_acc.get(key, 0)))
                    _bold(cc)
                tc = ws.cell(row=r, column=2 + len(cols),
                             value=int(sum(hour_acc.values())))
                _bold(tc)
                r += 1
                hour_acc = {}
            hour_lab = b["label"][:2]
            ws.cell(row=r, column=1, value=b["label"])
            for j, key in enumerate(cols):
                ws.cell(row=r, column=2 + j,
                        value=int(b["counts"].get(key, 0)))
            ws.cell(row=r, column=2 + len(cols), value=int(b["total"]))
            for key, n in b["counts"].items():
                hour_acc[key] = hour_acc.get(key, 0) + n
            r += 1
        if hour_acc:
            ws.cell(row=r, column=1, value=f"{hour_lab}:00 hour")
            _bold(ws.cell(row=r, column=1))
            for j, key in enumerate(cols):
                cc = ws.cell(row=r, column=2 + j,
                             value=int(hour_acc.get(key, 0)))
                _bold(cc)
            tc = ws.cell(row=r, column=2 + len(cols),
                         value=int(sum(hour_acc.values())))
            _bold(tc)
            r += 1
        # window totals + peak hour + PHF per direction
        r += 1
        ws.cell(row=r, column=1, value="Window total")
        _bold(ws.cell(row=r, column=1))
        for j, key in enumerate(cols):
            ws.cell(row=r, column=2 + j, value=int(res["totals"][key]))
        r += 1
        for j, key in enumerate(cols):
            series = [(b["start"], b["counts"].get(key, 0))
                      for b in res["bins"]]
            best_i, best_v = None, -1
            for i in range(len(series) - 3):
                v = sum(n for _s, n in series[i:i + 4])
                if v > best_v:
                    best_i, best_v = i, v
            if best_i is None or best_v <= 0:
                continue
            sub = [n for _s, n in series[best_i:best_i + 4]]
            phf = round(best_v / (4 * max(sub)), 2) if max(sub) else None
            ws.cell(row=r, column=1,
                    value=f"Peak hour {colname(key)}")
            ws.cell(row=r, column=2,
                    value=res["bins"][best_i]["label"])
            ws.cell(row=r, column=3, value=int(best_v))
            ws.cell(row=r, column=4,
                    value=f"PHF {phf}" if phf else "")
            r += 1
        # ---- rolling hourly totals (operator spec: 7:00-8:00,
        # 7:15-8:15, ... every 15-minute step) --------------------------
        r += 1
        c = ws.cell(row=r, column=1, value="Rolling hourly totals")
        _bold(c)
        r += 1
        ws.cell(row=r, column=1, value="Hour starting")
        for j, key in enumerate(cols):
            _bold(ws.cell(row=r, column=2 + j, value=colname(key)))
        _bold(ws.cell(row=r, column=2 + len(cols), value="Total"))
        r += 1
        nb = res["bins"]
        for i in range(len(nb) - 3):
            ws.cell(row=r, column=1, value=nb[i]["label"])
            tot = 0
            for j, key in enumerate(cols):
                v = sum(nb[i + k]["counts"].get(key, 0) for k in range(4))
                ws.cell(row=r, column=2 + j, value=int(v))
                tot += v
            ws.cell(row=r, column=2 + len(cols), value=int(tot))
            r += 1

        # ---- class breakdown sheet (operator spec) --------------------
        groups = ("car", "truck", "bus", "motorcycle")
        cs = wb.create_sheet(f"Classes {w['variant'][-4:]}")
        cs["A1"] = f"{name} — {w['variant']} vehicle classes"
        _bold(cs["A1"])
        hdr2 = 3
        cs.cell(row=hdr2, column=1, value="Interval")
        col_i = 2
        cls_cols = []
        for key in cols:
            for g in groups:
                _bold(cs.cell(row=hdr2, column=col_i,
                              value=f"{colname(key)} {g}"))
                cls_cols.append((key, g))
                col_i += 1
        rr = hdr2 + 1
        for b in res["bins"]:
            cs.cell(row=rr, column=1, value=b["label"])
            for j, (key, g) in enumerate(cls_cols):
                cs.cell(row=rr, column=2 + j,
                        value=int(b["classes"].get(f"{key}:{g}", 0)))
            rr += 1
        _bold(cs.cell(row=rr, column=1, value="Total"))
        for j, (key, g) in enumerate(cls_cols):
            tot = sum(int(b["classes"].get(f"{key}:{g}", 0))
                      for b in res["bins"])
            _bold(cs.cell(row=rr, column=2 + j, value=tot))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path
