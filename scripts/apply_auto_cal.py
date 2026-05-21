"""Take an auto_calibrate.py output JSON and apply its suggested paths
to a project's camera, writing into intersection_paths via the suggestion
flow (save_calibration_suggestion + apply mapping).

Used to bootstrap the overnight test: auto-cal runs offline, this script
pushes the result into the DB so the pipeline picks it up on next run.

Usage:
  py scripts/apply_auto_cal.py \\
      --project 97a7849a --camera-id 1 \\
      --suggestion evaluations/auto_cal_sunnyvale_am_15min.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import (
    clear_paths_for_camera, get_connection, list_paths_for_camera,
    mark_suggestion_applied, save_calibration_suggestion, upsert_path,
)


def map_zones_to_legs(payload: dict, project_id: str, camera_id: int,
                     tolerance_px: float = 80.0) -> dict[int, int]:
    """For each suggested leg_zone, find the nearest existing leg by
    Euclidean distance between origin points. Returns {zone_id: leg_id}.
    Zones with no leg within tolerance_px are absent from the dict."""
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT leg_id, origin_zone FROM legs WHERE camera_id=?", (camera_id,),
        ).fetchall()
    finally:
        conn.close()
    legs = []
    for lid, zone_str in rows:
        try:
            zone = json.loads(zone_str) if zone_str else []
            if zone and len(zone) >= 1:
                legs.append((lid, float(zone[0][0]), float(zone[0][1])))
        except Exception:
            pass

    out = {}
    for z in payload.get("leg_zones", []):
        zid = z["zone_id"]
        ox, oy = z["origin_point"]
        best, best_d = None, float("inf")
        for lid, lx, ly in legs:
            d = math.hypot(ox - lx, oy - ly)
            if d < best_d:
                best_d, best = d, lid
        if best is not None and best_d <= tolerance_px:
            out[zid] = best
            print(f"  zone {zid} ({ox:.0f},{oy:.0f}) -> leg {best} (dist={best_d:.1f}px)")
        else:
            print(f"  zone {zid} ({ox:.0f},{oy:.0f}) UNMATCHED (nearest leg dist={best_d:.1f}px)")
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True, help="project_id (folder name)")
    p.add_argument("--camera-id", type=int, required=True)
    p.add_argument("--suggestion", required=True,
                   help="path to auto_calibrate.py output JSON")
    p.add_argument("--tolerance-px", type=float, default=80.0,
                   help="max distance from suggested zone to existing leg origin")
    p.add_argument("--save-suggestion", action="store_true",
                   help="ALSO persist the suggestion to calibration_suggestions "
                        "for UI review (in addition to applying paths)")
    args = p.parse_args()

    payload = json.loads(Path(args.suggestion).read_text())
    print(f"loaded suggestion: {len(payload.get('leg_zones', []))} zones, "
          f"{len(payload.get('paths', []))} paths")
    print()

    print("Mapping suggestion zones to existing legs:")
    zone_to_leg = map_zones_to_legs(payload, args.project, args.camera_id,
                                    tolerance_px=args.tolerance_px)
    print()

    if not zone_to_leg:
        print("No suggestion zones map to existing legs. Aborting.")
        return 1

    # Optionally persist the full suggestion to the DB so it shows up in
    # the calibration UI banner (status: applied).
    if args.save_suggestion:
        meta = {"applied_via": "scripts/apply_auto_cal.py",
                "tolerance_px": args.tolerance_px}
        save_calibration_suggestion(args.project, args.camera_id, payload,
                                    job_metadata=meta)
        mark_suggestion_applied(args.project, args.camera_id)
        print("saved suggestion to calibration_suggestions (status=applied)")
        print()

    print(f"Clearing existing paths for camera {args.camera_id}...")
    n_cleared = clear_paths_for_camera(args.project, args.camera_id)
    print(f"  removed {n_cleared} existing paths")
    print()

    applied = 0
    skipped = []
    for path in payload.get("paths", []):
        ozid = path.get("origin_zone_id")
        dzid = path.get("destination_zone_id")
        o_lid = zone_to_leg.get(ozid)
        d_lid = zone_to_leg.get(dzid)
        if o_lid is None or d_lid is None:
            skipped.append((ozid, dzid))
            continue
        upsert_path(
            args.project, args.camera_id, o_lid, d_lid,
            path["polyline"], path["movement_label"],
            source="auto", supporting_count=path.get("supporting_count", 0),
        )
        applied += 1
        print(f"  applied: L{o_lid}->L{d_lid}  {path['movement_label']:>7}  "
              f"n={path.get('supporting_count', 0):>4}  "
              f"{len(path['polyline'])}pts")

    print()
    print(f"applied {applied} paths, skipped {len(skipped)}")
    if skipped:
        print(f"  skipped (zone unmapped): {skipped}")

    final = list_paths_for_camera(args.project, args.camera_id)
    print(f"intersection_paths for camera {args.camera_id} now: {len(final)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
