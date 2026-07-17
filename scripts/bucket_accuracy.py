"""Per-(leg, movement) accuracy for ONE 15-min bucket (Stage C single-bucket validation).

Targets the case where reprocessing the full 11h is too slow, so we
reprocess just one 15-min trim window and check whether the algorithmic
changes (heading gate, dest radius 20px, L24 heading-exclude) produced
the same Stage A replay-predicted improvement in real vehicle_events.

Usage:
  py scripts/bucket_accuracy.py "7:00 AM"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groundtruth import (
    ALL_MVT, LEG_TO_APPROACH, BUCKET_SECONDS,
    bucket_to_footage_seconds, fetch_our_counts, parse_manual_csv,
)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: py scripts/bucket_accuracy.py <bucket_label>", file=sys.stderr)
        print("  e.g.: py scripts/bucket_accuracy.py '7:00 AM'", file=sys.stderr)
        return 2
    label = sys.argv[1].strip()

    manual = parse_manual_csv()
    if label not in manual:
        print(f"unknown bucket: {label!r}; valid: {sorted(manual)}", file=sys.stderr)
        return 1
    b_start, b_end = bucket_to_footage_seconds(label)
    ours = fetch_our_counts(b_start, b_end)

    cells = []
    for lid, approach in LEG_TO_APPROACH.items():
        for mvt in ALL_MVT:
            m = manual[label][approach][mvt]
            o = ours[lid][mvt]
            cells.append({
                "leg_id": lid, "approach": approach, "movement": mvt,
                "manual": m, "ours": o,
                "delta": o - m, "abs_delta": abs(o - m),
            })
    cells.sort(key=lambda c: -c["abs_delta"])

    print(f"\n=== Per-(leg, movement) for bucket {label!r} ===\n")
    print(f"{'Leg':<3} {'Approach':<24} {'Mvt':<6} "
          f"{'Manual':>6} {'Ours':>5} {'Delta':>7} {'|D|':>5}")
    print("-" * 60)
    for c in cells:
        print(f"L{c['leg_id']:<2} {c['approach']:<24} {c['movement']:<6} "
              f"{c['manual']:>6} {c['ours']:>5} {c['delta']:>+7} {c['abs_delta']:>5}")

    total_manual = sum(c["manual"] for c in cells)
    total_ours = sum(c["ours"] for c in cells)
    sum_abs = sum(c["abs_delta"] for c in cells)
    pct = sum_abs / total_manual * 100 if total_manual > 0 else None
    print("-" * 60)
    print(f"\nTotals: manual={total_manual}  ours={total_ours}  "
          f"sum|delta|={sum_abs}")
    print(f"\nAGGREGATE METRIC = sum|delta| / total_manual = "
          f"{pct:.2f}%" if pct is not None else "  n/a")
    return 0


if __name__ == "__main__":
    sys.exit(main())
