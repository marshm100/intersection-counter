"""Data-driven leg + path-bank recalibration (Phase 3, direction-based).

Rebuilds the leg reference_headings + path bank from regenerated trajectories.
At this camera detection is late and starts span a continuous horizontal band, so
origins are NOT recoverable from start-point clustering. Instead we separate flows
by DIRECTION OF TRAVEL: the two opposite dominant tail-heading modes define the
arterial axis (the through pair); off-axis tails are turns. Movements come from the
flow geometry; approach identity from count-matching the manual TMC. Only the
reliable signals are used (tails + counts), never the suspect stored headings or
mid-turn entry tangents. See docs/recalibration_plan_2026-05-27.md.

Emits a suggestion JSON (updated_legs + paths). Does NOT write the DB.

Usage:
  py scripts/recalibrate_camera.py --out evaluations/recal_cam1.json
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.auto_calibrate import _fit_mean_polyline
from backend.services.trajectory_classifier import _exit_velocity
from groundtruth import (
    ALL_MVT, BUCKET_SECONDS, bucket_to_footage_seconds, db_processed_window,
    overlap_seconds, parse_manual_csv,
)
from replay_attribution_changes import PROJECT_DB, load_events, load_legs

# Manual study approaches; the two Belt Line ones carry the through arterial.
BELT_APPROACHES = ["NB N Belt Line Rd", "SB N Belt Line Rd"]   # arterial (through pair)
SIDE_APPROACHES = ["EB Northwest Dr", "WB Private Driveway"]    # side streets (turns)
APPROACH_TO_LEG = {"SB N Belt Line Rd": 22, "NB N Belt Line Rd": 23,
                   "WB Private Driveway": 24, "EB Northwest Dr": 25}
THROUGH_TOL_DEG = 45.0
POLYLINE_PTS = 15


def _heading_of(vx, vy):
    return math.degrees(math.atan2(vx, -vy)) % 360


def _tail_heading(traj):
    return _heading_of(*_exit_velocity(traj))


def _ang_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def _circ_mean(degs):
    s = sum(math.sin(math.radians(d)) for d in degs)
    c = sum(math.cos(math.radians(d)) for d in degs)
    return math.degrees(math.atan2(s, c)) % 360 if degs else 0.0


def detect_axis(tails, bin_deg=15):
    """Return (dir_a, dir_b) — the two opposite dominant tail directions."""
    nb = int(360 / bin_deg)
    hist = [0] * nb
    for t in tails:
        hist[int(t // bin_deg) % nb] += 1
    a = max(range(nb), key=lambda i: hist[i])
    dir_a = a * bin_deg + bin_deg / 2
    opp = (dir_a + 180) % 360
    cand = [i for i in range(nb) if _ang_diff(i * bin_deg + bin_deg / 2, opp) <= 30]
    b = max(cand, key=lambda i: hist[i]) if cand else int((a + nb // 2) % nb)
    dir_b = b * bin_deg + bin_deg / 2
    # refine each as circular mean of tails closest to it
    ta = [t for t in tails if _ang_diff(t, dir_a) <= _ang_diff(t, dir_b)]
    tb = [t for t in tails if _ang_diff(t, dir_b) < _ang_diff(t, dir_a)]
    return _circ_mean(ta) if ta else dir_a, _circ_mean(tb) if tb else dir_b


def manual_for_window(window):
    manual = parse_manual_csv()
    out = {a: {m: 0.0 for m in ALL_MVT} for a in APPROACH_TO_LEG}
    p0, p1 = window
    for label, bucket in manual.items():
        b0, b1 = bucket_to_footage_seconds(label)
        ov = overlap_seconds(p0, p1, b0, b1)
        if ov <= 0:
            continue
        sc = ov / BUCKET_SECONDS
        for a in APPROACH_TO_LEG:
            if a in bucket:
                for m in ALL_MVT:
                    out[a][m] += bucket[a][m] * sc
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evaluations/recal_cam1.json")
    ap.add_argument("--min-support", type=int, default=5)
    args = ap.parse_args()

    conn = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(conn)
    events = load_events(conn)
    conn.close()
    trajs = [e["trajectory"] for e in events if e["trajectory"] and len(e["trajectory"]) >= 4]
    window = db_processed_window()
    manual = manual_for_window(window)
    tails = [_tail_heading(t) for t in trajs]
    median_start_x = float(np.median([t[0][0] for t in trajs]))
    print(f"loaded {len(trajs)} trajectories; window {window[0]:.0f}-{window[1]:.0f}s")

    # --- Step 1: arterial axis + flow groups (no start-zone clustering) ---
    dir_a, dir_b = detect_axis(tails)
    print(f"\n=== Step 1: arterial axis ~ {dir_a:.0f} / {dir_b:.0f} deg ===")
    groups: dict[str, list] = {}
    for t in trajs:
        th = _tail_heading(t)
        da, db = _ang_diff(th, dir_a), _ang_diff(th, dir_b)
        if min(da, db) <= THROUGH_TOL_DEG:
            key = "through_a" if da < db else "through_b"   # by travel direction
        else:
            # off-axis turn: rotation sense of tail vs nearest axis direction
            base = dir_a if da < db else dir_b
            cross = math.sin(math.radians(th - base))
            key = "turn_right" if cross > 0 else "turn_left"
        groups.setdefault(key, []).append(t)
    for k, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"  {k:<12} n={len(g):<4} median_tail={_circ_mean([_tail_heading(x) for x in g]):.0f}")
    thru_groups = sorted([k for k in groups if k.startswith("through")],
                         key=lambda k: -len(groups[k]))
    covered = sum(len(groups[k]) for k in thru_groups)
    # Gate 1: through pair dominates
    print(f"  through pair covers {covered}/{len(trajs)} ({covered/len(trajs)*100:.0f}%) "
          f"[gate: >=70%]")

    # --- Step 2: median polyline + stats per group ---
    def stat(g):
        return {"count": len(g), "polyline": _fit_mean_polyline(g, POLYLINE_PTS),
                "tail": _circ_mean([_tail_heading(x) for x in g]),
                "start_x": float(np.median([x[0][0] for x in g])),
                "start_pt": [float(np.median([x[0][0] for x in g])),
                             float(np.median([x[0][1] for x in g]))]}
    gstats = {k: stat(g) for k, g in groups.items() if len(g) >= args.min_support}

    # --- Step 3: assign through pair -> Belt Line legs by count rank vs manual thru ---
    manual_thru_rank = sorted(BELT_APPROACHES, key=lambda a: -manual[a]["thru"])  # NB(56) then SB(37)
    updated_legs, paths = [], []
    assigned = {}
    for i, gk in enumerate(thru_groups[:2]):
        gs = gstats.get(gk)
        if gs is None:
            continue
        appr = manual_thru_rank[i] if i < len(manual_thru_rank) else BELT_APPROACHES[i]
        leg_id = APPROACH_TO_LEG[appr]
        # through exits to the OTHER belt leg
        other = manual_thru_rank[1 - i] if i < 2 else appr
        dest_leg = APPROACH_TO_LEG[other]
        updated_legs.append({"leg_id": leg_id, "approach": appr,
                             "origin_point": [round(gs["start_pt"][0], 1), round(gs["start_pt"][1], 1)],
                             "reference_heading": round(gs["tail"], 1)})
        paths.append({"origin_leg_id": leg_id, "destination_leg_id": dest_leg,
                      "movement_label": "through",
                      "polyline": [[round(x, 1), round(y, 1)] for x, y in gs["polyline"]],
                      "supporting_count": gs["count"], "source": "data-driven"})
        assigned[(appr, "thru")] = gs["count"]
        print(f"\n  through group {gk} (n={gs['count']}, tail={gs['tail']:.0f}) -> "
              f"{appr} (L{leg_id}) through, dest L{dest_leg}, ref={gs['tail']:.0f}")

    # Turn groups -> side-street approaches by count (best-effort on thin data)
    turn_groups = sorted([k for k in gstats if k.startswith("turn")],
                         key=lambda k: -gstats[k]["count"])
    for i, gk in enumerate(turn_groups):
        gs = gstats[gk]
        appr = SIDE_APPROACHES[i] if i < len(SIDE_APPROACHES) else SIDE_APPROACHES[-1]
        mvt = "right" if gk == "turn_right" else "left"
        leg_id = APPROACH_TO_LEG[appr]
        paths.append({"origin_leg_id": leg_id, "destination_leg_id": None,
                      "movement_label": mvt,
                      "polyline": [[round(x, 1), round(y, 1)] for x, y in gs["polyline"]],
                      "supporting_count": gs["count"], "source": "data-driven"})
        assigned[(appr, mvt)] = gs["count"]
        print(f"  turn group {gk} (n={gs['count']}) -> {appr} (L{leg_id}) {mvt} (best-effort)")

    # --- Validation gate: assigned vs manual ---
    print(f"\n=== Gate: assigned vs manual (window) ===")
    print(f"{'approach':<22} {'mvt':<6} {'manual':>7} {'assigned':>9}")
    for appr in APPROACH_TO_LEG:
        for m in ALL_MVT:
            man = manual[appr][m]
            asg = assigned.get((appr, m), 0)
            if man < 0.5 and asg == 0:
                continue
            print(f"{appr:<22} {m:<6} {man:>7.1f} {asg:>9}")

    out = {"project": "97a7849a", "camera_id": 1, "window_sec": list(window),
           "arterial_axis_deg": [round(dir_a, 1), round(dir_b, 1)],
           "updated_legs": updated_legs, "paths": paths}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nwrote suggestion -> {args.out}  ({len(paths)} paths, {len(updated_legs)} legs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
