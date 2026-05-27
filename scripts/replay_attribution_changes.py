"""Replay attribution changes on existing trajectories (Stage A diagnostic).

Re-runs origin + destination attribution on all 9,785 persisted vehicle_events
trajectories under three bundled changes:

  (1) Origin Tier-0: heading-consistency gate. A polyline match is only
      accepted if the polyline's averaged first-3-segments bearing is within
      25 deg of the track prefix's averaged first-3-segments bearing.
      Eliminates cross-leg coincidental matches (e.g., L23 trajectories
      matching an L22-origin polyline because spatial distance happened to
      score low).

  (2) Destination Tier-0: tightened max_avg_distance from 40 to 20 px.
      Reduces destination-polyline over-permissiveness identified in B3
      (1012 events bucketed as L22->L24 when only ~18 were real).

  (3) Origin Tier-2: heading fallback excludes L24 (the private driveway).
      A2 found 596 phantom L24 events came via Tier-2 heading. The driveway
      is low-volume; excluding it from heading fallback prevents the broad
      direction-match basin from absorbing throughs.

For each event we re-derive (new_origin_leg, new_destination_leg) and
compute the new movement via derive_movement (rank-based on leg geometry,
the correct labeler at this skewed camera per Grok's Round 5 analysis).

Output: new per-(origin_leg, movement) counts, new aggregate metric, and a
delta-vs-A1-baseline table. Does NOT modify the DB or production code.

Usage:
  py scripts/replay_attribution_changes.py
  py scripts/replay_attribution_changes.py --save A_combined
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import TRAJECTORY_MIN_DISTANCE_PX, TRIPWIRE_HALF_LENGTH_PX
from backend.services.origin_detector import (
    average_perpendicular_distance,
    crossing_direction,
    did_cross_line,
    tripwire_from_point,
)
from backend.services.trajectory_classifier import (
    derive_movement,
    score_destination_by_polyline,
    score_destination_leg,
    score_path_joint,
)

PROJECT_DB = Path("data/projects/97a7849a/project.db")
EVAL_DIR = Path("evaluations")

# Mirror the metric script
LEG_TO_APPROACH = {
    22: "SB N Belt Line Rd",
    23: "NB N Belt Line Rd",
    24: "WB Private Driveway",
    25: "EB Northwest Dr",
}

# Pipeline constants
ORIGIN_ASSIGN_MIN_FRAMES = 2
POLYLINE_MIN_TRAJ_PTS = 4
POLYLINE_PREFIX_PTS = 8

# Tunables for the three changes
ORIGIN_POLY_MATCH_RADIUS_PX = 30.0  # unchanged (the issue isn't origin radius)
ORIGIN_HEADING_GATE_DEG = 25.0       # change (1): new gate
DEST_POLY_MATCH_RADIUS_PX = 20.0     # change (2): was 40
HEADING_FALLBACK_EXCLUDE_LEG_IDS = {24}  # change (3): no L24 via heading


def _segment_heading_deg(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return math.degrees(math.atan2(dx, -dy)) % 360


def _avg_bearing_over_segments(poly: list, n_segments: int = 3) -> float | None:
    """Circular-mean bearing across the first n_segments of poly."""
    if not poly or len(poly) < 2:
        return None
    k = min(n_segments, len(poly) - 1)
    sins, coss = 0.0, 0.0
    for i in range(k):
        h = _segment_heading_deg(poly[i], poly[i + 1])
        r = math.radians(h)
        sins += math.sin(r); coss += math.cos(r)
    if abs(sins) < 1e-9 and abs(coss) < 1e-9:
        return None
    return math.degrees(math.atan2(sins, coss)) % 360


def _angle_diff(a: float, b: float) -> float:
    """Smallest angular distance between two bearings in degrees."""
    return abs((a - b + 180) % 360 - 180)


def _entry_segment(polyline: list) -> list:
    """Mirror origin_detector._entry_segment exactly."""
    if not polyline:
        return []
    n = len(polyline)
    if n <= 2:
        return list(polyline)
    mid = (n + 1) // 2 + 1
    return list(polyline[:mid])


def score_origin_with_heading_gate(
    trajectory_prefix: list,
    paths: list,
    *,
    max_avg_distance_px: float = ORIGIN_POLY_MATCH_RADIUS_PX,
    max_bearing_diff_deg: float | None = None,  # reads from module-global at call time
) -> dict:
    if max_bearing_diff_deg is None:
        max_bearing_diff_deg = ORIGIN_HEADING_GATE_DEG
    """Same as score_origin_by_polyline, but reject candidates whose
    polyline's averaged first-3-segments bearing deviates from the track
    prefix's averaged first-3-segments bearing by more than max_bearing_diff_deg."""
    if not trajectory_prefix or not paths:
        return {"origin_leg_id": None, "distance": float("inf"),
                "path_id": None, "considered": 0, "rejected_by_heading": 0}

    track_bearing = _avg_bearing_over_segments(trajectory_prefix, n_segments=3)

    best_dist = float("inf")
    best_leg = None
    best_path_id = None
    best_support = -1
    rejected = 0
    for p in paths:
        entry = _entry_segment(p.get("polyline") or [])
        if len(entry) < 2:
            continue
        # Heading gate
        if track_bearing is not None and max_bearing_diff_deg is not None:
            poly_bearing = _avg_bearing_over_segments(entry, n_segments=3)
            if poly_bearing is not None:
                if _angle_diff(track_bearing, poly_bearing) > max_bearing_diff_deg:
                    rejected += 1
                    continue
        d = average_perpendicular_distance(trajectory_prefix, entry)
        if (d < best_dist or
                (d == best_dist and p.get("supporting_count", 0) > best_support)):
            best_dist = d
            best_leg = p.get("origin_leg_id")
            best_path_id = p.get("path_id")
            best_support = p.get("supporting_count", 0)

    if best_leg is None or best_dist > max_avg_distance_px:
        return {"origin_leg_id": None, "distance": best_dist,
                "path_id": best_path_id, "considered": len(paths),
                "rejected_by_heading": rejected}
    return {"origin_leg_id": best_leg, "distance": best_dist,
            "path_id": best_path_id, "considered": len(paths),
            "rejected_by_heading": rejected}


def replay_origin(traj: list, legs: list, paths: list) -> tuple[int | None, str]:
    """Three-tier origin attribution mirroring pipeline.py:_assign_origin
    PLUS heading gate on Tier 0 AND L24 exclusion on Tier 2."""
    if len(traj) < ORIGIN_ASSIGN_MIN_FRAMES:
        return None, "none"

    # Tier 0
    if paths and len(traj) >= POLYLINE_MIN_TRAJ_PTS:
        prefix = traj[:min(POLYLINE_PREFIX_PTS, len(traj))]
        match = score_origin_with_heading_gate(prefix, paths)
        if match.get("origin_leg_id") is not None:
            return match["origin_leg_id"], "polyline"

    # Tier 1: tripwire
    for leg in legs:
        zone = leg.get("origin_zone")
        if not zone:
            continue
        if len(zone) == 1:
            ref = leg.get("reference_heading")
            if ref is None:
                continue
            line_start, line_end = tripwire_from_point(
                zone[0], ref, half_length=TRIPWIRE_HALF_LENGTH_PX,
            )
        elif len(zone) >= 2:
            line_start = tuple(zone[0]); line_end = tuple(zone[1])
        else:
            continue
        for i in range(1, len(traj)):
            if did_cross_line(traj[i-1], traj[i], line_start, line_end):
                direction = crossing_direction(
                    traj[i-1], traj[i], line_start, line_end,
                    reference_heading=leg.get("reference_heading"),
                )
                if direction == "enter":
                    return leg["leg_id"], "tripwire"

    # Tier 2: heading fallback, with L24 excluded
    start = traj[0]; end = traj[-1]
    dx = end[0]-start[0]; dy = end[1]-start[1]
    if math.hypot(dx, dy) < TRAJECTORY_MIN_DISTANCE_PX:
        return None, "none"
    movement_heading = math.degrees(math.atan2(dx, -dy)) % 360
    best_lid, best_diff = None, float("inf")
    for leg in legs:
        if leg["leg_id"] in HEADING_FALLBACK_EXCLUDE_LEG_IDS:
            continue
        ref = leg.get("reference_heading")
        if ref is None:
            continue
        diff = abs((movement_heading - ref + 180) % 360 - 180)
        if diff < best_diff:
            best_diff, best_lid = diff, leg["leg_id"]
    if best_lid is not None and best_diff <= 90:
        return best_lid, "heading"
    return None, "none"


def replay_destination(
    traj: list, origin_leg_id: int, legs: list, paths: list,
) -> tuple[int | None, str]:
    """Polyline-first destination attribution with tightened radius;
    fallback to softmax leg scorer if no polyline matches."""
    if origin_leg_id is None:
        return None, "none"
    # Tier 0 dest (tightened)
    pd = score_destination_by_polyline(
        traj, origin_leg_id, paths,
        max_avg_distance_px=DEST_POLY_MATCH_RADIUS_PX,
    )
    if pd.get("destination_leg_id") is not None:
        return pd["destination_leg_id"], "polyline"
    # Tier 1 fallback
    dr = score_destination_leg(traj, origin_leg_id, legs)
    if dr.get("destination_leg_id") is not None:
        return dr["destination_leg_id"], "softmax"
    return None, "none"


def load_legs(conn: sqlite3.Connection, camera_id: int = 1) -> list[dict]:
    rows = conn.execute(
        "SELECT leg_id, label, cardinal_direction, reference_heading, origin_zone "
        "FROM legs WHERE camera_id=? ORDER BY leg_id", (camera_id,),
    ).fetchall()
    return [
        {
            "leg_id": r[0], "label": r[1], "cardinal_direction": r[2],
            "reference_heading": r[3],
            "origin_zone": json.loads(r[4]) if isinstance(r[4], str) else r[4],
        }
        for r in rows
    ]


def load_paths(conn: sqlite3.Connection, camera_id: int = 1) -> list[dict]:
    rows = conn.execute(
        "SELECT path_id, origin_leg_id, destination_leg_id, polyline, "
        "movement_label, supporting_count, source "
        "FROM intersection_paths WHERE camera_id=? ORDER BY path_id", (camera_id,),
    ).fetchall()
    return [
        {
            "path_id": r[0], "origin_leg_id": r[1], "destination_leg_id": r[2],
            "polyline": json.loads(r[3]) if isinstance(r[3], str) else r[3],
            "movement_label": r[4],
            "supporting_count": r[5] or 0,
            "source": r[6],
        }
        for r in rows
    ]


def load_events(conn: sqlite3.Connection, camera_id: int = 1) -> list[dict]:
    rows = conn.execute(
        "SELECT event_id, origin_leg_id, destination_leg_id, movement, "
        "trajectory_data, timestamp_video "
        "FROM vehicle_events WHERE camera_id=? AND rejected=0 "
        "ORDER BY event_id", (camera_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "event_id": r[0],
            "stored_origin_leg_id": r[1],
            "stored_destination_leg_id": r[2],
            "stored_movement": r[3],
            "trajectory": json.loads(r[4]) if isinstance(r[4], str) else r[4],
            "timestamp_video": r[5],
        })
    return out


def replay_all(events: list, legs: list, paths: list, *, use_joint: bool = False) -> dict:
    """Re-attribute every event. Return per-(origin_leg, movement) counts
    plus a tier breakdown and dropped-event count.

    When use_joint is True, the joint partial-Fréchet scorer (score_path_joint)
    attributes origin+destination+movement in one shot off the winning path
    (Attribution v2). Events the joint scorer can't confidently match fall
    through to the legacy three-tier origin + Tier-0/softmax destination chain,
    exactly as pipeline._finalize_vehicle_data does."""
    leg_dict = {l["leg_id"]: l for l in legs}
    NORM = {"through": "thru", "left": "left", "right": "right", "u_turn": "uturn"}
    cells: dict[tuple[int, str], int] = {}
    tiers = {"origin": {"joint": 0, "polyline": 0, "tripwire": 0, "heading": 0, "none": 0},
             "destination": {"joint": 0, "polyline": 0, "softmax": 0, "none": 0}}
    n_dropped_origin = 0
    n_dropped_dest = 0
    n_per_event = []

    for ev in events:
        traj = ev["trajectory"]
        if not traj:
            continue

        # Attribution v2: joint scorer first (reads origin+dest+movement off
        # the matched path). On a confident hit, skip the legacy chain entirely.
        if use_joint and paths:
            j = score_path_joint(traj, paths)
            if j.get("destination_leg_id") is not None:
                new_o = j["origin_leg_id"]
                new_d = j["destination_leg_id"]
                mvt_norm = NORM.get(j["movement_label"], j["movement_label"])
                tiers["origin"]["joint"] += 1
                tiers["destination"]["joint"] += 1
                key = (new_o, mvt_norm)
                cells[key] = cells.get(key, 0) + 1
                n_per_event.append({
                    "event_id": ev["event_id"], "new_origin": new_o,
                    "new_destination": new_d, "new_movement": mvt_norm,
                    "timestamp_video": ev["timestamp_video"], "tier": "joint",
                })
                continue

        new_o, o_tier = replay_origin(traj, legs, paths)
        tiers["origin"][o_tier] = tiers["origin"].get(o_tier, 0) + 1
        if new_o is None:
            n_dropped_origin += 1
            continue
        new_d, d_tier = replay_destination(traj, new_o, legs, paths)
        tiers["destination"][d_tier] = tiers["destination"].get(d_tier, 0) + 1
        if new_d is None:
            n_dropped_dest += 1
            continue
        origin_leg = leg_dict.get(new_o)
        dest_leg = leg_dict.get(new_d)
        if origin_leg is None or dest_leg is None:
            continue
        new_mvt = derive_movement(origin_leg, dest_leg, legs)
        mvt_norm = NORM.get(new_mvt, new_mvt)
        key = (new_o, mvt_norm)
        cells[key] = cells.get(key, 0) + 1
        n_per_event.append({
            "event_id": ev["event_id"],
            "new_origin": new_o, "new_destination": new_d,
            "new_movement": mvt_norm, "timestamp_video": ev["timestamp_video"],
        })

    return {"cells": cells, "tiers": tiers,
            "dropped_origin": n_dropped_origin,
            "dropped_dest": n_dropped_dest,
            "n_events": len(events),
            "per_event": n_per_event}


def main() -> int:
    global ORIGIN_HEADING_GATE_DEG, DEST_POLY_MATCH_RADIUS_PX, HEADING_FALLBACK_EXCLUDE_LEG_IDS
    p = argparse.ArgumentParser()
    p.add_argument("--save", help="save snapshot evaluations/<name>.json")
    p.add_argument("--no-heading-gate", action="store_true",
                   help="disable Tier-0 heading-consistency gate")
    p.add_argument("--dest-radius", type=float, default=None,
                   help="override destination match radius (px)")
    p.add_argument("--no-l24-exclude", action="store_true",
                   help="don't exclude L24 from heading fallback")
    p.add_argument("--joint", action="store_true",
                   help="Attribution v2: route through the joint partial-Frechet "
                        "scorer (score_path_joint), legacy tiers as fallback")
    args = p.parse_args()

    # Apply ablation overrides
    if args.no_heading_gate:
        ORIGIN_HEADING_GATE_DEG = None
    if args.dest_radius is not None:
        DEST_POLY_MATCH_RADIUS_PX = args.dest_radius
    if args.no_l24_exclude:
        HEADING_FALLBACK_EXCLUDE_LEG_IDS = set()

    conn = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(conn)
    paths = load_paths(conn)
    events = load_events(conn)
    conn.close()
    print(f"loaded {len(events)} events, {len(legs)} legs, {len(paths)} paths")
    if args.joint:
        print("MODE: joint partial-Frechet scorer (Attribution v2), legacy tiers as fallback")
    print(f"changes bundled:")
    print(f"  (1) origin Tier-0 heading gate: max bearing diff {ORIGIN_HEADING_GATE_DEG} deg")
    print(f"  (2) destination Tier-0 max_avg_distance: {DEST_POLY_MATCH_RADIUS_PX} px (was 40)")
    print(f"  (3) origin Tier-2 heading fallback excludes leg(s): {sorted(HEADING_FALLBACK_EXCLUDE_LEG_IDS)}")

    result = replay_all(events, legs, paths, use_joint=args.joint)

    print(f"\n=== Replay tiers (origin) ===")
    total = result["n_events"]
    for k, n in result["tiers"]["origin"].items():
        print(f"  {k:<9} {n:>6}  ({n/total*100:5.1f}%)")
    print(f"\n=== Replay tiers (destination) ===")
    for k, n in result["tiers"]["destination"].items():
        print(f"  {k:<9} {n:>6}  ({n/total*100:5.1f}%)")
    print(f"\nDropped at origin (no tier matched): {result['dropped_origin']}")
    print(f"Dropped at destination (no tier matched): {result['dropped_dest']}")

    print(f"\n=== New per-(origin_leg, movement) counts ===")
    print(f"{'Leg':<3} {'Mvt':<6} {'Count':>6}")
    print("-" * 22)
    for (lid, mvt), n in sorted(result["cells"].items(), key=lambda kv: -kv[1]):
        if lid is None: continue
        print(f"L{lid:<2} {mvt:<6} {n:>6}")

    # Compare to A1 baseline if available
    a1_path = EVAL_DIR / "A1_baseline.json"
    if a1_path.exists():
        a1 = json.loads(a1_path.read_text())
        print(f"\n=== Comparison vs A1 baseline (manual is fixed) ===")
        a1_cells = {(c["leg_id"], c["movement"]): c for c in a1["cells"]}
        # Build new cells with the same keys.
        new_cells = {(k[0], k[1]): n for k, n in result["cells"].items()}
        print(f"{'Leg':<3} {'Mvt':<6} {'Manual':>8} "
              f"{'A1.Ours':>8} {'New.Ours':>9} "
              f"{'A1.|D|':>7} {'New.|D|':>8} {'D_change':>9}")
        print("-" * 70)
        all_keys = sorted(set(a1_cells) | set(new_cells))
        new_abs_total = 0.0
        a1_abs_total = a1["metric"]["sum_abs_delta"]
        manual_total = a1["metric"]["total_manual"]
        ours_total_new = 0
        for k in all_keys:
            a1c = a1_cells.get(k, {"manual": 0.0, "ours": 0, "abs_delta": 0.0})
            new_ours = new_cells.get(k, 0)
            manual = a1c["manual"]
            new_abs = abs(new_ours - manual)
            new_abs_total += new_abs
            ours_total_new += new_ours
            change = new_abs - a1c.get("abs_delta", 0)
            arrow = "DOWN" if change < -0.5 else ("UP" if change > 0.5 else "    ")
            print(f"L{k[0]:<2} {k[1]:<6} {manual:>8.1f} "
                  f"{a1c['ours']:>8} {new_ours:>9} "
                  f"{a1c.get('abs_delta', 0):>7.1f} {new_abs:>8.1f} {change:>+9.1f} {arrow}")
        print("-" * 70)
        new_agg = new_abs_total / manual_total * 100 if manual_total > 0 else None
        a1_agg = a1["metric"]["agg_err_pct"]
        print(f"\nAggregate metric:")
        print(f"  A1 baseline:   manual={manual_total:.1f}  ours={a1['metric']['total_ours']}  "
              f"sum|D|={a1_abs_total:.1f}  agg_err={a1_agg:.2f}%")
        print(f"  New (replay):  manual={manual_total:.1f}  ours={ours_total_new}  "
              f"sum|D|={new_abs_total:.1f}  agg_err={new_agg:.2f}%")
        print(f"  Change:        agg_err {a1_agg - new_agg:+.2f}pp "
              f"({'IMPROVED' if new_agg < a1_agg else 'WORSE'})")

    if args.save:
        EVAL_DIR.mkdir(exist_ok=True)
        out_path = EVAL_DIR / f"{args.save}.json"
        # Strip per_event for snapshot (too large); cells with tuple keys
        # become a list of dicts for JSON-serializability.
        summary = {
            "cells": [
                {"leg_id": k[0], "movement": k[1], "ours": n}
                for k, n in result["cells"].items() if k[0] is not None
            ],
            "tiers": result["tiers"],
            "dropped_origin": result["dropped_origin"],
            "dropped_dest": result["dropped_dest"],
            "n_events": result["n_events"],
        }
        out_path.write_text(json.dumps(summary, indent=2))
        print(f"\nsaved snapshot -> {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
