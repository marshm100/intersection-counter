"""Per-(origin_leg, movement) accuracy metric for Sunnyvale (Stage A1).

Builds on groundtruth.py's CSV parsing + DB query to produce a finer-grained
diagnostic than per-leg recall:

  - Per-(leg, movement) cell: manual, ours, signed delta, abs delta, pct err
  - Aggregate metric: AGG = sum |delta_cell| / total_manual_events
  - Cells sorted by abs delta (worst first) so the next fix is obvious

This is the metric the Sunnyvale accuracy plan targets. groundtruth.py's
per-leg recall hides offsetting errors and is unsuitable as a fix target.

Usage:
  py scripts/per_movement_accuracy.py                  # full sweep
  py scripts/per_movement_accuracy.py --save A1_baseline
  py scripts/per_movement_accuracy.py --diff A1_baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from groundtruth import (
    ALL_MVT,
    LEG_TO_APPROACH,
    BUCKET_SECONDS,
    EVAL_DIR,
    bucket_to_footage_seconds,
    db_processed_window,
    fetch_our_counts,
    overlap_seconds,
    parse_manual_csv,
)


def aggregate_full_sweep(manual: dict, processed: tuple[float, float]) -> dict:
    """Mirror run_full_sweep accumulation but skip groundtruth.py's print path.

    Returns aggregated per-(leg, movement) counts across all overlapping
    buckets, apportioned by overlap.
    """
    p_start, p_end = processed
    agg_manual = {lid: {m: 0.0 for m in ALL_MVT} for lid in LEG_TO_APPROACH}
    agg_ours = {lid: {m: 0 for m in ALL_MVT} for lid in LEG_TO_APPROACH}
    n_buckets = 0

    for label, bucket in manual.items():
        b_start, b_end = bucket_to_footage_seconds(label)
        ov = overlap_seconds(p_start, p_end + 1, b_start, b_end)
        if ov <= 0:
            continue
        scale = ov / BUCKET_SECONDS
        ours = fetch_our_counts(max(b_start, p_start), min(b_end, p_end + 1))
        for lid, approach in LEG_TO_APPROACH.items():
            for mvt in ALL_MVT:
                agg_manual[lid][mvt] += bucket[approach][mvt] * scale
                agg_ours[lid][mvt] += ours[lid][mvt]
        n_buckets += 1

    return {"manual": agg_manual, "ours": agg_ours, "n_buckets": n_buckets}


def build_cells(agg: dict) -> list[dict]:
    """Flatten to a list of cell dicts, sorted by abs_delta descending."""
    cells = []
    for lid, approach in LEG_TO_APPROACH.items():
        for mvt in ALL_MVT:
            m = agg["manual"][lid][mvt]
            o = agg["ours"][lid][mvt]
            delta = o - m
            cells.append({
                "leg_id":    lid,
                "approach":  approach,
                "movement":  mvt,
                "manual":    round(m, 1),
                "ours":      o,
                "delta":     round(delta, 1),
                "abs_delta": round(abs(delta), 1),
                "pct_err":   (abs(delta) / m * 100) if m > 0 else (None if o == 0 else float("inf")),
            })
    cells.sort(key=lambda c: c["abs_delta"], reverse=True)
    return cells


def compute_metric(cells: list[dict]) -> dict:
    total_manual = sum(c["manual"] for c in cells)
    total_ours   = sum(c["ours"]   for c in cells)
    sum_abs      = sum(c["abs_delta"] for c in cells)
    agg_pct      = (sum_abs / total_manual * 100) if total_manual > 0 else None
    return {
        "total_manual":  round(total_manual, 1),
        "total_ours":    total_ours,
        "sum_abs_delta": round(sum_abs, 1),
        "agg_err_pct":   (round(agg_pct, 2) if agg_pct is not None else None),
    }


def print_report(cells: list[dict], metric: dict, n_buckets: int) -> None:
    print(f"\n=== Per-(leg, movement) accuracy — {n_buckets} buckets ===\n")
    print(f"{'Leg':<3} {'Approach':<24} {'Mvt':<6} "
          f"{'Manual':>8} {'Ours':>6} {'Delta':>8} {'|D|':>6} {'%Err':>7}")
    print("-" * 75)
    for c in cells:
        pct = c["pct_err"]
        if pct is None:
            pct_s = "    --"
        elif pct == float("inf"):
            pct_s = "   inf"
        else:
            pct_s = f"{pct:6.1f}%"
        print(f"L{c['leg_id']:<2} {c['approach']:<24} {c['movement']:<6} "
              f"{c['manual']:>8.1f} {c['ours']:>6} {c['delta']:>+8.1f} "
              f"{c['abs_delta']:>6.1f} {pct_s}")

    print("-" * 75)
    print(f"\nTotals:  manual={metric['total_manual']:>8.1f}  "
          f"ours={metric['total_ours']:>6}  "
          f"sum|delta|={metric['sum_abs_delta']:>7.1f}")
    print(f"\nAGGREGATE METRIC = sum|delta_cell| / total_manual = "
          f"{metric['agg_err_pct']:.2f}%  "
          f"(target: <5%)\n")


def save_snapshot(name: str, payload: dict) -> Path:
    EVAL_DIR.mkdir(exist_ok=True)
    path = EVAL_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2))
    print(f"saved snapshot -> {path}")
    return path


def load_snapshot(name: str) -> dict | None:
    path = EVAL_DIR / f"{name}.json"
    if not path.exists():
        print(f"no snapshot at {path}", file=sys.stderr)
        return None
    return json.loads(path.read_text())


def diff_snapshots(prev: dict, curr: dict) -> None:
    print("\n=== Diff vs saved snapshot ===\n")
    prev_metric = prev.get("metric", {})
    curr_metric = curr.get("metric", {})
    pa, ca = prev_metric.get("agg_err_pct"), curr_metric.get("agg_err_pct")
    if pa is not None and ca is not None:
        marker = "improved" if ca < pa else ("worse" if ca > pa else "same")
        print(f"  AGGREGATE: {pa:.2f}%  ->  {ca:.2f}%  "
              f"({ca-pa:+.2f}pp)  [{marker}]\n")

    prev_cells = {(c["leg_id"], c["movement"]): c for c in prev.get("cells", [])}
    curr_cells = {(c["leg_id"], c["movement"]): c for c in curr.get("cells", [])}
    print(f"{'Leg':<3} {'Mvt':<6} {'Prev|D|':>8} {'Curr|D|':>8} {'Change':>8}")
    print("-" * 40)
    keys = sorted(set(prev_cells) | set(curr_cells))
    for key in keys:
        p = prev_cells.get(key, {}).get("abs_delta", 0)
        c = curr_cells.get(key, {}).get("abs_delta", 0)
        change = c - p
        if abs(change) < 0.5:
            continue
        print(f"L{key[0]:<2} {key[1]:<6} {p:>8.1f} {c:>8.1f} {change:>+8.1f}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--save", help="save snapshot as evaluations/<name>.json")
    p.add_argument("--diff", help="diff against saved snapshot")
    args = p.parse_args()

    manual = parse_manual_csv()
    processed = db_processed_window()
    if processed is None:
        print("no events in DB; nothing to compare", file=sys.stderr)
        return 1

    agg = aggregate_full_sweep(manual, processed)
    cells = build_cells(agg)
    metric = compute_metric(cells)
    print_report(cells, metric, agg["n_buckets"])

    payload = {"metric": metric, "cells": cells, "n_buckets": agg["n_buckets"]}

    if args.save:
        save_snapshot(args.save, payload)
    if args.diff:
        prev = load_snapshot(args.diff)
        if prev:
            diff_snapshots(prev, payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
