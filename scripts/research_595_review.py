"""CAN A REVIEWER CLOSE THE 5/95 GAP? (2026-10-15, operator: "the data we bring humans in the loop to do must be
able to get the bar above the 5/95 rule ... yes run them"). The shipped default (stem mm1) fails 98 of 1228
movement cell-bins and 79 of 487 approach cell-bins, ~25 vehicles per hour of video beyond tolerance. Two questions,
per window, label-free on the app's side (Miovision is used only to score):
  Q1 TARGETING  can the app tell WHICH cell-bins need review without Miovision?
       - production queue (review_flags, open): share of failing cell-bins with a matching flag
         (rule595_queue_recall.flag_matches_bin), and of passing ones (wasted review)
       - encounter flags (research_review_queue.flags: two counted tracks meeting where a count can change):
         the cell-bin's FLAGGED COUNTS (its counted events on a flag); review the cell-bins with the most flagged
         counts first - recall of failing cell-bins at the top 10 / 20 / 30% of cell-bins by that rank
  Q2 DIRECTION  in a failing cell-bin, do the flags hold enough corrections of the right sign?
       - OVER (ours > ref): flagged counts >= the excess beyond tolerance (each removable on review)
       - UNDER: encounter flags sit on counted events and cannot add a car; reported (production gap flags only)
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_595_review.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, time as dtime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services.rule595 import score_cells, tolerance  # noqa: E402
from backend.services.spot_check import _rec_offset_seconds  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402
from research_near_twins import WINDOWS  # noqa: E402
from research_review_queue import flags as encounter_flags  # noqa: E402
from rule595_queue_recall import flag_matches_bin, load_open_flags  # noqa: E402
from v2_score_dev import CORRIDOR, NORM, SITES, leg_dir_for, load_miovision  # noqa: E402

TOPS = (0.1, 0.2, 0.3)


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    site = SITES[CORRIDOR]
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    every = {"mov": [], "appr": []}
    for cam, w in WINDOWS:
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
        fps = float(fps)
        db, rows = locate(stem, {}, cam, w, chash)
        lo, hi = site["windows"][w]
        minutes = [dtime(h, m) for h in range(lo, hi) for m in range(60)]
        ld = leg_dir_for(CORRIDOR, cam, site)
        mio = load_miovision(cam, site)
        mm = [m for m in minutes if m in mio]
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        evs = [dict(zip(("tid", "o", "mv", "ts"), r)) for r in d.execute(
            "SELECT vehicle_track_id, origin_leg_id, movement, timestamp_real FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,)) if r[3]]
        d.close()
        flagged = {t for f in encounter_flags(db, rows, cam, fps) for t in (f["a"], f["b"])}
        ours = {"mov": defaultdict(lambda: defaultdict(int)), "appr": defaultdict(lambda: defaultdict(int))}
        nflag = {"mov": Counter(), "appr": Counter()}
        for e in evs:
            dr = ld.get(e["o"])
            if not dr:
                continue
            tm = datetime.fromisoformat(e["ts"]).time().replace(second=0, microsecond=0)
            mv = NORM.get(e["mv"], e["mv"])
            ours["mov"][tm][(dr, mv)] += 1
            ours["appr"][tm][dr] += 1
            if e["tid"] is not None and int(e["tid"]) in flagged:
                b = f"{tm.hour:02d}:{(tm.minute // 15) * 15:02d}"
                nflag["mov"][(b, f"{dr} {mv}")] += 1
                nflag["appr"][(b, dr)] += 1
        refa = defaultdict(lambda: defaultdict(int))
        for m, cells in mio.items():
            for k, v in cells.items():
                refa[m][k[0]] += v
        rec = _rec_offset_seconds(PROJ, cam) or 0
        pflags = load_open_flags(con, cam)
        for lvl, ref in (("mov", mio), ("appr", refa)):
            for r in score_cells(ours[lvl], ref, mm):
                tol = tolerance(r["ref"])
                ex = max(0.0, abs(r["ours"] - r["ref"]) - tol)
                prod = lvl == "mov" and any(flag_matches_bin(f, r["bin"], r["cell"], rec) for f in pflags)
                every[lvl].append({"cam": cam, "w": w, "bin": r["bin"], "cell": r["cell"], "ok": r["ok"],
                                   "over": r["ours"] > r["ref"], "ex": ex, "n": r["ours"],
                                   "flagged": nflag[lvl][(r["bin"], r["cell"])], "prod": prod})
        print(f"cam{cam} {w}: {len(evs)} counts, {len(flagged)} flagged tracks, {len(pflags)} open production flags",
              flush=True)

    for lvl, name in (("mov", "MOVEMENT cell-bins"), ("appr", "APPROACH cell-bins")):
        A = every[lvl]
        fail = [x for x in A if not x["ok"]]
        print(f"\n=== {name}: {len(fail)} failing of {len(A)}; vehicles beyond tolerance {sum(x['ex'] for x in fail):.0f}")
        if lvl == "mov":
            pc = sum(x["prod"] for x in fail)
            pp = sum(x["prod"] for x in A if x["ok"])
            print(f"  Q1 production queue: flags {pc}/{len(fail)} failing cell-bins "
                  f"({100 * pc / max(len(fail), 1):.0f}%); also on {pp}/{len(A) - len(fail)} passing ones")
        order = sorted(A, key=lambda x: (-x["flagged"], -x["n"]))
        for top in TOPS:
            k = int(round(top * len(A)))
            sel = order[:k]
            got = [x for x in sel if not x["ok"]]
            exg = sum(x["ex"] for x in got)
            print(f"  Q1 encounter rank: review the top {top:.0%} of cell-bins ({k}) by flagged counts -> "
                  f"{len(got)}/{len(fail)} failing cell-bins ({100 * len(got) / max(len(fail), 1):.0f}%), "
                  f"{exg:.0f}/{sum(x['ex'] for x in fail):.0f} excess vehicles; flagged counts to review "
                  f"{sum(x['flagged'] for x in sel)}")
        over = [x for x in fail if x["over"]]
        under = [x for x in fail if not x["over"]]
        enough = [x for x in over if x["flagged"] >= x["ex"]]
        three = [x for x in over if x["flagged"] >= 3 * x["ex"]]
        print(f"  Q2 OVER  {len(over)} failing cell-bins (excess {sum(x['ex'] for x in over):.0f}): flagged counts >= excess "
              f"in {len(enough)}, >= 3x excess in {len(three)}; median flagged/excess "
              f"{np.median([x['flagged'] / max(x['ex'], 1) for x in over]) if over else 0:.1f}")
        print(f"  Q2 UNDER {len(under)} failing cell-bins (excess {sum(x['ex'] for x in under):.0f}): encounter flags cannot "
              f"add a car" + (f"; production flag present on {sum(x['prod'] for x in under)}" if lvl == "mov" else ""))
        for x in sorted(fail, key=lambda x: -x["ex"])[:10]:
            print(f"     cam{x['cam']} {x['w']} {x['bin']} {x['cell']:10} {'OVER ' if x['over'] else 'UNDER'} "
                  f"excess {x['ex']:5.1f}  counts {x['n']:4}  flagged {x['flagged']:3}  prod-flag {'Y' if x['prod'] else '.'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
