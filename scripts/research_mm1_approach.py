"""Why arm mm1 lowers cam2's approach score: per 15-min bin x approach, the
cells whose 5/95 verdict flipped between the control (mm1c) and mm1, with the
movement cells that moved inside them. Dev-validation only.

Usage: .venv/Scripts/python.exe -X utf8 scripts/research_mm1_approach.py [CTRL ARM] [CAM]
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services.rule595 import score_cells  # noqa: E402
from v2_score_dev import (CORRIDOR, SITES, events_from_db, leg_dir_for,  # noqa: E402
                          load_miovision, per_min_from_events)

BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")


def _approach(pm):
    out = defaultdict(lambda: defaultdict(int))
    for mnt, cells in pm.items():
        for k, v in cells.items():
            out[mnt][k[0]] += v
    return out


def _bin_cells(pm, ms):
    c = defaultdict(int)
    for m in ms:
        for k, v in pm.get(m, {}).items():
            c[k] += v
    return c


def main() -> int:
    ctrl, arm = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("mm1c", "mm1")
    cam = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    site = SITES[CORRIDOR]
    leg_dir = leg_dir_for(CORRIDOR, cam, site)
    mio = load_miovision(cam, site)
    tally = defaultdict(int)
    for w in ("study_0700", "study_1100", "study_1600"):
        lo, hi = site["windows"][w]
        minutes = [m for m in (dtime(h, mm) for h in range(lo, hi) for mm in range(60)) if m in mio]
        pms = {s: per_min_from_events(events_from_db(str(BASE / f"{s}_cam{cam}_{w}.db"), cam, site),
                                      leg_dir) for s in (ctrl, arm)}
        rows = {s: {(r["bin"], r["cell"]): r for r in score_cells(_approach(pms[s]), _approach(mio), minutes)}
                for s in (ctrl, arm)}
        by_bin = defaultdict(list)
        for m in minutes:
            by_bin[f"{m.hour:02d}:{(m.minute // 15) * 15:02d}"].append(m)
        print(f"\n== cam{cam} {w}")
        for key in sorted(set(rows[ctrl]) | set(rows[arm])):
            a, b = rows[ctrl].get(key), rows[arm].get(key)
            ok_a, ok_b = bool(a and a["ok"]), bool(b and b["ok"])
            if ok_a == ok_b:
                continue
            tally["lost" if ok_a else "won"] += 1
            ref = (a or b)["ref"]
            print(f"  {key[0]} {key[1]:>3}: {'LOST' if ok_a else 'WON '}  Mio {ref}  ctrl {a and a['ours']}  "
                  f"{arm} {b and b['ours']}")
            ca, cb, cm = (_bin_cells(p, by_bin[key[0]]) for p in (pms[ctrl], pms[arm], mio))
            for k in sorted(set(ca) | set(cb)):
                if k[0] == key[1] and ca.get(k, 0) != cb.get(k, 0):
                    print(f"        {k[0]} {k[1]:>5}: Mio {cm.get(k, 0):>4}  ctrl {ca.get(k, 0):>4}  {arm} {cb.get(k, 0):>4}")
    print(f"\napproach cells flipped: lost {tally['lost']}  won {tally['won']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
