"""Morning summary for the polyline-pipeline overnight test.

Run this after the overnight Balanced run completes. It:
  1. Reports pipeline counters (n_origin_via_polyline, etc.) from the
     current run state.
  2. Runs scripts/groundtruth.py --diff baseline to compare recall to
     the pre-polyline baseline.
  3. Per-leg breakdown of L18/L19/L20/L21 attribution + delta vs the
     last failed run (the broken backward-extrap one stored as
     pre-existing data).

Usage:
  py scripts/overnight_summary.py
"""
from __future__ import annotations

import json
import subprocess
import sqlite3
import sys
from pathlib import Path


PROJECT_DB = Path("data/projects/97a7849a/project.db")
INTERSECTION_ID = 1
CAMERA_ID = 1


def section(title: str) -> None:
    print()
    print("=" * 76)
    print(title)
    print("=" * 76)


def main() -> int:
    if not PROJECT_DB.exists():
        print(f"DB not found: {PROJECT_DB}", file=sys.stderr)
        return 1

    section("Run state")
    conn = sqlite3.connect(str(PROJECT_DB))
    state = conn.execute(
        "SELECT status, error_message, updated_at FROM v3_run_state WHERE intersection_id=?",
        (INTERSECTION_ID,),
    ).fetchone()
    print(f"intersection {INTERSECTION_ID}: state={state}")

    n_events = conn.execute(
        "SELECT COUNT(*) FROM vehicle_events WHERE rejected=0"
    ).fetchone()[0]
    mn, mx = conn.execute(
        "SELECT MIN(timestamp_video), MAX(timestamp_video) FROM vehicle_events WHERE rejected=0"
    ).fetchone()
    print(f"events: {n_events}")
    if mn is not None:
        print(f"footage window: {mn:.0f} - {mx:.0f} sec ({(mx-mn)/60:.1f} min)")

    section("Per-leg event count + manual-ground-truth reference")
    by_leg = dict(conn.execute(
        "SELECT origin_leg_id, COUNT(*) FROM vehicle_events "
        "WHERE rejected=0 GROUP BY origin_leg_id"
    ).fetchall())
    # Manual ground truth from earlier baselines (per docs/handoffs/2026-05-20.md):
    # AM peak (7:00-9:00) approx counts: L18=5257, L19=5726, L20=17, L21=1015.
    # Full AM+PM if both trims processed: roughly 2x those values.
    print(f"  L18: {by_leg.get(18, 0)} (manual reference: ~5257 AM-only)")
    print(f"  L19: {by_leg.get(19, 0)} (manual reference: ~5726 AM-only)")
    print(f"  L20: {by_leg.get(20, 0)} (manual reference: ~17    AM-only -- driveway)")
    print(f"  L21: {by_leg.get(21, 0)} (manual reference: ~1015  AM-only)")

    section("Paths in use (polyline calibration)")
    paths = conn.execute(
        "SELECT origin_leg_id, destination_leg_id, movement_label, "
        "supporting_count, source FROM intersection_paths WHERE camera_id=? "
        "ORDER BY origin_leg_id, destination_leg_id",
        (CAMERA_ID,),
    ).fetchall()
    print(f"{len(paths)} paths calibrated for camera {CAMERA_ID}")
    for r in paths:
        print(f"  L{r[0]} -> L{r[1]}: {r[2]:>7}  n={r[3]:>4}  source={r[4]}")

    conn.close()

    section("Ground-truth diff vs baseline.json")
    # Note: baseline.json was captured pre-polyline, so this diff shows
    # the cumulative recall change since the polyline architecture
    # landed. Negative deltas are bad.
    try:
        result = subprocess.run(
            ["py", "scripts/groundtruth.py", "--diff", "baseline"],
            capture_output=True, text=True, timeout=120,
        )
        print(result.stdout[-3000:])  # tail the output
        if result.returncode != 0:
            print(f"(non-zero exit {result.returncode})", file=sys.stderr)
            print(result.stderr[-1000:], file=sys.stderr)
    except Exception as e:
        print(f"groundtruth.py invocation failed: {e}", file=sys.stderr)

    section("Bug B residual check (replay_movement on stored events)")
    try:
        result = subprocess.run(
            ["py", "scripts/replay_movement.py"],
            capture_output=True, text=True, timeout=120,
        )
        print(result.stdout[-3000:])
        if result.returncode != 0:
            print(f"(non-zero exit {result.returncode})", file=sys.stderr)
    except Exception as e:
        print(f"replay_movement.py invocation failed: {e}", file=sys.stderr)

    print()
    print("Done. Headline metrics to focus on:")
    print("  - L19 event count: pre-fix was 24% recall (128 in 23 min).")
    print("    Polyline target: >70% (4000+ in 2 hr AM + similar PM).")
    print("  - L20 event count: pre-fix was 12,765% (2171 vs manual 17).")
    print("    Polyline target: <100 (driveway is genuinely low-traffic).")
    print("  - L18 phantom-lefts: pre-fix was 67. Polyline target: <5.")
    print("  - L21 fake-throughs: pre-fix was 41. Polyline target: 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
