"""Score production counts against the CUSTOMER standard — Miovision's
5/95 rule (operator-provided 2026-07-28):

  per movement cell per 15-min bin:
    ref <= 100  ->  |ours - ref| <= 5 vehicles   (absolute grace)
    ref  > 100  ->  |ours - ref| / ref <= 5%     (95% accurate)

Scored per camera over the deliverable's claimed windows (trims where
declared; cam3 full-day AND a daylight cut — Miovision's own guarantee
EXCLUDES night). Cells = (bound, movement) present in either source per
bin (a phantom cell vs ref 0 must fit inside +/-5 too).

Basis: PRODUCTION project.db events vs Miovision per-minute XML — the
shipping config against the customer metric.
Evidence -> runs/3b_validation/rule595.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import triangulate_manual as T
import gate3b_fm51 as FM

OUT = Path("runs/3b_validation/rule595.json")

CORRIDOR = {
    1: [(7, 9), (16, 18)],
    2: [(7, 9), (11, 13), (16, 18)],
    3: None,                      # full day; daylight cut reported too
    4: [(7, 9), (11, 13), (16, 18)],
    5: [(7, 9), (11, 13), (16, 18)],
}
DAYLIGHT = (6, 20)                # cam3's daylight cut (Mio night exclusion)


from backend.services.rule595 import compliance, score_cells


def score(ours, ref, minutes):
    return score_cells(ours, ref, minutes)


def main() -> int:
    result = {}
    for cam, hours in CORRIDOR.items():
        ours = T.load_ours(cam)
        mio = T.load_miovision(cam)
        if hours is None:
            all_min = sorted(mio.keys())
            rows = score(ours, mio, all_min)
            day_min = [m for m in all_min if DAYLIGHT[0] <= m.hour < DAYLIGHT[1]]
            rows_day = score(ours, mio, day_min)
            result[f"cam{cam}"] = {"full_day": compliance(rows),
                                   "daylight_only": compliance(rows_day)}
            print(f"[595] cam{cam}: full {result[f'cam{cam}']['full_day']['pct']}% "
                  f"daylight {result[f'cam{cam}']['daylight_only']['pct']}%",
                  flush=True)
        else:
            minutes = [dtime(h, m) for lo, hi in hours
                       for h in range(lo, hi) for m in range(60)]
            rows = score(ours, mio, minutes)
            result[f"cam{cam}"] = compliance(rows)
            print(f"[595] cam{cam}: {result[f'cam{cam}']['pct']}% "
                  f"({result[f'cam{cam}']['compliant']}/{result[f'cam{cam}']['cells_scored']}) "
                  f"worst={result[f'cam{cam}']['worst'][:2]}", flush=True)

    # FM51 (stock-era production table, the held-out site)
    mio_pm, appr = FM.load_mio_perminute()
    import sqlite3
    from backend.services.cardinals import OPPOSITE
    from collections import defaultdict as dd
    conn = sqlite3.connect("data/projects/0acb12c0/project.db")
    card = {lid: cd for lid, cd in conn.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=2")}
    sys_bound = dd(int)
    evs = list(conn.execute(
        "SELECT origin_leg_id, destination_leg_id, movement, timestamp_video "
        "FROM vehicle_events WHERE camera_id=2 AND COALESCE(rejected,0)=0"))
    conn.close()
    for ol, _dl, _mv, _ts in evs:
        sys_bound[OPPOSITE.get((card.get(ol) or "").upper(), "")] += 1
    tot = dd(int)
    for cells in mio_pm.values():
        for (ai, _mv), n in cells.items():
            tot[ai] += n
    used, ai2b = set(), {}
    for ai, t_ in sorted(tot.items(), key=lambda kv: -kv[1]):
        best = min((b for b in sys_bound if b not in used),
                   key=lambda b: abs(sys_bound[b] - t_), default=None)
        if best is not None:
            ai2b[ai], _ = best, used.add(best)
    from datetime import datetime, timedelta
    REC = datetime.fromisoformat("2026-04-30T00:00:03")
    ours_fm = dd(lambda: dd(int))
    norm = {"through": "through", "left": "left", "right": "right",
            "u_turn": "u_turn"}
    for ol, _dl, mv, ts in evs:
        if ts is None:
            continue
        t_ = (REC + timedelta(seconds=float(ts))).time().replace(
            second=0, microsecond=0)
        b = OPPOSITE.get((card.get(ol) or "").upper(), "")
        if b:
            ours_fm[t_][(b, norm.get(mv, mv))] += 1
    ref_fm = dd(lambda: dd(int))
    for t_, cells in mio_pm.items():
        key = t_.time().replace(second=0, microsecond=0)
        for (ai, mv), n in cells.items():
            b = ai2b.get(ai)
            if b:
                ref_fm[key][(b, mv)] += n
    fm_minutes = [dtime(h, m) for lo, hi in [(7, 9), (16, 18)]
                  for h in range(lo, hi) for m in range(60)]
    rows = score(ours_fm, ref_fm, fm_minutes)
    result["fm51_stock_era"] = compliance(rows)
    print(f"[595] FM51 (stock-era table): {result['fm51_stock_era']['pct']}% "
          f"worst={result['fm51_stock_era']['worst'][:2]}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("RULE595 DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
