"""Stage 5.2 — the AUTHORIZED LEC2-under-5/95 judgment
(plan_stage5_phantom_2026-07-29, section 5.2; operator "authorized").

Re-judges the FROZEN LEC2 bundle (constants exactly as committed; the
sweep harness's own event streams — no refitting, no new replays: all
BASE/lpatch40 DBs exist) at THE CUSTOMER BAR: per-bin 5/95 cell-bin
compliance via backend/services/rule595.score_cells, BASE vs LEC2, per
site. cam3 is scored on its DAYLIGHT cut — the same basis every
Stage-1..5 5/95 number uses.

Pre-declared per-camera gates (the plan doc, before this script ran):
  G1 compliance strictly improves;
  G2 no NEW BIG failing bin (|delta| >= 20) created;
  G3 fixed/broken: net flips positive AND broken <= 20% of fixed;
  G4a cam3 hard-stop cells (E right / N left): |delta| totals not worse;
  G4b eaten-vehicle detector (the cam4 STAT trap): per-camera undercount
      mass (sum of max(0, ref-ours) over bins) up by <= 5%;
  G5 FM51 (held-out, ftv2n replay basis): same gates.

Basis: replayed-minutes (the deliverable-sweep basis), GT = Miovision
per-minute. Named; never mixed with production numbers.
Evidence -> runs/stage5_phantom/lec2_595_judgment.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.rule595 import compliance, score_cells
from lane_echo_sweep import SWEEP, gt_perminute, lec2_events, score
from rule595_compliance import DAYLIGHT

OUT = Path("runs/stage5_phantom/lec2_595_judgment.json")
BIG = 20
CAM3_HARDSTOP_CELLS = {("E", "right"), ("N", "left")}


def undercount_mass(rows) -> int:
    return sum(max(0, r["ref"] - r["ours"]) for r in rows)


def main() -> int:
    result: dict = {}
    for project, cam, windows, hours in SWEEP:
        key = f"{project[:4]}:c{cam}"
        scratch = Path(f"data/projects/{project}/_replay_scratch")
        gt = gt_perminute(project, cam)
        base_pm = defaultdict(lambda: defaultdict(int))
        lec_pm = defaultdict(lambda: defaultdict(int))
        for w in windows:
            b, k, legcard = lec2_events(project, cam, w, scratch)
            for evl, dst in ((b, base_pm), (k, lec_pm)):
                for m, cells in score(evl, legcard).items():
                    for kk, v in cells.items():
                        dst[m][kk] += v
        if hours is None:                      # cam3: the daylight cut
            mins = [m for m in sorted(gt.keys())
                    if DAYLIGHT[0] <= m.hour < DAYLIGHT[1]]
        else:
            mins = [dtime(h, m) for lo, hi in hours
                    for h in range(lo, hi) for m in range(60)]

        rows_b = score_cells(base_pm, gt, mins)
        rows_l = score_cells(lec_pm, gt, mins)
        cb, cl = compliance(rows_b), compliance(rows_l)
        bmap = {(r["bin"], r["cell"]): r for r in rows_b}
        lmap = {(r["bin"], r["cell"]): r for r in rows_l}
        keys = set(bmap) | set(lmap)

        fixed = broken = 0
        new_big = []
        for kk in keys:
            b_ok = bmap.get(kk, {"ok": True})["ok"]
            l_ok = lmap.get(kk, {"ok": True})["ok"]
            if not b_ok and l_ok:
                fixed += 1
            if b_ok and not l_ok:
                broken += 1
            l_r = lmap.get(kk)
            if l_r is not None and not l_ok and \
                    abs(l_r["ours"] - l_r["ref"]) >= BIG:
                b_r = bmap.get(kk)
                was_big = (b_r is not None and not b_r["ok"]
                           and abs(b_r["ours"] - b_r["ref"]) >= BIG)
                if not was_big:
                    new_big.append({"bin": kk[0], "cell": str(kk[1]),
                                    "ours": l_r["ours"], "ref": l_r["ref"]})

        um_b, um_l = undercount_mass(rows_b), undercount_mass(rows_l)
        g1 = (cl["pct"] or 0) > (cb["pct"] or 0)
        g2 = not new_big
        g3 = fixed - broken > 0 and broken <= 0.2 * fixed
        g4b = um_l <= um_b * 1.05
        gates = {"G1_compliance_improves": g1, "G2_no_new_big": g2,
                 "G3_flips": g3, "G4b_no_eaten_vehicles": g4b}
        if cam == 3 and project == "97a7849a":
            worse = {}
            for cell in CAM3_HARDSTOP_CELLS:
                db_ = sum(abs(r["ours"] - r["ref"]) for r in rows_b
                          if r["cell"] == " ".join(cell))
                dl_ = sum(abs(r["ours"] - r["ref"]) for r in rows_l
                          if r["cell"] == " ".join(cell))
                worse[" ".join(cell)] = {"base": db_, "lec2": dl_}
            gates["G4a_cam3_cells"] = all(
                v["lec2"] <= v["base"] for v in worse.values())
            result_hs = worse
        else:
            result_hs = None

        verdict = all(gates.values())
        result[key] = {
            "compliance_base_pct": cb["pct"], "compliance_lec2_pct": cl["pct"],
            "cells_scored": cb["cells_scored"],
            "fixed": fixed, "broken": broken, "new_big": new_big[:6],
            "undercount_mass": {"base": um_b, "lec2": um_l},
            "hardstop_cells": result_hs,
            "gates": gates, "verdict": "PASS" if verdict else "FAIL",
        }
        print(f"[J] {key}: 5/95 {cb['pct']}% -> {cl['pct']}%  "
              f"fixed {fixed} broken {broken} new_big {len(new_big)} "
              f"undercount {um_b}->{um_l}  "
              f"{'PASS' if verdict else 'FAIL'} "
              f"({[g for g, v in gates.items() if not v]})", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("LEC2 595 JUDGMENT DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
