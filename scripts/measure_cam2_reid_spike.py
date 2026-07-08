"""Phase-3 measurement for the cam2 ReID generalization spike
(docs/plan_reid_cam2_spike_2026-07-07.md).

Measures ANY events DB (live project.db baseline, or the Phase-2 working final DB)
against Miovision over the 07:00-07:30 window, per (approach-direction, movement)
cell, with the same keying as corridor_per_approach_baseline.py / interval_metric
so numbers are comparable to the stored ~7.9% per-approach baseline.

Miovision here is the DEV yardstick only (CLAUDE.md prime directive) — nothing in
the pipeline consumes it; this script only scores a finished run.

Usage:
  py scripts/measure_cam2_reid_spike.py --db data/projects/97a7849a/project.db
  py scripts/measure_cam2_reid_spike.py --db <workdir>/prod_final_cam2.db
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import triangulate_manual as T
import interval_metric as IM

PROJECT = "97a7849a"
NORM = {"through": "thru", "u_turn": "uturn", "left": "left", "right": "right"}

# The four collinear cells the spike must close (plan doc, baseline signed deltas):
WATCH = {("EB", "right"): +31, ("SB", "thru"): -43, ("NB", "left"): -66, ("EB", "thru"): -27}


def load_events_db(db: str, cam: int) -> T.PerMin:
    """Same as triangulate_manual.load_ours but for an arbitrary DB path.
    leg cardinal_direction always comes from the PROJECT db (working DBs carry
    the same legs table, but the live one is authoritative)."""
    pc = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    leg_dir = {lid: T._CARD_TO_DIR.get((card or "").strip().upper())
               for lid, card in pc.execute(
                   "SELECT leg_id,cardinal_direction FROM legs WHERE camera_id=?", (cam,))}
    pc.close()
    c = sqlite3.connect(db)
    out: T.PerMin = defaultdict(lambda: defaultdict(int))
    n_events = 0
    for olid, mv, ts in c.execute(
            "SELECT origin_leg_id, movement, timestamp_real FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,)):
        d = leg_dir.get(olid)
        if ts and d:
            key = datetime.fromisoformat(ts).time().replace(second=0, microsecond=0)
            out[key][(d, NORM.get(mv, mv))] += 1
            n_events += 1
    c.close()
    out["_n_events"] = n_events  # stashed count (popped by caller)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="events DB to score")
    ap.add_argument("--camera", type=int, default=2)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=int, default=30)
    args = ap.parse_args()

    h, m, _ = (int(x) for x in args.start_hms.split(":"))
    window = [time((h + (m + i) // 60) % 24, (m + i) % 60) for i in range(args.minutes)]
    wset = set(window)

    mio = T.load_miovision(args.camera)
    ours = load_events_db(args.db, args.camera)
    n_events_all = ours.pop("_n_events")

    # ---- per-cell window totals + signed deltas ----
    man_cell: dict[tuple, int] = defaultdict(int)
    our_cell: dict[tuple, int] = defaultdict(int)
    for t in window:
        for cell, n in mio.get(t, {}).items():
            man_cell[cell] += n
        for cell, n in ours.get(t, {}).items():
            our_cell[cell] += n
    cells = sorted(set(man_cell) | set(our_cell),
                   key=lambda c: -abs(our_cell.get(c, 0) - man_cell.get(c, 0)))

    tot_man = sum(man_cell.values())
    tot_our = sum(our_cell.values())
    n_win_events = sum(our_cell.values())

    print(f"\n=== cam{args.camera}  {args.start_hms} +{args.minutes}min   db={args.db} ===")
    print(f"{'cell':<12}{'mio':>6}{'ours':>6}{'delta':>7}   (watch-cell baseline)")
    for cell in cells:
        man, our = man_cell.get(cell, 0), our_cell.get(cell, 0)
        if man == 0 and our == 0:
            continue
        d, mv = cell
        mark = f"   <- WATCH (was {WATCH[cell]:+d})" if cell in WATCH else ""
        print(f"{d+'-'+mv:<12}{man:>6}{our:>6}{our-man:>+7}{mark}")
    net = (tot_our - tot_man) / tot_man * 100 if tot_man else float("nan")
    print(f"{'TOTAL':<12}{tot_man:>6}{tot_our:>6}{tot_our-tot_man:>+7}   net {net:+.1f}%")

    # ---- THE metric: per-approach AVG |err| per 15-min interval, windowed ----
    res = IM.per_interval(ours, mio, minutes=window, by_approach=True)
    print(f"\nAVG |err| per 15-min interval (windowed): "
          f"{res['avg_abs_err_pct']}%  [{res['verdict']}]  (n_bins={res['n_bins']})")
    pa = [(d, r) for d, r in sorted(res["per_approach"].items()) if r["n_bins"]]
    for d, r in pa:
        print(f"    {d:<3} AVG |err| {r['avg_abs_err_pct']:5.1f}%  [{r['verdict']:<4}]"
              f"  max {r['max_abs_err_pct']:.1f}% @{r['worst_interval']}")
    vals = [r["avg_abs_err_pct"] for _, r in pa]
    if vals:
        print(f"    per-approach MAE (mean of approaches): {sum(vals)/len(vals):.1f}%")

    # ---- sanity: fragmentation / phantom pressure ----
    print(f"\nevents in window: {n_win_events}   (whole DB, this cam: {n_events_all})"
          f"   vs Miovision {tot_man} real vehicles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
