"""Auto-calibrate Sunnyvale polylines from existing vehicle_events trajectories (Stage B3).

Skips YOLO+tracker re-processing AND skips zone discovery (legs are
already known). For each (origin_leg_id, destination_leg_id) bucket in
vehicle_events, fits a median polyline through the bucket's trajectories
and derives the movement label from the polyline's entry/exit tangents.

Why bucket by stored (origin, destination) instead of clustering start/end
points:
  - Single-linkage clustering with 8,759 dense points chains adjacent
    legs (start positions are only ~100 px apart vs density of points).
  - Origin_leg_id is mostly correct — A2 showed phantom errors are
    LABEL/geometry on polylines, not wrong leg assignment.
  - The mis-attribution risk for fitting is low: median-of-trajectories
    is robust if mis-bucketed events are a minority.

The output is the same JSON schema as scripts/auto_calibrate.py and
applies via scripts/apply_auto_cal.py.

Usage:
  py scripts/auto_cal_from_db.py --out evaluations/auto_cal_from_db.json
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auto_calibrate import (
    MIN_TRAJECTORY_PATH_PX,
    MIN_TRAJECTORY_POINTS,
    POLYLINE_CONTROL_POINTS,
    _fit_mean_polyline,
    _label_confidence,
    _path_distance,
    derive_path_movement,
)

PROJECT_DB = Path("data/projects/97a7849a/project.db")
FRAME_SIZE = (640, 480)

PATH_MIN_SUPPORT = 8  # minimum trajectories per (O, D) bucket to emit a polyline


def load_legs(conn: sqlite3.Connection, camera_id: int = 1) -> list[dict]:
    rows = conn.execute(
        "SELECT leg_id, reference_heading, origin_zone "
        "FROM legs WHERE camera_id=? ORDER BY leg_id", (camera_id,),
    ).fetchall()
    return [
        {
            "leg_id": r[0],
            "reference_heading": r[1],
            "origin_zone": json.loads(r[2]) if isinstance(r[2], str) else r[2],
        }
        for r in rows
    ]


def nearest_leg(point: tuple[float, float], legs: list[dict],
                max_dist_px: float | None) -> int | None:
    """Return leg_id whose origin is closest to point. None if all legs
    are beyond max_dist_px."""
    best_lid, best_d = None, float("inf")
    for leg in legs:
        zone = leg["origin_zone"] or []
        if not zone:
            continue
        ox, oy = float(zone[0][0]), float(zone[0][1])
        d = math.hypot(point[0] - ox, point[1] - oy)
        if d < best_d:
            best_d, best_lid = d, leg["leg_id"]
    if max_dist_px is not None and best_d > max_dist_px:
        return None
    return best_lid


def load_trajectories_by_snap(
    conn: sqlite3.Connection, legs: list[dict],
    camera_id: int = 1,
    snap_radius_px: float | None = None,
) -> dict[tuple[int, int], list[list[tuple[float, float]]]]:
    """Group trajectories by (nearest-leg-to-start, nearest-leg-to-end).

    Ignores stored origin_leg_id and destination_leg_id — uses known leg
    positions to bucket trajectories by their actual spatial start/end.
    """
    rows = conn.execute(
        "SELECT trajectory_data FROM vehicle_events "
        "WHERE camera_id=? AND rejected=0",
        (camera_id,),
    ).fetchall()
    buckets: dict[tuple[int, int], list] = defaultdict(list)
    n_total = 0
    n_unsnapped = 0
    for (data,) in rows:
        if not data:
            continue
        traj = json.loads(data) if isinstance(data, str) else data
        if len(traj) < MIN_TRAJECTORY_POINTS:
            continue
        traj_t = [(float(x), float(y)) for x, y in traj]
        if _path_distance(traj_t) < MIN_TRAJECTORY_PATH_PX:
            continue
        n_total += 1
        o_lid = nearest_leg(traj_t[0],  legs, snap_radius_px)
        d_lid = nearest_leg(traj_t[-1], legs, snap_radius_px)
        if o_lid is None or d_lid is None:
            n_unsnapped += 1
            continue
        buckets[(o_lid, d_lid)].append(traj_t)
    print(f"  snapped {n_total - n_unsnapped}/{n_total} trajectories "
          f"({n_unsnapped} unsnapped, radius={snap_radius_px})")
    return dict(buckets)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="evaluations/auto_cal_from_db.json")
    p.add_argument("--camera-id", type=int, default=1)
    p.add_argument("--min-support", type=int, default=PATH_MIN_SUPPORT)
    p.add_argument("--snap-radius-px", type=float, default=None,
                   help="optional cap on distance from trajectory start/end "
                        "to nearest leg origin (None = always snap to nearest)")
    args = p.parse_args()

    t0 = time.time()
    conn = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(conn, args.camera_id)
    buckets = load_trajectories_by_snap(
        conn, legs, args.camera_id, snap_radius_px=args.snap_radius_px,
    )
    conn.close()

    n_traj_total = sum(len(v) for v in buckets.values())
    print(f"loaded {n_traj_total} filtered trajectories in {len(buckets)} "
          f"(origin, destination) buckets")
    for (o, d), trajs in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        print(f"  L{o}->L{d}: n={len(trajs)}")

    # Build leg_zones from existing legs table (no clustering needed).
    leg_zone_id_for = {leg["leg_id"]: i for i, leg in enumerate(legs)}
    leg_zones = []
    for leg in legs:
        zone = leg["origin_zone"] or []
        if not zone:
            continue
        pt = zone[0]
        leg_zones.append({
            "zone_id": leg_zone_id_for[leg["leg_id"]],
            "origin_point": [float(pt[0]), float(pt[1])],
            "reference_heading": leg["reference_heading"],
            "supporting_count": sum(len(v) for k, v in buckets.items() if k[0] == leg["leg_id"]),
            "confidence": "n/a",  # using known legs, not derived from clustering
            "leg_id": leg["leg_id"],
        })

    # Fit polyline + derive label for each (O, D) bucket with enough support.
    paths = []
    skipped = []
    for (o_leg, d_leg), trajs in sorted(buckets.items()):
        if len(trajs) < args.min_support:
            skipped.append((o_leg, d_leg, len(trajs)))
            continue
        if o_leg not in leg_zone_id_for or d_leg not in leg_zone_id_for:
            skipped.append((o_leg, d_leg, len(trajs)))
            continue
        polyline = _fit_mean_polyline(trajs, POLYLINE_CONTROL_POINTS)
        if polyline is None:
            skipped.append((o_leg, d_leg, len(trajs)))
            continue
        path_dict = {
            "entry_zone_id": leg_zone_id_for[o_leg],
            "exit_zone_id":  leg_zone_id_for[d_leg],
            "polyline": polyline,
        }
        label = derive_path_movement(path_dict)
        paths.append({
            "origin_zone_id": leg_zone_id_for[o_leg],
            "destination_zone_id": leg_zone_id_for[d_leg],
            "polyline": [list(pt) for pt in polyline],
            "supporting_count": len(trajs),
            "movement_label": label,
            "_origin_leg_id": o_leg,
            "_destination_leg_id": d_leg,
        })

    paths.sort(key=lambda p: -p["supporting_count"])
    print(f"\nfitted {len(paths)} paths (min_support={args.min_support}); "
          f"skipped {len(skipped)}")
    for p in paths:
        print(f"  L{p['_origin_leg_id']}->L{p['_destination_leg_id']}  "
              f"{p['movement_label']:>7}  n={p['supporting_count']:>4}  "
              f"pts={len(p['polyline'])}")
    if skipped:
        print(f"  skipped: {skipped}")

    # Strip helper keys before writing.
    for p in paths:
        p.pop("_origin_leg_id", None)
        p.pop("_destination_leg_id", None)

    # Exit zones — same as entry (legs are bidirectional in this schema).
    exit_zones = [
        {"zone_id": z["zone_id"], "centroid": z["origin_point"],
         "supporting_count": z["supporting_count"]}
        for z in leg_zones
    ]
    # Strip leg_id helper before write.
    leg_zones_out = [
        {k: v for k, v in z.items() if k != "leg_id"}
        for z in leg_zones
    ]

    result = {
        "video_path": "(from-db)",
        "sample_window": None,
        "frame_size": list(FRAME_SIZE),
        "stats": {
            "trajectories_total": n_traj_total,
            "buckets": len(buckets),
            "paths_fitted": len(paths),
            "paths_skipped": len(skipped),
            "wall_seconds": round(time.time() - t0, 1),
        },
        "leg_zones": leg_zones_out,
        "exit_zones": exit_zones,
        "paths": paths,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
