"""Corridor study delivery (Deliver+ATR plan, Part 1, 2026-08-28).

Generates the per-intersection client deliverables from LIVE
production events on the shipped basis: the Miovision-parity Excel
workbook + the PDF report for each of the five intersections, into
deliverables/corridor_2026-05-12/. Records each intersection's
export-gate verdict (generates regardless — operator-ordered
deliverable; verdicts go on the cover). Read-only over production.

Usage:  py -X utf8 scripts/deliver_corridor.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import get_connection                    # noqa: E402
from backend.services.excel_export import generate_miovision_xlsx  # noqa: E402
from backend.services.pdf_report import generate_report_pdf    # noqa: E402
from backend.services.spot_check import export_gate            # noqa: E402

PROJECT = "97a7849a"
OUT = Path("deliverables/corridor_2026-05-12")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    conn = get_connection(PROJECT)
    rows = conn.execute(
        "SELECT intersection_id, name, date FROM intersections "
        "ORDER BY sort_order, intersection_id").fetchall()
    conn.close()

    try:
        gate = export_gate(PROJECT)
    except Exception as e:
        gate = {"error": str(e)}
    verdicts = {}
    made = []
    for iid, name, date in rows:
        entry = None
        for it in (gate.get("intersections") or []):
            if it.get("intersection_id") == iid:
                entry = it
                break
        verdicts[iid] = {"name": name,
                         "gate": (entry or {}).get("overall", "n/a")}
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        xlsx = OUT / f"TMC_{safe}_{date}.xlsx"
        pdf = OUT / f"TMC_Report_{safe}_{date}.pdf"
        generate_miovision_xlsx(PROJECT, xlsx, iid)
        generate_report_pdf(PROJECT, pdf, intersection_id=iid)
        made += [xlsx, pdf]
        print(f"{name}: gate={verdicts[iid]['gate']} -> "
              f"{xlsx.name} ({xlsx.stat().st_size//1024} KB), "
              f"{pdf.name} ({pdf.stat().st_size//1024} KB)")
    (OUT / "gate_verdicts.json").write_text(
        json.dumps(verdicts, indent=2, default=str))
    print(f"\n{len(made)} deliverable files in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
