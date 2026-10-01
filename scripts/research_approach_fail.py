"""Where do the APPROACH bins fail? (2026-10-01)

For each production window: every approach x 15-min bin (the PRD 7.2 bar, scripts/v2_score_dev.py's
two-level scoring), ours vs Miovision, pass/fail, and the failing bins' sign. Also the
movement-level breakdown of each failing approach-bin, so an over/undercount can be traced to
the movements that carry it.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_approach_fail.py [CAM:WINDOW ...]
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import v2_score_dev as S  # noqa: E402
from backend.services.rule595 import score_cells  # noqa: E402

WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"), (2, "study_1100"),
           (2, "study_1600"), (3, "study_0600"), (4, "study_0700"), (4, "study_1100"),
           (4, "study_1600"), (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]


def approach(pm):
    out = defaultdict(lambda: defaultdict(int))
    for mnt, cells in pm.items():
        for k, v in cells.items():
            out[mnt][k[0]] += v
    return out


def main() -> int:
    wins = ([(int(a.split(":")[0]), a.split(":")[1]) for a in sys.argv[1:]] or WINDOWS)
    site = S.SITES[S.CORRIDOR]
    tally = Counter()
    for cam, variant in wins:
        lo, hi = site["windows"][variant]
        minutes = [dtime(h, m) for h in range(lo, hi) for m in range(60)]
        leg_dir = S.leg_dir_for(S.CORRIDOR, cam, site)
        mio = S.load_miovision(cam, site)
        mm = [m for m in minutes if m in mio]
        ours = S.load_production(S.CORRIDOR, cam, site, leg_dir)
        arows = score_cells(approach(ours), approach(mio), mm)
        mrows = score_cells(ours, mio, mm)
        ok = sum(r["ok"] for r in arows)
        print(f"\n=== cam{cam} {variant}: approach {ok}/{len(arows)} pass ===")
        by_app = defaultdict(list)
        for r in arows:
            by_app[r["cell"]].append(r)
        for app, rs in sorted(by_app.items()):
            fails = [r for r in rs if not r["ok"]]
            over = sum(1 for r in fails if r["ours"] > r["ref"])
            tot_o, tot_r = sum(r["ours"] for r in rs), sum(r["ref"] for r in rs)
            print(f"  {app}: {len(rs) - len(fails)}/{len(rs)} pass  ours {tot_o} vs Mio {tot_r} "
                  f"({100 * (tot_o - tot_r) / max(tot_r, 1):+.1f}%)  fails: {over} over, "
                  f"{len(fails) - over} under")
            tally[(cam, app, "over")] += over
            tally[(cam, app, "under")] += len(fails) - over
            for r in fails:
                mv = [m for m in mrows if m["bin"] == r["bin"] and m["cell"].startswith(app + " ")]
                parts = ", ".join(f"{m['cell'].split(' ', 1)[1]} {m['ours']}/{m['ref']}"
                                  for m in mv if m["ours"] != m["ref"])
                print(f"     {r['bin']}  {r['ours']} vs {r['ref']} ({r['ours'] - r['ref']:+d})  [{parts}]")
    print("\nFAILING APPROACH-BINS by camera, approach, sign:")
    for k, n in sorted(tally.items()):
        if n:
            print(f"  cam{k[0]} {k[1]} {k[2]}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
