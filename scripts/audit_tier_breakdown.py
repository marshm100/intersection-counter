"""Tier-breakdown audit (Stage A2).

For each persisted vehicle_event, replay its trajectory through the SAME
origin attribution tiers as backend/services/pipeline.py:_assign_origin in
order:

  Tier 0: score_origin_by_polyline  (Phase 1, primary)
  Tier 1: tripwire (zone-line crossing on a synthesized perpendicular)
  Tier 2: heading fallback (overall start->end displacement vs leg ref)

Records which tier WOULD HAVE matched for each event and tabulates the tier
distribution per (origin_leg, movement) cell. The replay also confirms
whether the replayed origin matches the stored origin (sanity check for
script correctness — the live pipeline used the same tiers, so the
distribution should reproduce stored origins for ~all events).

This cannot measure events the live pipeline dropped pre-attribution
(no origin assigned, marked n_insufficient_data, never written to DB).
Those vehicles do not exist in vehicle_events.

Usage:
  py scripts/audit_tier_breakdown.py
  py scripts/audit_tier_breakdown.py --save A2_tiers
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
    crossing_direction,
    did_cross_line,
    score_origin_by_polyline,
    tripwire_from_point,
)

PROJECT_DB = Path("data/projects/97a7849a/project.db")
EVAL_DIR = Path("evaluations")

LEG_TO_APPROACH = {
    22: "SB N Belt Line Rd",
    23: "NB N Belt Line Rd",
    24: "WB Private Driveway",
    25: "EB Northwest Dr",
}

# Mirror pipeline.py constants.
ORIGIN_ASSIGN_MIN_FRAMES = 2
POLYLINE_MIN_TRAJ_PTS = 4
POLYLINE_PREFIX_PTS = 8


def replay_origin_tier(traj: list, legs: list, paths: list) -> str:
    """Mirror pipeline.py:_assign_origin tier order. Returns the tier name
    that would have produced an assignment (or 'none')."""
    if len(traj) < ORIGIN_ASSIGN_MIN_FRAMES:
        return "none"

    # Tier 0: polyline match
    if paths and len(traj) >= POLYLINE_MIN_TRAJ_PTS:
        prefix = traj[:min(POLYLINE_PREFIX_PTS, len(traj))]
        match = score_origin_by_polyline(prefix, paths)
        if match.get("origin_leg_id") is not None:
            return "polyline"

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
            line_start = tuple(zone[0])
            line_end = tuple(zone[1])
        else:
            continue
        for i in range(1, len(traj)):
            if did_cross_line(traj[i - 1], traj[i], line_start, line_end):
                direction = crossing_direction(
                    traj[i - 1], traj[i], line_start, line_end,
                    reference_heading=leg.get("reference_heading"),
                )
                if direction == "enter":
                    return "tripwire"

    # Tier 2: heading fallback
    start = traj[0]
    end = traj[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    displacement = math.hypot(dx, dy)
    if displacement < TRAJECTORY_MIN_DISTANCE_PX:
        return "none"
    movement_heading = math.degrees(math.atan2(dx, -dy)) % 360
    best_diff = float("inf")
    for leg in legs:
        ref = leg.get("reference_heading")
        if ref is None:
            continue
        diff = abs((movement_heading - ref + 180) % 360 - 180)
        if diff < best_diff:
            best_diff = diff
    if best_diff <= 90:
        return "heading"
    return "none"


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
        "SELECT event_id, origin_leg_id, movement, trajectory_data "
        "FROM vehicle_events WHERE camera_id=? AND rejected=0 "
        "ORDER BY event_id", (camera_id,),
    ).fetchall()
    return [
        {"event_id": r[0], "origin_leg_id": r[1], "movement": r[2],
         "trajectory": json.loads(r[3]) if isinstance(r[3], str) else r[3]}
        for r in rows
    ]


NORM_MVT = {"through": "thru", "left": "left", "right": "right", "u_turn": "uturn"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--save", help="save snapshot evaluations/<name>.json")
    args = p.parse_args()

    conn = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(conn)
    paths = load_paths(conn)
    events = load_events(conn)
    conn.close()

    print(f"loaded {len(events)} events, {len(legs)} legs, {len(paths)} paths")
    print(f"path sources: {dict.fromkeys((p['source'] or 'unknown') for p in paths)}")
    print(f"path supporting_counts: {[p['supporting_count'] for p in paths]}")

    # Replay each event. Record stored (leg, movement) and replay tier.
    cells: dict[tuple[int, str], dict[str, int]] = {}
    sanity = {"replay_matches_stored_leg": 0, "total": 0}
    tier_global = {"polyline": 0, "tripwire": 0, "heading": 0, "none": 0}

    for ev in events:
        traj = ev["trajectory"]
        if not traj:
            continue
        sanity["total"] += 1
        tier = replay_origin_tier(traj, legs, paths)
        tier_global[tier] = tier_global.get(tier, 0) + 1

        # Also figure out which leg the replayed origin would have been —
        # for sanity check only (does replay match the stored origin?).
        replayed_lid = None
        if tier == "polyline":
            prefix = traj[:min(POLYLINE_PREFIX_PTS, len(traj))]
            m = score_origin_by_polyline(prefix, paths)
            replayed_lid = m.get("origin_leg_id")
        elif tier == "tripwire":
            for leg in legs:
                zone = leg.get("origin_zone")
                if not zone:
                    continue
                if len(zone) == 1:
                    ref = leg.get("reference_heading")
                    if ref is None:
                        continue
                    line_start, line_end = tripwire_from_point(
                        zone[0], ref, half_length=TRIPWIRE_HALF_LENGTH_PX)
                elif len(zone) >= 2:
                    line_start = tuple(zone[0]); line_end = tuple(zone[1])
                else:
                    continue
                hit = False
                for i in range(1, len(traj)):
                    if did_cross_line(traj[i-1], traj[i], line_start, line_end):
                        direction = crossing_direction(
                            traj[i-1], traj[i], line_start, line_end,
                            reference_heading=leg.get("reference_heading"))
                        if direction == "enter":
                            replayed_lid = leg["leg_id"]
                            hit = True
                            break
                if hit:
                    break
        elif tier == "heading":
            start = traj[0]; end = traj[-1]
            dx = end[0]-start[0]; dy = end[1]-start[1]
            if math.hypot(dx, dy) >= TRAJECTORY_MIN_DISTANCE_PX:
                mvh = math.degrees(math.atan2(dx, -dy)) % 360
                best_lid, best_diff = None, float("inf")
                for leg in legs:
                    ref = leg.get("reference_heading")
                    if ref is None:
                        continue
                    diff = abs((mvh - ref + 180) % 360 - 180)
                    if diff < best_diff:
                        best_diff, best_lid = diff, leg["leg_id"]
                if best_lid is not None and best_diff <= 90:
                    replayed_lid = best_lid

        if replayed_lid == ev["origin_leg_id"]:
            sanity["replay_matches_stored_leg"] += 1

        # Tabulate by (stored_leg, stored_movement).
        mvt = NORM_MVT.get(ev["movement"], ev["movement"] or "unknown")
        key = (ev["origin_leg_id"], mvt)
        cell = cells.setdefault(key, {"polyline": 0, "tripwire": 0,
                                       "heading": 0, "none": 0, "total": 0})
        cell[tier] += 1
        cell["total"] += 1

    # Report
    print(f"\n=== Global tier distribution (over {sanity['total']} events) ===")
    for tier, n in tier_global.items():
        pct = n / sanity["total"] * 100 if sanity["total"] else 0
        print(f"  {tier:<9} {n:>6}  ({pct:5.1f}%)")
    print(f"\nReplay vs stored origin match: "
          f"{sanity['replay_matches_stored_leg']}/{sanity['total']} "
          f"({sanity['replay_matches_stored_leg']/sanity['total']*100:.1f}%)")
    print("  (mismatches expected for events where tier ordering or polyline "
          "supporting_count tie-breaks differ from the live run; should be small)")

    print(f"\n=== Per-(stored leg, movement) tier distribution ===")
    print(f"{'Leg':<3} {'Mvt':<6} {'Total':>6} "
          f"{'Polyln':>7} {'Tripwr':>7} {'Headng':>7} {'None':>6}")
    print("-" * 55)
    for (lid, mvt), c in sorted(cells.items(), key=lambda kv: -kv[1]["total"]):
        if lid is None:
            continue
        total = c["total"]
        def frac(k):
            return f"{c[k]:>4}({c[k]/total*100:>3.0f}%)" if total else f"{c[k]:>4}    "
        print(f"L{lid:<2} {mvt:<6} {total:>6} {frac('polyline'):>11} "
              f"{frac('tripwire'):>11} {frac('heading'):>11} {frac('none'):>10}")

    payload = {
        "global_tiers": tier_global,
        "cells": [
            {"leg_id": k[0], "movement": k[1], **v}
            for k, v in cells.items() if k[0] is not None
        ],
        "sanity": sanity,
    }
    if args.save:
        EVAL_DIR.mkdir(exist_ok=True)
        path = EVAL_DIR / f"{args.save}.json"
        path.write_text(json.dumps(payload, indent=2))
        print(f"\nsaved snapshot -> {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
