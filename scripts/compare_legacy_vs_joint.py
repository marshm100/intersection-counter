"""B0_legacy vs B0_joint — the apples-to-apples accuracy comparison (P2.A).

After a reprocess regenerates trajectories, this re-attributes the SAME stored
trajectory_data two ways via in-memory replay (seconds, no retrack) and scores
each against the manual ground truth apportioned to the processed window:

  - legacy : the three-tier origin + polyline/softmax destination path (joint OFF)
  - joint  : score_path_joint (Attribution v2, joint ON), legacy as fallback

It prints both arms' aggregate error + the per-cell deltas, so the joint scorer's
real win (or regression) on regenerated volume is visible in one shot. This is the
clean delta the plan calls for; both arms come from one trajectory set so there is
no cross-universe mixing.

Usage:
  py scripts/compare_legacy_vs_joint.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groundtruth import ALL_MVT, LEG_TO_APPROACH, db_processed_window, parse_manual_csv
from replay_attribution_changes import (
    PROJECT_DB, load_events, load_legs, load_paths, replay_all,
)
from tune_joint_scorer import manual_cells_for_window, metrics


def main() -> int:
    conn = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(conn)
    paths = load_paths(conn)
    events = load_events(conn)
    conn.close()

    window = db_processed_window()
    if window is None:
        print("No events in DB — run the reprocess first.")
        return 1
    manual = manual_cells_for_window(parse_manual_csv(), window)
    total_manual = sum(manual[lid][m] for lid in manual for m in ALL_MVT)

    legacy = replay_all(events, legs, paths, use_joint=False)["cells"]
    joint = replay_all(events, legs, paths, use_joint=True)["cells"]
    lr, la = metrics(legacy, manual)
    jr, ja = metrics(joint, manual)

    print(f"Processed window (footage sec): {window[0]:.0f}-{window[1]:.0f}")
    print(f"Events: {len(events)}   total manual in window: {total_manual:.0f}\n")
    print(f"{'arm':<8} {'agg_err':>9} {'robust':>9}")
    print("-" * 28)
    print(f"{'legacy':<8} {la:>8.2f}% {lr:>8.2f}%")
    print(f"{'joint':<8} {ja:>8.2f}% {jr:>8.2f}%")
    print(f"{'delta':<8} {ja-la:>+8.2f}pp {jr-lr:>+8.2f}pp "
          f"({'JOINT BETTER' if ja < la else 'legacy better'})\n")

    # Per-cell: manual vs each arm, worst movers first.
    print(f"{'Leg':<4} {'Mvt':<6} {'Manual':>7} {'Legacy':>7} {'Joint':>6} "
          f"{'L|d|':>6} {'J|d|':>6}")
    print("-" * 50)
    rows = []
    for lid in LEG_TO_APPROACH:
        for m in ALL_MVT:
            man = manual[lid][m]
            lo = legacy.get((lid, m), 0)
            jo = joint.get((lid, m), 0)
            rows.append((lid, m, man, lo, jo, abs(lo - man), abs(jo - man)))
    rows.sort(key=lambda r: max(r[5], r[6]), reverse=True)
    for lid, m, man, lo, jo, ld, jd in rows:
        if man == 0 and lo == 0 and jo == 0:
            continue
        print(f"L{lid:<3} {m:<6} {man:>7.1f} {lo:>7} {jo:>6} {ld:>6.1f} {jd:>6.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
