"""Offline movement-label diagnostic for Bug B.

For every stored event, re-derive (origin, destination, movement) under
candidate variants of destination scoring and derive_movement, and compare
to what production wrote. Targets the two known mislabels:

  Bug B-1: L18 phantom lefts -- derive_movement labels L18 -> L20 (delta
    31 CCW) as "left" even though L20 is a slight bend in the road, not a
    geometric left turn.

  Bug B-2: L21 fake throughs -- L21 (Northwest Dr) physically terminates
    at the intersection, but derive_movement labels L21 -> L20 as "through"
    because L20 sits at rank 1 of 3 in CCW order from L21.

Variants exposed:
  - destination weights (heading vs position)
  - shape-aware override (use net_heading_change to veto when extreme)
  - geometric paired-road derive_movement (no-through when no opposite)
  - through_partner-aware derive_movement (engineer-provided hint)

Usage:
  py scripts/replay_movement.py                       # default report
  py scripts/replay_movement.py --variant shape       # apply shape override
  py scripts/replay_movement.py --variant paired      # paired-road
  py scripts/replay_movement.py --pair 18:20          # focus on one pair
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.trajectory_classifier import (
    derive_movement as derive_movement_current,
    score_destination_leg,
)

PROJECT_DB = Path("data/projects/97a7849a/project.db")

# Shape-bucket thresholds from backend/config.py (mirrored locally so the
# diagnostic doesn't pull config side-effects).
THROUGH_MAX = 25.0
TURN_MIN = 35.0
UTURN_MIN = 135.0


# --- I/O ----------------------------------------------------------------

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


def load_events(conn: sqlite3.Connection, camera_id: int = 1) -> list[dict]:
    rows = conn.execute(
        "SELECT event_id, origin_leg_id, destination_leg_id, movement, "
        "trajectory_data, classifier_net_heading_change, "
        "destination_confidence, destination_posterior_json "
        "FROM vehicle_events WHERE camera_id=? AND rejected=0 "
        "ORDER BY event_id", (camera_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "event_id": r[0],
            "origin_leg_id": r[1],
            "destination_leg_id": r[2],
            "movement": r[3],
            "trajectory": json.loads(r[4]) if r[4] else [],
            "net_heading_change": r[5],
            "destination_confidence": r[6],
            "destination_posterior": json.loads(r[7]) if r[7] else {},
        })
    return out


# --- derive_movement variants ------------------------------------------

def derive_movement_paired(
    origin_leg: dict,
    destination_leg: dict | None,
    all_legs: list[dict],
    *,
    through_tolerance_deg: float = 20.0,
) -> str:
    """Geometric paired-road variant.

    For each origin leg, identify the through-partner: the leg whose
    reference_heading is closest to opposite (within through_tolerance_deg).
    If no candidate falls inside that tolerance, the origin is treated as a
    terminating leg -- all non-origin destinations are turns, never "through."

    For non-through destinations, classify as left or right by which side
    of the origin's heading vector the destination's origin point sits.
    """
    if destination_leg is None:
        return "insufficient_data"
    if destination_leg["leg_id"] == origin_leg["leg_id"]:
        return "u_turn"

    origin_ref = float(origin_leg.get("reference_heading", 0))
    opposite = (origin_ref + 180.0) % 360.0

    def _delta_to_opposite(leg: dict) -> float:
        d = abs(float(leg.get("reference_heading", 0)) - opposite)
        return min(d, 360.0 - d)

    others = [l for l in all_legs if l["leg_id"] != origin_leg["leg_id"]]
    if not others:
        return "u_turn"

    # Closest-to-opposite candidate; "through-partner" if within tolerance.
    candidates = sorted(others, key=_delta_to_opposite)
    through_partner = (
        candidates[0] if _delta_to_opposite(candidates[0]) <= through_tolerance_deg
        else None
    )

    if through_partner is not None and destination_leg["leg_id"] == through_partner["leg_id"]:
        return "through"

    # All other destinations are turns. Side-of-axis check.
    # Origin's forward vector in image coords (y-down): (sin(h), -cos(h)).
    h = math.radians(origin_ref)
    fx, fy = math.sin(h), -math.cos(h)

    origin_pt = _leg_origin_point(origin_leg)
    dest_pt = _leg_origin_point(destination_leg)
    rx, ry = dest_pt[0] - origin_pt[0], dest_pt[1] - origin_pt[1]

    # 2D cross product: fx*ry - fy*rx.
    # In image coords (y-down), positive cross = destination is on RIGHT of
    # forward direction; negative = LEFT. (Verify against a known case below.)
    cross = fx * ry - fy * rx
    return "right" if cross > 0 else "left"


def derive_movement_through_partner_hint(
    origin_leg: dict,
    destination_leg: dict | None,
    all_legs: list[dict],
    through_partner_map: dict[int, int | None],
) -> str:
    """Engineer-provided through-partner variant (Tier C preview).

    through_partner_map: {origin_leg_id -> through_partner_leg_id or None}.
    None = terminating leg. Used to label destinations correctly even
    when geometry alone is ambiguous (L21 -> L20 sits near-opposite but
    isn't a real through).
    """
    if destination_leg is None:
        return "insufficient_data"
    if destination_leg["leg_id"] == origin_leg["leg_id"]:
        return "u_turn"

    partner_id = through_partner_map.get(origin_leg["leg_id"])
    if partner_id is not None and destination_leg["leg_id"] == partner_id:
        return "through"

    # Side classification same as paired variant.
    origin_ref = float(origin_leg.get("reference_heading", 0))
    h = math.radians(origin_ref)
    fx, fy = math.sin(h), -math.cos(h)
    origin_pt = _leg_origin_point(origin_leg)
    dest_pt = _leg_origin_point(destination_leg)
    rx, ry = dest_pt[0] - origin_pt[0], dest_pt[1] - origin_pt[1]
    cross = fx * ry - fy * rx
    return "right" if cross > 0 else "left"


def _leg_origin_point(leg: dict) -> tuple[float, float]:
    oz = leg.get("origin_zone") or []
    if not oz:
        return (0.0, 0.0)
    if len(oz) == 1:
        return (float(oz[0][0]), float(oz[0][1]))
    sx = sum(float(p[0]) for p in oz) / len(oz)
    sy = sum(float(p[1]) for p in oz) / len(oz)
    return (sx, sy)


# --- Shape-aware veto ---------------------------------------------------

def shape_implied_movement(net_heading_change: float | None) -> str | None:
    """What movement would the trajectory's shape suggest in isolation?

    Returns None if we can't decide (no shape data). Otherwise one of
    through / left / right / u_turn using the classifier's existing
    bucket thresholds.
    """
    if net_heading_change is None:
        return None
    abs_change = abs(net_heading_change)
    if abs_change >= UTURN_MIN:
        return "u_turn"
    if abs_change <= THROUGH_MAX:
        return "through"
    if abs_change >= TURN_MIN:
        return "left" if net_heading_change < 0 else "right"
    return None  # ambiguous zone


# --- Pair-level diagnostics --------------------------------------------

def pair_summary(events: list[dict], legs_by_id: dict[int, dict]) -> None:
    """For each (origin, destination, movement) triple seen in the DB,
    print event count + stats on net_heading_change + spatial spread of
    trajectory end positions. This is the headline diagnostic."""
    by_triple = defaultdict(list)
    for ev in events:
        if ev["origin_leg_id"] is None:
            continue
        key = (ev["origin_leg_id"], ev["destination_leg_id"], ev["movement"])
        by_triple[key].append(ev)

    print(f"\n{'=' * 76}")
    print(f"Per-(origin, destination, movement) summary")
    print(f"{'=' * 76}")
    print(f"{'O':>3} {'D':>3} {'mvt':<8} {'n':>4} {'nhc_mean':>10} {'nhc_med':>9} "
          f"{'nhc_p10/p90':>13} {'end_xrange':>12} {'end_yrange':>12} {'shape!=lbl':>10}")
    for key in sorted(by_triple):
        o, d, m = key
        evs = by_triple[key]
        n = len(evs)
        nhcs = [e["net_heading_change"] for e in evs if e["net_heading_change"] is not None]
        if nhcs:
            nhcs_sorted = sorted(nhcs)
            mean = sum(nhcs) / len(nhcs)
            med = nhcs_sorted[len(nhcs_sorted) // 2]
            p10 = nhcs_sorted[max(0, int(len(nhcs_sorted) * 0.1) - 1)]
            p90 = nhcs_sorted[min(len(nhcs_sorted) - 1, int(len(nhcs_sorted) * 0.9))]
        else:
            mean = med = p10 = p90 = float("nan")
        ends = [e["trajectory"][-1] for e in evs if e["trajectory"]]
        if ends:
            xs = [p[0] for p in ends]
            ys = [p[1] for p in ends]
            x_range = f"{int(min(xs))}-{int(max(xs))}"
            y_range = f"{int(min(ys))}-{int(max(ys))}"
        else:
            x_range = y_range = "-"
        shape_disagreements = sum(
            1 for e in evs
            if shape_implied_movement(e["net_heading_change"]) is not None
            and shape_implied_movement(e["net_heading_change"]) != m
        )
        d_s = f"L{d}" if d is not None else "None"
        print(f"L{o:<2} {d_s:>3} {m:<8} {n:>4} "
              f"{mean:>10.1f} {med:>9.1f} {p10:>6.0f}/{p90:<6.0f} "
              f"{x_range:>12} {y_range:>12} {shape_disagreements:>10}")


def per_leg_movement_distribution(events: list[dict]) -> None:
    """Per origin leg, distribution of movement labels in the DB."""
    print(f"\n{'=' * 76}")
    print(f"Per-origin-leg movement distribution (stored labels)")
    print(f"{'=' * 76}")
    by_origin = defaultdict(Counter)
    for ev in events:
        if ev["origin_leg_id"] is not None:
            by_origin[ev["origin_leg_id"]][ev["movement"]] += 1
    print(f"{'origin':>6} {'through':>8} {'left':>5} {'right':>6} "
          f"{'u_turn':>7} {'insufficient_data':>18} {'TOTAL':>6}")
    for lid in sorted(by_origin):
        c = by_origin[lid]
        total = sum(c.values())
        print(f"L{lid:<5} {c.get('through', 0):>8} {c.get('left', 0):>5} "
              f"{c.get('right', 0):>6} {c.get('u_turn', 0):>7} "
              f"{c.get('insufficient_data', 0):>18} {total:>6}")


# --- Variant evaluation ------------------------------------------------

def reweight_destination(
    trajectory: list, origin_leg_id: int, legs: list[dict],
    heading_weight: float, position_weight: float,
) -> int | None:
    """Re-run destination scorer with custom weights, return chosen leg_id."""
    res = score_destination_leg(
        trajectory, origin_leg_id, legs,
        heading_weight=heading_weight,
        position_weight=position_weight,
    )
    return res.get("destination_leg_id")


def evaluate_variants(events: list[dict], legs: list[dict]) -> None:
    legs_by_id = {l["leg_id"]: l for l in legs}

    # Tier A: tighter destination weights
    dest_changes_A = []
    for ev in events:
        if ev["origin_leg_id"] is None or not ev["trajectory"]:
            continue
        new_dest = reweight_destination(
            ev["trajectory"], ev["origin_leg_id"], legs,
            heading_weight=0.85, position_weight=0.15,
        )
        if new_dest != ev["destination_leg_id"]:
            dest_changes_A.append((ev, new_dest))

    # Tier B: geometric paired-road derive_movement
    label_changes_B = []
    for ev in events:
        if ev["origin_leg_id"] is None or ev["destination_leg_id"] is None:
            continue
        origin = legs_by_id.get(ev["origin_leg_id"])
        dest = legs_by_id.get(ev["destination_leg_id"])
        if origin is None or dest is None:
            continue
        new_lbl = derive_movement_paired(origin, dest, legs)
        if new_lbl != ev["movement"]:
            label_changes_B.append((ev, new_lbl))

    # Tier C preview: hand-coded through-partner map for Sunnyvale.
    # L18 <-> L19 (Belt Line); L20 and L21 marked terminating.
    sunnyvale_partners = {18: 19, 19: 18, 20: None, 21: None}
    label_changes_C = []
    for ev in events:
        if ev["origin_leg_id"] is None or ev["destination_leg_id"] is None:
            continue
        origin = legs_by_id.get(ev["origin_leg_id"])
        dest = legs_by_id.get(ev["destination_leg_id"])
        if origin is None or dest is None:
            continue
        new_lbl = derive_movement_through_partner_hint(
            origin, dest, legs, sunnyvale_partners,
        )
        if new_lbl != ev["movement"]:
            label_changes_C.append((ev, new_lbl))

    print(f"\n{'=' * 76}")
    print(f"Variant evaluation (events that would change)")
    print(f"{'=' * 76}")
    print(f"Tier A -- tighten destination weights to 0.85/0.15:")
    print(f"  destination changes: {len(dest_changes_A)} of {len(events)} events")
    _print_change_flow_dest(dest_changes_A)

    print(f"\nTier B -- geometric paired-road derive_movement (through_tol=20):")
    print(f"  label changes: {len(label_changes_B)} of {len(events)} events")
    _print_change_flow_label(label_changes_B)

    print(f"\nTier C -- engineer-provided through-partner map "
          f"(L18<->L19, L20/L21 terminating):")
    print(f"  label changes: {len(label_changes_C)} of {len(events)} events")
    _print_change_flow_label(label_changes_C)


def _print_change_flow_dest(changes: list) -> None:
    flow = Counter()
    for ev, new in changes:
        old = ev["destination_leg_id"]
        flow[(ev["origin_leg_id"], old, new)] += 1
    for (o, old, new), n in sorted(flow.items(), key=lambda kv: -kv[1])[:15]:
        old_s = f"L{old}" if old else "None"
        new_s = f"L{new}" if new else "None"
        print(f"    L{o}: dest {old_s} -> {new_s}  ({n})")


def _print_change_flow_label(changes: list) -> None:
    flow = Counter()
    for ev, new in changes:
        flow[(ev["origin_leg_id"], ev["destination_leg_id"], ev["movement"], new)] += 1
    for (o, d, old, new), n in sorted(flow.items(), key=lambda kv: -kv[1])[:15]:
        d_s = f"L{d}" if d else "None"
        print(f"    L{o}->{d_s}: {old} -> {new}  ({n})")


# --- Self-test of new derive_movement variants -------------------------

def self_test_variants(legs: list[dict]) -> None:
    """Spot-check the new variants on the four named edge cases."""
    legs_by_id = {l["leg_id"]: l for l in legs}
    print(f"\n{'=' * 76}")
    print(f"Variant self-test on named cases")
    print(f"{'=' * 76}")
    cases = [
        (18, 19, "expect: through"),
        (18, 20, "expect: bend, NOT a left"),
        (18, 21, "expect: right turn"),
        (21, 18, "expect: left or right (turn)"),
        (21, 19, "expect: turn (Northwest Dr terminates)"),
        (21, 20, "expect: turn (Northwest Dr terminates, manual=0 throughs)"),
    ]
    sunnyvale_partners = {18: 19, 19: 18, 20: None, 21: None}
    print(f"{'O':>3} {'D':>3} {'current':>10} {'paired':>10} {'C-hint':>10}  note")
    for o, d, note in cases:
        o_leg = legs_by_id[o]
        d_leg = legs_by_id[d]
        cur = derive_movement_current(o_leg, d_leg, all_legs=legs)
        pair = derive_movement_paired(o_leg, d_leg, legs)
        hint = derive_movement_through_partner_hint(o_leg, d_leg, legs, sunnyvale_partners)
        print(f"L{o:<2} L{d:<2} {cur:>10} {pair:>10} {hint:>10}  {note}")


# --- CLI ----------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--camera-id", type=int, default=1)
    p.add_argument("--pair", type=str, default=None,
                   help="Focus on a single origin:dest pair, e.g. 18:20")
    args = p.parse_args()

    if not PROJECT_DB.exists():
        print(f"DB not found: {PROJECT_DB}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(conn, args.camera_id)
    legs_by_id = {l["leg_id"]: l for l in legs}
    events = load_events(conn, args.camera_id)
    print(f"loaded {len(events)} events, {len(legs)} legs "
          f"(camera_id={args.camera_id})")

    if args.pair:
        try:
            o, d = (int(x) for x in args.pair.split(":"))
        except ValueError:
            print(f"--pair format is O:D, e.g. 18:20", file=sys.stderr)
            return 1
        sub = [ev for ev in events
               if ev["origin_leg_id"] == o and ev["destination_leg_id"] == d]
        print(f"\nFocused: L{o} -> L{d}  ({len(sub)} events)")
        for ev in sub:
            t = ev["trajectory"]
            start = t[0] if t else ("-", "-")
            end = t[-1] if t else ("-", "-")
            nhc = ev["net_heading_change"]
            shape = shape_implied_movement(nhc) or "ambiguous"
            nhc_s = f"{nhc:>6.1f}" if nhc is not None else "   n/a"
            print(f"  ev{ev['event_id']:>4}: mvt={ev['movement']:<6} "
                  f"nhc={nhc_s}  shape_says={shape:<9} "
                  f"start=({start[0]:>4.0f},{start[1]:>4.0f}) "
                  f"end=({end[0]:>4.0f},{end[1]:>4.0f}) "
                  f"npts={len(t)}")
        return 0

    per_leg_movement_distribution(events)
    pair_summary(events, legs_by_id)
    self_test_variants(legs)
    evaluate_variants(events, legs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
