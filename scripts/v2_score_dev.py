"""Pipeline-V2 D5 — dev scorer (plan_v2_week1_derisk §D5).

THE ONLY V2 MODULE THAT READS MIOVISION (dev-validation basis; never a
runtime input). Scores, on one window's Miovision-covered minutes:
  (a) V2 events (any events_*.json from D4),
  (b) the PRODUCTION vehicle_events table (same minutes, for reference),
against per-cell per-15-min 5/95 + the named wall signatures.

Usage:
  py -X utf8 scripts/v2_score_dev.py runs/v2_week1/events_cam2_study_0700_greedy.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import triangulate_manual as T                          # noqa: E402
from backend.services.rule595 import compliance, score_cells  # noqa: E402

NORM = {"through": "thru", "u_turn": "uturn"}
WINDOW_HOURS = {"study_0700": (7, 9), "study_1100": (11, 13),
                "study_1600": (16, 18), "study_0600": (6, 20)}


def per_min_from_events(events: list[dict], leg_dir: dict[int, str]):
    out = defaultdict(lambda: defaultdict(int))
    for e in events:
        d = leg_dir.get(e["origin_leg"])
        if not d:
            continue
        tm = datetime.fromisoformat(e["wallclock"]).time().replace(
            second=0, microsecond=0)
        out[tm][(d, NORM.get(e["movement"], e["movement"]))] += 1
    return out


def cell_totals(pm, minutes):
    tot = defaultdict(int)
    mset = set(minutes)
    for tm, cells in pm.items():
        if tm in mset:
            for k, n in cells.items():
                tot[k] += n
    return tot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("events_json", nargs="+",
                    help="D4 events_*.json OR a pass-2 working twopass_*.db")
    args = ap.parse_args()
    for path in args.events_json:
        stem = Path(path).stem
        if path.endswith(".db"):
            # twopass_cam{c}_{variant}.db from v2_run_pass2 (scratch)
            cam = int(stem.split("_")[1].replace("cam", ""))
            variant = stem.split("_", 2)[2]
            for pref in ("v2a_", "v2b_", "v2c_", "v2d_"):
                variant = variant.replace(pref, "")
            import sqlite3 as _sq
            c = _sq.connect(f"file:{path}?mode=ro", uri=True)
            evs = []
            for olid, mv, ts in c.execute(
                    "SELECT origin_leg_id, movement, timestamp_real FROM "
                    "vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0",
                    (cam,)):
                if ts:
                    evs.append({"origin_leg": olid, "movement": mv,
                                "wallclock": ts})
            c.close()
            blob = {"camera": cam, "events": evs}
        else:
            blob = json.loads(Path(path).read_text())
            cam = blob["camera"]
            variant = "_".join(stem.split("_")[2:4])
        lo, hi = WINDOW_HOURS[variant]
        minutes = [dtime(h, m) for h in range(lo, hi) for m in range(60)]

        import sqlite3
        conn = sqlite3.connect("file:data/projects/97a7849a/project.db?mode=ro",
                               uri=True)
        leg_dir = {lid: T._CARD_TO_DIR.get((card or "").strip().upper())
                   for lid, card in conn.execute(
                       "SELECT leg_id, cardinal_direction FROM legs "
                       "WHERE camera_id=?", (cam,))}
        conn.close()

        mio = T.load_miovision(cam)
        mio_minutes = [m for m in minutes if m in mio]
        ours_v2 = per_min_from_events(blob["events"], leg_dir)
        ours_prod = T.load_ours(cam)

        rows_v2 = score_cells(ours_v2, mio, mio_minutes)
        rows_prod = score_cells(ours_prod, mio, mio_minutes)
        c_v2, c_prod = compliance(rows_v2), compliance(rows_prod)

        t_mio = cell_totals(mio, mio_minutes)
        t_v2 = cell_totals(ours_v2, mio_minutes)
        t_prod = cell_totals(ours_prod, mio_minutes)

        print(f"\n=== {stem} (cam{cam} {variant}, "
              f"{len(mio_minutes)} Mio minutes) ===")
        print(f"5/95 cell-bins: V2 {c_v2['pct']}% "
              f"({c_v2['compliant']}/{c_v2['cells_scored']})  |  "
              f"PRODUCTION {c_prod['pct']}% "
              f"({c_prod['compliant']}/{c_prod['cells_scored']})")
        print(f"{'cell':>12} {'Mio':>6} {'V2':>6} {'prod':>6}")
        for k in sorted(set(t_mio) | set(t_v2) | set(t_prod)):
            print(f"{k[0]+' '+k[1]:>12} {t_mio.get(k,0):>6} "
                  f"{t_v2.get(k,0):>6} {t_prod.get(k,0):>6}")
        out = Path("runs/v2_week1") / f"score_{stem}.json"
        out.write_text(json.dumps(
            {"v2": c_v2, "production": c_prod,
             "totals": {f"{k[0]}_{k[1]}": [t_mio.get(k, 0), t_v2.get(k, 0),
                                           t_prod.get(k, 0)]
                        for k in sorted(set(t_mio) | set(t_v2) | set(t_prod))}},
            indent=1))
        print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
