"""Stage 5.1A/B — the phantom-small-cell inventory + post-review ceiling
(plan_stage5_phantom_2026-07-29).

A (production basis, same as rule595.json / the recall study):
  every failing cell-bin classified PHANTOM-SMALL (ours > ref, ref <= 10)
  / OVERCOUNT (ours > ref, ref > 10) / UNDERCOUNT (ours < ref), joined
  against the POST-SWEEP open queue (shared join), per camera:
  the post-review CEILING = (bins - fails + caught_fails) / bins — what
  a perfect reviewer working today's queue could deliver, vs the 6.3
  interim gate >= 99%. Plus the top offender CELLS per class.

B (replay-cells basis from the LEC2 deliverable sweep — cell-level,
  never mixed with A): which base phantom-small CELLS the frozen LEC2
  bundle closes / improves / worsens per site.

Evidence -> runs/stage5_phantom/inventory.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import triangulate_manual as T
from backend.services.spot_check import _rec_offset_seconds
from rule595_compliance import CORRIDOR, DAYLIGHT, score
from rule595_queue_recall import BIG, PROJECT, flag_matches_bin, load_open_flags

OUT = Path("runs/stage5_phantom/inventory.json")
SWEEP = Path("runs/cam5_wall/sweep_deliverable.json")

PHANTOM_REF_MAX = 10          # per-bin: a near-empty reference cell
CELL_PHANTOM_REF_MAX = 30     # day-level cells in the sweep evidence
CELL_PHANTOM_MIN_EXCESS = 20


def classify(o: int, r: int) -> str:
    if o > r:
        return "phantom_small" if r <= PHANTOM_REF_MAX else "overcount"
    return "undercount"


def main() -> int:
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    result: dict = {"A_production": {}, "B_sweep_replay_cells": {}}

    for cam, hours in CORRIDOR.items():
        ours = T.load_ours(cam)
        mio = T.load_miovision(cam)
        if hours is None:
            minutes = [m for m in sorted(mio.keys())
                       if DAYLIGHT[0] <= m.hour < DAYLIGHT[1]]
        else:
            minutes = [dtime(h, m) for lo, hi in hours
                       for h in range(lo, hi) for m in range(60)]
        rows = score(ours, mio, minutes)
        fails = [r for r in rows if not r["ok"]]
        rec = _rec_offset_seconds(PROJECT, cam) or 0
        flags = load_open_flags(conn, cam)

        by_class = defaultdict(lambda: {"bins": 0, "big": 0, "caught": 0,
                                        "abs_delta": 0})
        cells = defaultdict(lambda: {"bins": 0, "abs_delta": 0, "cls": None})
        n_caught = 0
        for f in fails:
            cls = classify(f["ours"], f["ref"])
            d = abs(f["ours"] - f["ref"])
            caught = any(flag_matches_bin(fl, f["bin"], f["cell"], rec)
                         for fl in flags)
            n_caught += caught
            c = by_class[cls]
            c["bins"] += 1
            c["big"] += d >= BIG
            c["caught"] += caught
            c["abs_delta"] += d
            cc = cells[(f["cell"], cls)]
            cc["bins"] += 1
            cc["abs_delta"] += d
            cc["cls"] = cls

        n_bins, n_fails = len(rows), len(fails)
        ceiling = round(100.0 * (n_bins - n_fails + n_caught) / n_bins, 1)
        top = sorted(cells.items(), key=lambda kv: -kv[1]["abs_delta"])[:8]
        result["A_production"][f"cam{cam}"] = {
            "bins_scored": n_bins, "fails": n_fails, "caught": n_caught,
            "raw_compliance_pct": round(100.0 * (n_bins - n_fails) / n_bins, 1),
            "post_review_ceiling_pct": ceiling,
            "gap_to_6_3_gate": round(99.0 - ceiling, 1),
            "by_class": {k: dict(v) for k, v in sorted(by_class.items())},
            "top_offender_cells": [
                {"cell": cell, "class": v["cls"], "bins": v["bins"],
                 "abs_delta": v["abs_delta"]}
                for (cell, _cls), v in top],
        }
        a = result["A_production"][f"cam{cam}"]
        print(f"[PH] cam{cam}: ceiling {ceiling}% (raw "
              f"{a['raw_compliance_pct']}%, {n_caught}/{n_fails} caught) "
              f"classes: " + ", ".join(
                  f"{k} {v['bins']}b/{v['abs_delta']}veh"
                  f" ({v['caught']} caught)"
                  for k, v in sorted(by_class.items())), flush=True)
    conn.close()

    # --- B: the LEC2 sweep cross-view (replay-cells basis, named) -----------
    sweep = json.loads(SWEEP.read_text())
    for site, s in sweep.items():
        base, lec2 = s["base"]["cells"], s["lec2"]["cells"]
        rows_b = []
        for cell, (o, r) in base.items():
            if not (o - r > CELL_PHANTOM_MIN_EXCESS and r <= CELL_PHANTOM_REF_MAX):
                continue
            lo = lec2.get(cell, [0, r])[0]
            if abs(lo - r) <= 5:
                fate = "closed"
            elif abs(lo - r) < abs(o - r):
                fate = "improved"
            else:
                fate = "not_improved"
            rows_b.append({"cell": cell, "base_ours": o, "ref": r,
                           "lec2_ours": lo, "fate": fate})
        result["B_sweep_replay_cells"][site] = rows_b
        if rows_b:
            fates = defaultdict(int)
            for rr in rows_b:
                fates[rr["fate"]] += 1
            print(f"[PH] B {site}: phantom cells {len(rows_b)} -> "
                  f"{dict(fates)} :: " + "; ".join(
                      f"{rr['cell']} {rr['base_ours']}->{rr['lec2_ours']} "
                      f"(ref {rr['ref']})" for rr in rows_b[:4]), flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("PHANTOM INVENTORY DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
