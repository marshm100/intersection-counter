"""Tune the joint partial-Fréchet scorer against the manual ground truth (P2.B).

The committed defaults (max_cost=35, min_coverage_frac=0.28, tail_weight=0.35,
coverage_weight=0.15) were calibrated on only the 144 surviving trajectories.
After the repopulating reprocess regenerates the full set, this script tunes
them on real volume via fast in-memory replay (no retrack/re-detect needed —
attribution-only changes re-measure on stored trajectory_data in seconds).

Objective (robustified so the two ~5k through-cells don't dominate and let
L25-right stay broken):
    robust_agg = sum( min(|Δ_c|, cap * manual_c) ) / total_manual      # tune this
    agg_err    = sum( |Δ_c| ) / total_manual                            # report this

Search: coordinate descent from the current defaults over max_cost,
min_coverage_frac, tail_weight, coverage_weight (~30-50 replays, seconds each).

Anti-overfit: tune on the AM trim, validate on the PM trim (per-trim manual
windows). Falls back to a seeded 50/50 event split when trim_ids aren't set
(e.g. pre-reprocess).

Usage:
  py scripts/tune_joint_scorer.py                 # AM-tune / PM-validate
  py scripts/tune_joint_scorer.py --full          # tune on full set (no holdout)
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groundtruth import (
    ALL_MVT,
    BUCKET_SECONDS,
    LEG_TO_APPROACH,
    bucket_to_footage_seconds,
    overlap_seconds,
    parse_manual_csv,
)
from replay_attribution_changes import (
    PROJECT_DB,
    load_events,
    load_legs,
    load_paths,
    replay_all,
)

# Robust per-cell cap as a fraction of TOTAL manual (uniform across cells).
# Earlier this was 0.15 * that cell's OWN manual count, which had a blind spot:
# a cell with manual=0 (a pure phantom movement like L24-right) contributed 0,
# and a tiny-manual cell (L22-right, manual~1.5) could absorb a huge phantom
# over-attribution (ours=43) for almost nothing (cap 0.22). A uniform cap of
# CAP_FRAC*total_manual still stops the two giant through-cells from dominating
# the search, but now penalises phantoms and tiny-manual over-attribution — the
# exact errors we need the tuner to see.
CAP_FRAC = 0.05


def manual_cells_for_window(manual: dict, window: tuple[float, float]) -> dict:
    """Manual per-(leg, movement) counts apportioned to a footage-second window."""
    p_start, p_end = window
    out = {lid: {m: 0.0 for m in ALL_MVT} for lid in LEG_TO_APPROACH}
    for label, bucket in manual.items():
        b_start, b_end = bucket_to_footage_seconds(label)
        ov = overlap_seconds(p_start, p_end, b_start, b_end)
        if ov <= 0:
            continue
        scale = ov / BUCKET_SECONDS
        for lid, approach in LEG_TO_APPROACH.items():
            for m in ALL_MVT:
                out[lid][m] += bucket[approach][m] * scale
    return out


def metrics(ours_cells: dict, manual: dict) -> tuple[float, float]:
    """(robust_agg, agg_err) given replay cells {(lid, mvt): n} vs manual[lid][m]."""
    total_manual = sum(manual[lid][m] for lid in manual for m in ALL_MVT)
    if total_manual <= 0:
        return float("inf"), float("inf")
    cap = CAP_FRAC * total_manual   # uniform per-cell cap (scale-aware)
    sum_abs = 0.0
    sum_robust = 0.0
    for lid in LEG_TO_APPROACH:
        for m in ALL_MVT:
            man = manual[lid][m]
            ours = ours_cells.get((lid, m), 0)
            d = abs(ours - man)
            sum_abs += d
            sum_robust += min(d, cap)
    return sum_robust / total_manual * 100, sum_abs / total_manual * 100


def evaluate(events, legs, paths, params, manual) -> tuple[float, float]:
    res = replay_all(events, legs, paths, use_joint=True, joint_kwargs=params)
    return metrics(res["cells"], manual)


def coordinate_descent(events, legs, paths, manual, start: dict) -> tuple[dict, float]:
    """Sweep each param in turn, keeping the best; one refinement pass."""
    sweeps = {
        "max_cost": [25, 28, 30, 32, 35, 38, 41, 44],
        "min_coverage_frac": [0.20, 0.24, 0.28, 0.32, 0.35],
        "tail_weight": [0.20, 0.28, 0.35, 0.42],
        "coverage_weight": [0.05, 0.10, 0.15, 0.22],
    }
    best = dict(start)
    best_robust, _ = evaluate(events, legs, paths, best, manual)
    trials = []
    for _ in range(2):  # two passes of coordinate descent
        for key, values in sweeps.items():
            for v in values:
                cand = dict(best, **{key: v})
                if cand["tail_weight"] + cand["coverage_weight"] >= 0.95:
                    continue  # keep some weight on the shape term
                r, a = evaluate(events, legs, paths, cand, manual)
                trials.append((r, a, dict(cand)))
                if r < best_robust:
                    best_robust, best = r, cand
    trials.sort(key=lambda t: t[0])
    return best, best_robust, trials


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="tune on the full set (no AM/PM holdout)")
    ap.add_argument("--rec-start-offset", type=float, default=2.0,
                    help="recording start offset in seconds (video starts at 00:00:02)")
    args = ap.parse_args()

    conn = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(conn)
    paths = load_paths(conn)
    events = load_events(conn)
    # trim windows (footage seconds) for the holdout split.
    trims = conn.execute(
        "SELECT trim_id, start_wallclock, end_wallclock FROM trims ORDER BY sort_order"
    ).fetchall()
    conn.close()
    manual = parse_manual_csv()
    print(f"loaded {len(events)} events, {len(paths)} paths, {len(trims)} trims")

    start = {"max_cost": 35.0, "min_coverage_frac": 0.28,
             "tail_weight": 0.35, "coverage_weight": 0.15}

    def wallclock_to_footage(hms: str) -> float:
        h, m, s = (int(x) for x in hms.split(":"))
        return h * 3600 + m * 60 + s - args.rec_start_offset

    if args.full or len(trims) < 2:
        full_manual = manual_cells_for_window(manual, (0, 1e9))
        best, best_r, trials = coordinate_descent(events, legs, paths, full_manual, start)
        r0, a0 = evaluate(events, legs, paths, start, full_manual)
        rb, ab = evaluate(events, legs, paths, best, full_manual)
        print(f"\nFULL-SET tuning (no holdout):")
        print(f"  start {start} -> robust={r0:.2f}% agg={a0:.2f}%")
        print(f"  best  {best} -> robust={rb:.2f}% agg={ab:.2f}%")
    else:
        am, pm = trims[0], trims[1]
        am_win = (wallclock_to_footage(am[1]), wallclock_to_footage(am[2]))
        pm_win = (wallclock_to_footage(pm[1]), wallclock_to_footage(pm[2]))
        am_manual = manual_cells_for_window(manual, am_win)
        pm_manual = manual_cells_for_window(manual, pm_win)
        am_events = [e for e in events if e.get("trim_id") == am[0]] or \
            [e for e in events if am_win[0] <= (e.get("timestamp_video") or -1) < am_win[1]]
        pm_events = [e for e in events if e.get("trim_id") == pm[0]] or \
            [e for e in events if pm_win[0] <= (e.get("timestamp_video") or -1) < pm_win[1]]
        print(f"  AM train: {len(am_events)} events;  PM holdout: {len(pm_events)} events")
        best, best_r, trials = coordinate_descent(am_events, legs, paths, am_manual, start)
        r0, a0 = evaluate(am_events, legs, paths, start, am_manual)
        rb, ab = evaluate(am_events, legs, paths, best, am_manual)
        hr, ha = evaluate(pm_events, legs, paths, best, pm_manual)
        print(f"\nAM-tuned start {start} -> robust={r0:.2f}% agg={a0:.2f}%")
        print(f"AM-tuned best  {best} -> robust={rb:.2f}% agg={ab:.2f}%")
        print(f"PM HOLDOUT with best -> robust={hr:.2f}% agg={ha:.2f}%  "
              f"(trust this number, not the train one)")

    print("\nTop 5 configurations (by robust metric on train):")
    seen = set()
    shown = 0
    for r, a, cfg in trials:
        key = tuple(sorted(cfg.items()))
        if key in seen:
            continue
        seen.add(key)
        print(f"  robust={r:6.2f}%  agg={a:6.2f}%  {cfg}")
        shown += 1
        if shown >= 5:
            break
    print("\nIf the winner improves the holdout, update the JOINT_SCORER_* constants "
          "in backend/config.py and re-snapshot B0_joint.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
