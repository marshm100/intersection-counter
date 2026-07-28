"""THE customer standard as a service — the Miovision 5/95 rule
(plan_595_standard_2026-07-28, Stage 1.1; operator directive: this IS
the bar; the old interval-MAE metric is a diagnostic).

The rule, per classification cell per 15-minute bin:
    ref <= 100  ->  |ours - ref| <= 5 vehicles   (absolute grace)
    ref  > 100  ->  |ours - ref| / ref <= 5%     (95% accurate)

Windows longer than one bin scale the SMALL-CELL branch per-bin: a
W-minute window has bins_equiv = W/15; the absolute grace is +/-5 per
15-min equivalent (ref/bins_equiv <= 100 -> tol = 5*bins_equiv), and
the 5%-relative branch is scale-free. This is the faithful extension —
each 15-min slice carries +/-5 — used by the spot gate whose manual
counts are window totals.

Pure functions only; DEV drivers (scripts/rule595_compliance.py) and
the acceptance gate (spot_check) both import from here.
"""
from __future__ import annotations

from collections import defaultdict

SMALL_CELL_MAX_PER_BIN = 100
ABS_TOL_PER_BIN = 5.0
REL_TOL = 0.05


def tolerance(ref: float, bins_equiv: float = 1.0) -> float:
    """The allowed |ours - ref| for a cell whose reference is `ref`
    vehicles over `bins_equiv` 15-minute bins."""
    b = max(bins_equiv, 1e-9)
    if ref / b <= SMALL_CELL_MAX_PER_BIN:
        return ABS_TOL_PER_BIN * b
    return REL_TOL * ref


def rule_ok(ours: float, ref: float, bins_equiv: float = 1.0) -> bool:
    return abs(ours - ref) <= tolerance(ref, bins_equiv)


def score_cells(ours_perminute: dict, ref_perminute: dict, minutes,
                bin_min: int = 15, min_minutes: int = 10) -> list[dict]:
    """Per-bin per-cell 5/95 rows over two {minute: {cell: n}} sources.
    Cells present in EITHER source are scored (a phantom cell vs ref 0
    must fit inside +/-5 too). Bins need >= min_minutes covered minutes."""
    by_bin = defaultdict(list)
    for m in minutes:
        by_bin[(m.hour, m.minute // bin_min)].append(m)
    rows = []
    for b, ms in sorted(by_bin.items()):
        if len(ms) < min_minutes:
            continue
        o_cells: dict = defaultdict(int)
        r_cells: dict = defaultdict(int)
        for m in ms:
            for k, v in ours_perminute.get(m, {}).items():
                o_cells[k] += v
            for k, v in ref_perminute.get(m, {}).items():
                r_cells[k] += v
        for cell in sorted(set(o_cells) | set(r_cells), key=str):
            o, r = o_cells.get(cell, 0), r_cells.get(cell, 0)
            if o == 0 and r == 0:
                continue
            rows.append({"bin": f"{b[0]:02d}:{b[1]*bin_min:02d}",
                         "cell": cell if isinstance(cell, str)
                         else " ".join(str(x) for x in cell),
                         "ours": o, "ref": r,
                         "ok": rule_ok(o, r, bins_equiv=len(ms) / bin_min)})
    return rows


def compliance(rows: list[dict], worst_n: int = 8) -> dict:
    n = len(rows)
    ok = sum(1 for r in rows if r["ok"])
    worst = sorted((r for r in rows if not r["ok"]),
                   key=lambda r: -(abs(r["ours"] - r["ref"])))
    return {"cells_scored": n, "compliant": ok,
            "pct": round(100.0 * ok / n, 1) if n else None,
            "worst": [{k: r[k] for k in ("bin", "cell", "ours", "ref")}
                      for r in worst[:worst_n]]}
