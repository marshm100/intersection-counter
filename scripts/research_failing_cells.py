"""Every FAILING 5/95 cell of an arm, fleet-wide (2026-10-11, operator: "how do we fix it?").
The deliverable is cell pass/fail per 15-min bin, so this lists, per window and per movement,
how many bins fail, in which direction (over / under Miovision), and by how much beyond the
tolerance. A movement that fails the same way in most bins is a SYSTEMATIC bias with one
cause; one that flips sign bin to bin is noise or timing. Dev-validation only.
Usage: .venv\\Scripts\python.exe -X utf8 scripts/research_failing_cells.py STEM [PREFIX]
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services.rule595 import score_cells, tolerance  # noqa: E402
from v2_score_dev import (CORRIDOR, SITES, events_from_db, leg_dir_for,  # noqa: E402
                          load_miovision, per_min_from_events)

BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"), (2, "study_1100"),
           (2, "study_1600"), (3, "study_0600"), (4, "study_0700"), (4, "study_1100"),
           (4, "study_1600"), (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "dt2c"
    pre = sys.argv[2] if len(sys.argv) > 2 else ""
    site = SITES[CORRIDOR]
    fleet = defaultdict(lambda: [0, 0, 0, 0.0, 0, 0])   # fails, over, under, excess, net, bins
    n_cells = n_fail = 0
    for cam, w in WINDOWS:
        db = BASE / f"{stem}_cam{cam}_{pre}{w}.db"
        lo, hi = site["windows"][w]
        minutes = [dtime(h, m) for h in range(lo, hi) for m in range(60)]
        leg_dir = leg_dir_for(CORRIDOR, cam, site)
        mio = load_miovision(cam, site)
        rows = score_cells(per_min_from_events(events_from_db(str(db), cam, site), leg_dir), mio,
                           [m for m in minutes if m in mio])
        n_cells += len(rows)
        by = defaultdict(list)
        for r in rows:
            by[r["cell"]].append(r)
        print(f"\n== cam{cam} {w}: {sum(r['ok'] for r in rows)}/{len(rows)} cells pass")
        for cell, rs in sorted(by.items(), key=lambda kv: -sum(not r["ok"] for r in kv[1])):
            fails = [r for r in rs if not r["ok"]]
            if not fails:
                continue
            n_fail += len(fails)
            over = sum(r["ours"] > r["ref"] for r in fails)
            ex = [abs(r["ours"] - r["ref"]) - tolerance(r["ref"]) for r in fails]
            net = sum(r["ours"] - r["ref"] for r in rs)
            ref = sum(r["ref"] for r in rs)
            f = fleet[(cam, cell)]
            f[0] += len(fails); f[1] += over; f[2] += len(fails) - over; f[3] += sum(ex); f[4] += net; f[5] += len(rs)
            print(f"  {cell:10} fails {len(fails)}/{len(rs)} bins  over {over} under {len(fails) - over}  "
                  f"beyond tolerance by {min(ex):.0f}-{max(ex):.0f} veh  window net {net:+d} of {ref} "
                  f"({100 * net / max(ref, 1):+.1f}%)  bins: "
                  + " ".join(f"{r['ours'] - r['ref']:+d}{'' if r['ok'] else '!'}" for r in rs))
    print(f"\nFLEET: {n_fail} failing cells of {n_cells}")
    print("by camera x movement (fails, over, under, mean excess beyond tolerance, net over all its bins):")
    for (cam, cell), f in sorted(fleet.items(), key=lambda kv: -kv[1][0]):
        print(f"  cam{cam} {cell:10} {f[0]:3} fails of {f[5]:3}  over {f[1]:3} under {f[2]:3}  "
              f"excess {f[3] / f[0]:5.1f}  net {f[4]:+d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
