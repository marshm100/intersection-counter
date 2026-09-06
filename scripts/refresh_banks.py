"""Bank refresh runner (docs/plan_bank_refresh_2026-09-06.md).

Dry-run (default): prints the full before/after table for all five
cameras — old expectation (scaled to the study window the way
bank_expecteds scales), new count, and the no-row cells left alone.
--apply --db <path> writes the narrow UPDATE to the NAMED DB only
(a scratch snapshot, or production at B4 after operator go), with a
rollback sidecar per camera next to it.

Usage:
  py -X utf8 scripts/refresh_banks.py                 # dry-run table
  py -X utf8 scripts/refresh_banks.py --apply --db data/projects/97a7849a/_replay_scratch/bankref_20260906/refreshed_project.db
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.bank_refresh import refresh_bank  # noqa: E402

PROJECT = "97a7849a"
CAMS = [1, 2, 3, 4, 5]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=None,
                    help="target DB (required with --apply; never defaults "
                         "to production)")
    args = ap.parse_args()
    if args.apply and not args.db:
        print("--apply requires an explicit --db target (standing law: no "
              "production write without an operator-approved ship step)")
        return 2

    for cam in CAMS:
        res = refresh_bank(PROJECT, cam, db_path=args.db, write=args.apply)
        w = res["window_seconds"]
        print(f"\ncam{cam}  study window {w/3600:.1f} h  "
              f"({'WRITTEN' if res['written'] else 'dry-run'})")
        print(f"  {'cell':>9} {'movement':10} {'old':>6} {'old@win':>8} "
              f"{'new':>6} {'ratio':>7}")
        for r in res["rows"]:
            old_at_win = r["old_count"] * (w / (r["old_window_s"] or 1800.0))
            ratio = (r["new_count"] / old_at_win) if old_at_win else float("inf")
            cell = f"{r['origin_leg_id']}->{r['destination_leg_id']}"
            print(f"  {cell:>9} {r['movement']:10} {r['old_count']:>6} "
                  f"{old_at_win:>8.0f} {r['new_count']:>6} {ratio:>6.1f}x")
        for c in res["no_row_cells"]:
            print(f"  {c['origin_leg_id']}->{c['destination_leg_id']:<6} "
                  f"NO BANK ROW  counted={c['counted']}  (left alone)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
