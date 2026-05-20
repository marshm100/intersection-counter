"""Offline origin-attribution replay.

Re-runs the pipeline's _assign_origin logic against stored
vehicle_events.trajectory_data, with a pluggable tripwire builder so we
can compare candidate fixes against the current production logic
without re-running detection.

Why offline:
  Detection is the slow step. Trajectories are stored verbatim per
  event, so origin attribution can be replayed in ~seconds. The only
  failure mode this CANNOT measure is vehicles that the live pipeline
  dropped as insufficient_data (no origin assigned at all) — those
  trajectories were never persisted. For the L18/L20/L21-over-attributed
  subset of Bug A, offline replay sees everything we need.

Usage:
  py scripts/replay_origin.py                       # current logic (sanity)
  py scripts/replay_origin.py --variant edge        # edge-anchored tripwires
  py scripts/replay_origin.py --variant edge -v     # verbose per-event log
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

# Make backend importable when this script runs from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import TRAJECTORY_MIN_DISTANCE_PX, TRIPWIRE_HALF_LENGTH_PX
from backend.services.origin_detector import (
    crossing_direction,
    did_cross_line,
)

PROJECT_DB = Path("data/projects/97a7849a/project.db")
FRAME_W, FRAME_H = 640, 480

ORIGIN_ASSIGN_MIN_FRAMES = 2  # pipeline constant


# --- Tripwire variants --------------------------------------------------

def tripwire_current(
    origin_point: tuple, ref_heading: float, half_length: float = TRIPWIRE_HALF_LENGTH_PX
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Production tripwire: perpendicular to approach, symmetric around origin."""
    perp_rad = math.radians(ref_heading + 90.0)
    dx, dy = math.sin(perp_rad), -math.cos(perp_rad)
    x, y = float(origin_point[0]), float(origin_point[1])
    return (
        (x - dx * half_length, y - dy * half_length),
        (x + dx * half_length, y + dy * half_length),
    )


def tripwire_edge_anchored(
    origin_point: tuple,
    ref_heading: float,
    half_length: float = TRIPWIRE_HALF_LENGTH_PX,
    frame_w: int = FRAME_W,
    frame_h: int = FRAME_H,
    edge_buffer: float = 100.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Like tripwire_current, but if the origin point is within edge_buffer
    of a frame edge, extend the toward-edge endpoint along the perpendicular
    until it hits that edge (or until half_length runs out, whichever is
    farther). Keeps the away-side endpoint at the symmetric position.

    Rationale: vehicles entering from off-frame are first detected several
    pixels INSIDE the frame, past a short symmetric tripwire. Extending the
    toward-edge endpoint until it touches the frame boundary gives those
    vehicles' first-second detections a chance to cross.
    """
    x, y = float(origin_point[0]), float(origin_point[1])
    perp_rad = math.radians(ref_heading + 90.0)
    dx, dy = math.sin(perp_rad), -math.cos(perp_rad)

    # Symmetric endpoints (the "+dx" and "-dx" sides).
    p_plus = (x + dx * half_length, y + dy * half_length)
    p_minus = (x - dx * half_length, y - dy * half_length)

    # Which endpoint is closer to a frame edge? Walk both candidate
    # extensions; if either can reach a frame edge within a reasonable
    # multiplier of half_length, snap that endpoint to the edge.
    def edge_clip_distance(start: tuple, direction: tuple) -> float | None:
        """Parametric distance along direction from start until first
        frame edge is reached. None if direction points away from all
        edges (shouldn't happen for unit vectors)."""
        sx, sy = start
        ddx, ddy = direction
        ts = []
        if ddx > 1e-9:
            ts.append((frame_w - sx) / ddx)
        elif ddx < -1e-9:
            ts.append((0 - sx) / ddx)
        if ddy > 1e-9:
            ts.append((frame_h - sy) / ddy)
        elif ddy < -1e-9:
            ts.append((0 - sy) / ddy)
        ts = [t for t in ts if t > 0]
        return min(ts) if ts else None

    # Distance from origin to each candidate endpoint's edge.
    dist_plus = edge_clip_distance((x, y), (dx, dy))
    dist_minus = edge_clip_distance((x, y), (-dx, -dy))

    # Only extend if (a) origin itself sits within edge_buffer of an edge
    # and (b) the edge-side extension is longer than the default half_length
    # (no point shortening). Cap extension at 2× half_length to avoid silly
    # full-frame lines on legs that happen to sit far from edges in one
    # axis but close in another.
    near_edge = (
        x < edge_buffer or x > frame_w - edge_buffer
        or y < edge_buffer or y > frame_h - edge_buffer
    )
    if not near_edge:
        return (p_minus, p_plus)

    cap = half_length * 2.0
    new_plus = p_plus
    new_minus = p_minus
    if dist_plus is not None and dist_plus > half_length:
        ext = min(dist_plus, cap)
        new_plus = (x + dx * ext, y + dy * ext)
    if dist_minus is not None and dist_minus > half_length:
        ext = min(dist_minus, cap)
        new_minus = (x - dx * ext, y - dy * ext)
    return (new_minus, new_plus)


VARIANTS = {
    "current": tripwire_current,
    "edge": tripwire_edge_anchored,
}


# --- Backward-extrapolation classifier ---------------------------------
#
# The L19 failure mode: a vehicle enters from off-frame, is first detected
# well past the synthesized tripwire, and never crosses it. Heading
# fallback fails when the early-frame displacement is below the noise
# floor (slow approach / queueing). Both signals are positional — neither
# uses where the vehicle CAME from.
#
# Backward extrapolation: from the early-trajectory window, compute the
# motion vector. Run it backward from the first detection point until the
# frame boundary. That's the synthetic entry point — where the vehicle
# would have crossed into the frame if YOLO had caught it earlier. The
# nearest leg origin (within a tolerance) is the assigned leg.
#
# Robust to: late first-detection, biased training data (none required),
# turners (early velocity reflects approach direction, not exit).
# Fails on: stationary vehicles, vehicles that turn within the first few
# detected frames. Both expected to be rare relative to the L19 dropout
# population.

BACKWARD_MIN_DISP_PX = 15.0   # minimum early displacement to trust the velocity
BACKWARD_WINDOW_FRAMES = 8    # use up to this many early frames to compute velocity
BACKWARD_MATCH_RADIUS_PX = 180.0  # how close the extrapolated point must be to a leg origin


def early_motion_vector(
    trajectory: list[tuple],
    min_disp_px: float = BACKWARD_MIN_DISP_PX,
    window_frames: int = BACKWARD_WINDOW_FRAMES,
) -> tuple[float, float] | None:
    """Return a unit motion vector from the early trajectory window.

    Walks from traj[1] forward until either (a) cumulative displacement
    from traj[0] >= min_disp_px, or (b) we've consumed window_frames
    points. Returns None if the vehicle barely moved in the window.
    """
    if len(trajectory) < 2:
        return None
    start = trajectory[0]
    upper = min(window_frames + 1, len(trajectory))
    for i in range(1, upper):
        dx = trajectory[i][0] - start[0]
        dy = trajectory[i][1] - start[1]
        if math.hypot(dx, dy) >= min_disp_px:
            mag = math.hypot(dx, dy)
            return (dx / mag, dy / mag)
    # Window exhausted without enough displacement; use whatever we have
    # at the window edge if it's nonzero.
    end = trajectory[upper - 1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    mag = math.hypot(dx, dy)
    if mag < 1.0:
        return None
    return (dx / mag, dy / mag)


def backward_extrapolated_entry(
    trajectory: list[tuple],
    frame_w: int = FRAME_W,
    frame_h: int = FRAME_H,
) -> tuple[float, float] | None:
    """Project the first detection point backward along early motion
    until the frame boundary. Returns the boundary intersection point
    (or None if the trajectory doesn't have a usable motion vector)."""
    vec = early_motion_vector(trajectory)
    if vec is None:
        return None
    vx, vy = vec
    start = trajectory[0]
    sx, sy = float(start[0]), float(start[1])

    # Backward direction.
    bx, by = -vx, -vy
    # Parametric t > 0 to hit each frame boundary; pick the smallest positive.
    ts = []
    if bx > 1e-9:
        ts.append((frame_w - sx) / bx)
    elif bx < -1e-9:
        ts.append((0 - sx) / bx)
    if by > 1e-9:
        ts.append((frame_h - sy) / by)
    elif by < -1e-9:
        ts.append((0 - sy) / by)
    ts = [t for t in ts if t > 0]
    if not ts:
        return None
    t = min(ts)
    return (sx + bx * t, sy + by * t)


def assign_by_backward_extrapolation(
    trajectory: list[tuple],
    legs: list[dict],
    match_radius_px: float = BACKWARD_MATCH_RADIUS_PX,
    frame_w: int = FRAME_W,
    frame_h: int = FRAME_H,
) -> int | None:
    """Return the leg_id of the leg whose origin point is closest to the
    backward-extrapolated entry — provided that distance is within
    match_radius_px. Returns None on any condition that should bail out
    (no motion, no leg within radius)."""
    entry = backward_extrapolated_entry(trajectory, frame_w, frame_h)
    if entry is None:
        return None
    best_lid, best_d = None, float("inf")
    for leg in legs:
        zone = leg.get("origin_zone") or []
        if not zone:
            continue
        op = zone[0] if len(zone) == 1 else (
            (sum(p[0] for p in zone) / len(zone), sum(p[1] for p in zone) / len(zone))
        )
        d = math.hypot(entry[0] - op[0], entry[1] - op[1])
        if d < best_d:
            best_d, best_lid = d, leg["leg_id"]
    if best_lid is not None and best_d <= match_radius_px:
        return best_lid
    return None


# --- Replay -------------------------------------------------------------

def replay_assign_origin(
    trajectory: list[tuple],
    legs: list[dict],
    tripwire_fn,
    use_backward: bool = False,
) -> dict:
    """Mirrors backend.services.pipeline.VehicleTracker._assign_origin.

    Returns:
      {"origin_leg_id": int | None, "method": "tripwire"|"fallback"|"backward"|"none",
       "crossing_idx": int | None, "candidate_legs_crossed": list[int]}

    Order (when use_backward=True):
      1. Tripwire crossing (highest specificity — both position + crossing-
         direction match a calibrated line).
      2. Backward extrapolation (constrains position AND early motion).
      3. Heading-only fallback (direction only — least specific, last resort).
    The reordering matters because L18 and L20 reference headings are
    only 32 apart and a westbound vehicle satisfies the <=90 heading-
    enter check for both legs. Heading-fallback then picks by angle, not
    by position, and the closer-by-angle leg wins regardless of where
    the vehicle actually came from.
    """
    n = len(trajectory)
    if n < ORIGIN_ASSIGN_MIN_FRAMES:
        return {"origin_leg_id": None, "method": "none",
                "crossing_idx": None, "candidate_legs_crossed": []}

    # Build tripwires once for all legs (they don't move per-frame).
    leg_lines = []
    for leg in legs:
        zone = leg.get("origin_zone")
        if not zone:
            continue
        if len(zone) == 1:
            ref = leg.get("reference_heading")
            if ref is None:
                continue
            line_start, line_end = tripwire_fn(zone[0], ref)
        else:
            line_start = tuple(zone[0])
            line_end = tuple(zone[1])
        leg_lines.append((leg, line_start, line_end))

    # Production walks segments per-frame; for replay we equivalently walk
    # the full segment list once and pick the FIRST crossing that registers
    # as "enter". (Production checks every leg for crossing on each frame's
    # call, returning at the first enter — so the first segment + first
    # leg that match wins, in the order legs appear in self.legs.)
    candidate_legs_crossed = []
    for i in range(1, n):
        for leg, line_start, line_end in leg_lines:
            if did_cross_line(trajectory[i - 1], trajectory[i], line_start, line_end):
                direction = crossing_direction(
                    trajectory[i - 1], trajectory[i], line_start, line_end,
                    reference_heading=leg.get("reference_heading"),
                )
                if direction == "enter":
                    return {
                        "origin_leg_id": leg["leg_id"],
                        "method": "tripwire",
                        "crossing_idx": i,
                        "candidate_legs_crossed": candidate_legs_crossed,
                    }
                else:
                    candidate_legs_crossed.append((leg["leg_id"], "exit"))

    # Backward extrapolation (when enabled): more specific than heading
    # because it constrains position AND direction. Runs BEFORE heading
    # fallback so it can correct cases where two legs sit within 90 of
    # the vehicle's motion direction.
    if use_backward:
        lid = assign_by_backward_extrapolation(trajectory, legs)
        if lid is not None:
            return {"origin_leg_id": lid, "method": "backward",
                    "crossing_idx": None,
                    "candidate_legs_crossed": candidate_legs_crossed}

    # Heading fallback: use overall first->last displacement direction.
    start = trajectory[0]
    end = trajectory[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    displacement = math.hypot(dx, dy)
    if displacement < TRAJECTORY_MIN_DISTANCE_PX:
        return {"origin_leg_id": None, "method": "none",
                "crossing_idx": None,
                "candidate_legs_crossed": candidate_legs_crossed}

    movement_heading = math.degrees(math.atan2(dx, -dy)) % 360
    best_leg, best_diff = None, float("inf")
    for leg in legs:
        ref = leg.get("reference_heading")
        if ref is None:
            continue
        diff = abs((movement_heading - ref + 180) % 360 - 180)
        if diff < best_diff:
            best_diff, best_leg = diff, leg
    if best_leg is not None and best_diff <= 90:
        return {"origin_leg_id": best_leg["leg_id"], "method": "fallback",
                "crossing_idx": None,
                "candidate_legs_crossed": candidate_legs_crossed}

    return {"origin_leg_id": None, "method": "none",
            "crossing_idx": None,
            "candidate_legs_crossed": candidate_legs_crossed}


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
        "SELECT event_id, origin_leg_id, movement, trajectory_data "
        "FROM vehicle_events WHERE camera_id=? AND rejected=0 "
        "ORDER BY event_id", (camera_id,),
    ).fetchall()
    return [
        {"event_id": r[0], "origin_leg_id": r[1], "movement": r[2],
         "trajectory": json.loads(r[3])}
        for r in rows
    ]


# --- Reporting ----------------------------------------------------------

def summarize(events: list[dict], replays: list[dict], variant: str) -> None:
    n = len(events)
    matches = sum(1 for ev, rp in zip(events, replays)
                  if ev["origin_leg_id"] == rp["origin_leg_id"])
    methods = {"tripwire": 0, "fallback": 0, "none": 0}
    for rp in replays:
        methods[rp["method"]] = methods.get(rp["method"], 0) + 1

    print(f"\n=== Replay summary (variant={variant!r}) ===")
    print(f"events: {n}")
    print(f"matches stored origin: {matches}/{n} ({matches/n*100:.1f}%)")
    print(f"replay method: {methods}")

    leg_ids = sorted({ev["origin_leg_id"] for ev in events}
                     | {rp["origin_leg_id"] for rp in replays if rp["origin_leg_id"]})
    leg_ids = [l for l in leg_ids if l is not None]

    print(f"\n--- Confusion: stored origin (rows) -> replayed origin (cols) ---")
    header = f"{'':<6}" + "".join(f"L{l:<3} " for l in leg_ids) + f"{'None':<6} {'TOT':>4}"
    print(header)
    for src in leg_ids:
        row = {l: 0 for l in leg_ids}
        none_cnt = 0
        tot = 0
        for ev, rp in zip(events, replays):
            if ev["origin_leg_id"] != src:
                continue
            tot += 1
            tgt = rp["origin_leg_id"]
            if tgt is None:
                none_cnt += 1
            else:
                row[tgt] = row.get(tgt, 0) + 1
        cells = "".join(f"{row.get(l, 0):<4} " for l in leg_ids)
        print(f"L{src:<3}  {cells}{none_cnt:<6} {tot:>4}")

    print(f"\n--- Per-leg replay attribution method ---")
    for lid in leg_ids:
        sub = [rp for ev, rp in zip(events, replays) if rp["origin_leg_id"] == lid]
        if not sub:
            continue
        ms = {"tripwire": 0, "fallback": 0}
        for rp in sub:
            ms[rp["method"]] = ms.get(rp["method"], 0) + 1
        print(f"  L{lid}: n={len(sub)} tripwire={ms.get('tripwire', 0)} "
              f"fallback={ms.get('fallback', 0)}")


def verbose_log(events: list[dict], replays: list[dict]) -> None:
    print(f"\n--- Per-event detail (changes only) ---")
    for ev, rp in zip(events, replays):
        if ev["origin_leg_id"] == rp["origin_leg_id"]:
            continue
        start = ev["trajectory"][0]
        end = ev["trajectory"][-1]
        print(f"  ev{ev['event_id']}: stored=L{ev['origin_leg_id']} -> "
              f"replay={rp['origin_leg_id']} ({rp['method']})  "
              f"start=({start[0]:.0f},{start[1]:.0f}) end=({end[0]:.0f},{end[1]:.0f}) "
              f"npts={len(ev['trajectory'])}")


def truncation_test(
    events: list[dict],
    legs: list[dict],
    tripwire_fn,
    drop_first_k: int,
    use_backward: bool,
) -> dict:
    """For each event, simulate 'YOLO missed the approach phase' by
    dropping the first drop_first_k frames of the stored trajectory,
    then replay origin assignment. Report how often we recover the
    stored origin under the simulated handicap.

    Returns aggregate counts and a per-leg recovery table.
    """
    total = recovered = lost = reassigned = 0
    per_leg = {l["leg_id"]: {"n": 0, "recovered": 0, "lost": 0, "reassigned": 0,
                             "via_backward": 0}
               for l in legs}
    for ev in events:
        traj = ev["trajectory"]
        if len(traj) <= drop_first_k + 1:
            continue   # not enough trajectory left to bother
        truncated = traj[drop_first_k:]
        rp = replay_assign_origin(truncated, legs, tripwire_fn,
                                  use_backward=use_backward)
        stored = ev["origin_leg_id"]
        bucket = per_leg.setdefault(
            stored, {"n": 0, "recovered": 0, "lost": 0, "reassigned": 0,
                     "via_backward": 0})
        bucket["n"] += 1
        total += 1
        if rp["origin_leg_id"] == stored:
            recovered += 1
            bucket["recovered"] += 1
            if rp["method"] == "backward":
                bucket["via_backward"] += 1
        elif rp["origin_leg_id"] is None:
            lost += 1
            bucket["lost"] += 1
        else:
            reassigned += 1
            bucket["reassigned"] += 1
    return {
        "total": total, "recovered": recovered, "lost": lost,
        "reassigned": reassigned, "per_leg": per_leg,
    }


def print_truncation_report(label: str, result: dict) -> None:
    t = result["total"]
    if t == 0:
        print(f"\n=== {label} === (no events long enough)")
        return
    print(f"\n=== {label} ===")
    print(f"  recovered stored origin: {result['recovered']}/{t} "
          f"({result['recovered']/t*100:.1f}%)")
    print(f"  lost to insufficient_data: {result['lost']}/{t}")
    print(f"  reassigned to wrong leg:   {result['reassigned']}/{t}")
    print(f"  per-leg:")
    for lid, b in sorted(result["per_leg"].items()):
        if b["n"] == 0:
            continue
        bw = f"  via_backward={b['via_backward']}" if b["via_backward"] else ""
        print(f"    L{lid}: n={b['n']} recovered={b['recovered']} "
              f"lost={b['lost']} reassigned={b['reassigned']}{bw}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--variant", choices=sorted(VARIANTS), default="current")
    p.add_argument("--camera-id", type=int, default=1)
    p.add_argument("--backward", action="store_true",
                   help="Add backward-extrapolation as third fallback")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Per-event log of reassignments")
    p.add_argument("--compare", action="store_true",
                   help="Run both 'current' and 'edge', diff results")
    p.add_argument("--truncate", type=int, default=None,
                   help="Truncation test: drop first K frames of each trajectory "
                        "then replay (simulates YOLO missing the approach phase)")
    args = p.parse_args()

    if not PROJECT_DB.exists():
        print(f"DB not found: {PROJECT_DB}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(conn, args.camera_id)
    events = load_events(conn, args.camera_id)
    print(f"loaded {len(events)} events, {len(legs)} legs (camera_id={args.camera_id})")

    fn = VARIANTS[args.variant]

    if args.truncate is not None:
        # Compare with/without backward fallback under the truncation handicap.
        r_no = truncation_test(events, legs, fn, args.truncate, use_backward=False)
        r_yes = truncation_test(events, legs, fn, args.truncate, use_backward=True)
        print_truncation_report(
            f"truncate first {args.truncate} frames -- NO backward fallback", r_no)
        print_truncation_report(
            f"truncate first {args.truncate} frames -- WITH backward fallback", r_yes)
        # Delta
        d_rec = r_yes["recovered"] - r_no["recovered"]
        d_los = r_yes["lost"] - r_no["lost"]
        d_rea = r_yes["reassigned"] - r_no["reassigned"]
        print(f"\n=== Delta from adding backward fallback ===")
        print(f"  recovered: {d_rec:+}    lost: {d_los:+}    reassigned: {d_rea:+}")
        return 0

    if args.compare:
        rep_cur = [replay_assign_origin(ev["trajectory"], legs, VARIANTS["current"])
                   for ev in events]
        rep_edg = [replay_assign_origin(ev["trajectory"], legs, VARIANTS["edge"])
                   for ev in events]
        summarize(events, rep_cur, "current")
        summarize(events, rep_edg, "edge")
        moved = []
        for ev, c, e in zip(events, rep_cur, rep_edg):
            if c["origin_leg_id"] != e["origin_leg_id"]:
                moved.append((ev, c, e))
        print(f"\n=== Reassignments: current -> edge ({len(moved)} events) ===")
        if args.verbose or len(moved) <= 30:
            for ev, c, e in moved:
                s = ev["trajectory"][0]
                print(f"  ev{ev['event_id']}: "
                      f"L{c['origin_leg_id']}({c['method']}) -> "
                      f"L{e['origin_leg_id']}({e['method']})  "
                      f"start=({s[0]:.0f},{s[1]:.0f})")
        from collections import Counter
        flow = Counter()
        for _, c, e in moved:
            flow[(c["origin_leg_id"], e["origin_leg_id"])] += 1
        print("\nReassignment counts (current_replay -> edge_replay):")
        for (a, b), n in sorted(flow.items(), key=lambda kv: -kv[1]):
            print(f"  L{a} -> L{b}: {n}")
        return 0

    replays = [replay_assign_origin(ev["trajectory"], legs, fn,
                                     use_backward=args.backward)
               for ev in events]
    label = f"{args.variant}" + ("+backward" if args.backward else "")
    summarize(events, replays, label)
    if args.verbose:
        verbose_log(events, replays)
    return 0


if __name__ == "__main__":
    sys.exit(main())
