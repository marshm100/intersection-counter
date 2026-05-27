"""Diagnose the throughs-labeled-as-turns phantom (joint scorer).

For the regenerated camera-1 events, runs the joint scorer and, for every event
it labels a TURN, compares the chosen turn-path's partial-match cost/coverage
against the same-origin THROUGH path's cost/coverage. If the through path is
within a hair of the turn path (or the trajectory is just short), the polyline
bank can't disambiguate and the suffix match picks the wrong movement.

Usage: py scripts/diagnose_phantom.py
"""
from __future__ import annotations

import sqlite3
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.trajectory_classifier import (
    _densify_polyline, _resample_to, _subsequence_dtw, compute_path_distance,
    score_path_joint,
)
from replay_attribution_changes import PROJECT_DB, load_events, load_paths


def path_cost_cov(traj, poly, densify_step=12.0, traj_cap=30):
    traj_rs = _resample_to(traj, traj_cap)
    pd = _densify_polyline(poly, densify_step)
    if len(pd) < 2 or len(traj_rs) < 2:
        return float("inf"), 0.0
    start, end, cost = _subsequence_dtw(traj_rs, pd)
    plen = compute_path_distance(pd)
    sub = compute_path_distance(pd[start:end + 1])
    return cost, (sub / plen if plen > 0 else 0.0)


def main() -> int:
    c = sqlite3.connect(str(PROJECT_DB))
    events = load_events(c)
    paths = load_paths(c)
    c.close()
    by_id = {p["path_id"]: p for p in paths}
    through_by_origin = {p["origin_leg_id"]: p for p in paths if p["movement_label"] == "through"}

    tally: dict[str, list] = {}
    turn_examples = []
    for ev in events:
        traj = ev["trajectory"]
        if not traj or len(traj) < 4:
            continue
        r = score_path_joint(traj, paths)
        mv = r.get("movement_label")
        if mv is None:
            mv = "none"
        tally.setdefault(mv, []).append(len(traj))
        if mv in ("right", "left"):
            o = r["origin_leg_id"]
            thr = through_by_origin.get(o)
            tcost, tcov = path_cost_cov(traj, thr["polyline"]) if thr else (float("inf"), 0)
            turn_examples.append({
                "n": len(traj), "mv": mv,
                "chosen": f"L{o}->L{r['destination_leg_id']}",
                "chosen_cost": r["distance"], "chosen_cov": r["coverage"],
                "thru_cost": tcost, "thru_cov": tcov,
                "thru_passes": (tcost <= 35.0 and tcov >= 0.28),
                "gap": tcost - r["distance"],
            })

    print("Assigned-movement distribution (joint, default params):")
    for mv, lens in sorted(tally.items()):
        print(f"  {mv:<8} n={len(lens):<4} median_traj_pts={int(st.median(lens))}")

    print(f"\n{len(turn_examples)} events labeled a TURN. Trajectory length:")
    tl = [e["n"] for e in turn_examples]
    if tl:
        print(f"  median {int(st.median(tl))} pts, min {min(tl)}, max {max(tl)}")
        within5 = sum(1 for e in turn_examples if e["gap"] <= 5)
        thru_ok = sum(1 for e in turn_examples if e["thru_passes"])
        print(f"  through path within 5px cost of chosen turn: {within5}/{len(turn_examples)}")
        print(f"  through path ALSO passes gates (cost<=35, cov>=0.28): {thru_ok}/{len(turn_examples)}")

    print("\nWorst examples (turn chosen but through nearly as good):")
    print(f"{'n_pts':>5} {'chosen':<10} {'mv':<5} {'turnCost':>8} {'turnCov':>7} "
          f"{'thruCost':>8} {'thruCov':>7} {'gap':>6} {'thruOK':>6}")
    for e in sorted(turn_examples, key=lambda x: x["gap"])[:15]:
        print(f"{e['n']:>5} {e['chosen']:<10} {e['mv']:<5} {e['chosen_cost']:>8.1f} "
              f"{e['chosen_cov']:>7.2f} {e['thru_cost']:>8.1f} {e['thru_cov']:>7.2f} "
              f"{e['gap']:>+6.1f} {str(e['thru_passes']):>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
