"""Arm-vs-basis comparison for a declared gate (G-SM-1, 2026-09-09).

Reads runs/v2_week1/score_{basis}_cam{c}_{variant}.json and
score_{arm}_... for each window, prints movement / approach deltas, the
full cell table (Mio | basis | arm | production) and the PHANTOM-SLACK
check: any cell under 10 in Miovision that GREW in the arm is flagged —
sub-10-Mio cells passing on the +-5 slack are not wins.

Usage:  py -X utf8 scripts/arm_compare.py BASIS_STEM ARM_STEM cam1:study_0700 ...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load(stem, cam, variant):
    p = Path(f"runs/v2_week1/score_{stem}_cam{cam}_{variant}.json")
    return json.loads(p.read_text()) if p.exists() else None


def main() -> int:
    basis, arm = sys.argv[1], sys.argv[2]
    windows = [(w.split(":")[0].replace("cam", ""), w.split(":")[1])
               for w in sys.argv[3:]]
    print(f"{'window':16}{basis:>8}{arm:>8}{'delta':>8}   "
          f"{'app:'+basis:>10}{'app:'+arm:>9}")
    rows = []
    for cam, variant in windows:
        b, a = load(basis, cam, variant), load(arm, cam, variant)
        if a is None:
            print(f"cam{cam} {variant:11} arm missing")
            continue
        bp = b["v2"]["pct"] if b else None
        ap = a["v2"]["pct"]
        d = f"{ap - bp:+.1f}" if bp is not None else "?"
        print(f"cam{cam} {variant:11}{bp if bp is not None else '-':>8}"
              f"{ap:>8}{d:>8}   "
              f"{b['v2_approach']['pct'] if b else '-':>10}"
              f"{a['v2_approach']['pct']:>9}")
        rows.append((cam, variant, b, a))
    for cam, variant, b, a in rows:
        print(f"\n=== {cam} {variant}  cells: Mio | {basis} | {arm} | prod ===")
        tb = b["totals"] if b else {}
        ta = a["totals"]
        slack = []
        for cell in sorted(set(tb) | set(ta)):
            mio, arm_n, prod = ta.get(cell, [tb.get(cell, [0])[0], 0, 0])
            bas_n = tb.get(cell, [0, None])[1]
            flag = ""
            if mio < 10 and bas_n is not None and arm_n > bas_n:
                flag = "  <-- SUB-10-MIO CELL GREW (phantom slack)"
                slack.append(cell)
            elif mio < 10 and arm_n > mio + 5:
                flag = "  <-- sub-10-Mio cell over slack"
            print(f"{cell:>10} {mio:>7} {bas_n if bas_n is not None else '-':>7}"
                  f" {arm_n:>7} {prod:>7}{flag}")
        print(f"phantom-slack check: "
              f"{'CLEAN' if not slack else 'FAIL ' + ', '.join(slack)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
