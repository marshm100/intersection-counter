"""Conservation-based QA (Phase 3 — docs/implementation_plan_architecture_2026-06-11.md).

Zero-ground-truth sanity checks on counted events, the standard agency
practice (Maryland SHA "Reviewing and Validating Turning Movement Counts",
corroborated by VDOT/WisDOT/TxDOT balancing guidance):

1. REVERSE-MOVEMENT BALANCE (per intersection): a movement's volume should
   roughly equal its geometric reverse — NB-thru vs SB-thru, SB-left vs
   WB-right, etc. In cardinal-pair terms reverse(a->b) = (b->a). VALID OVER
   LONG COUNTS ONLY: during a peak, directional imbalance is real traffic
   (cam1 07:00-07:30: NB 595 vs SB 425 is the AM commute, not an error), so
   results carry a window-length-aware confidence and short windows report
   as informational, never red.

2. CORRIDOR CONSISTENCY (between intersections): volume exiting intersection
   A toward neighbor B should match volume entering B from A's direction,
   net of mid-block access. This observes the SAME vehicle stream twice a
   few minutes apart, so it is valid at ANY window length — it is the
   primary new-site check.

Cardinal conventions (project-wide, see backend.services.cardinals): a leg's
cardinal is its POSITION at the intersection. A vehicle entering from the south
has origin leg cardinal 'S' (the south arm); one exiting toward the north has
destination leg cardinal 'N' (the north arm). The approach NAME is the bound
direction = opposite(position) (bound_approach); left/right/through is
convention-invariant.

Verdicts: ok / warn / fail / info (info = check not applicable at this
window length or volume). Tolerances are RELATIVE with an absolute floor so
tiny cells don't flag on noise.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

from backend.database import get_connection
from backend.services.cardinals import bound_approach

# Movement from a cardinal pair (duplicated from the bank builder's table —
# module-level so the QA layer has no scripts/ dependency).
_LEFT = {("N", "E"), ("E", "S"), ("S", "W"), ("W", "N")}
_RIGHT = {("N", "W"), ("W", "S"), ("S", "E"), ("E", "N")}


def _movement(a: str, b: str) -> str:
    if a == b:
        return "u_turn"
    if (a, b) in _LEFT:
        return "left"
    if (a, b) in _RIGHT:
        return "right"
    return "through"


# Reverse balance: relative imbalance |A-B|/max(A,B) above these is flagged.
# Only meaningful over >= MIN_BALANCE_WINDOW_SEC of footage; below that the
# check reports verdict="info" (real directional peaking dominates).
REVERSE_WARN = 0.25
REVERSE_FAIL = 0.50
MIN_CELL_VOLUME = 20          # ignore cells smaller than this (noise floor)
MIN_BALANCE_WINDOW_SEC = 6 * 3600

# Corridor consistency: the same stream measured twice. Mid-block driveways
# add/remove some vehicles; the corridor's own healthy links run ~5-10%.
CORRIDOR_WARN = 0.15
CORRIDOR_FAIL = 0.30
MIN_LINK_VOLUME = 30


def _cardinal_volumes(project_id: str, intersection_id: int) -> tuple[dict, float]:
    """Aggregate counted events for an intersection into (origin_cardinal,
    dest_cardinal) -> count, plus the processed window length in seconds.

    Uses every camera on the intersection; legs map leg_id -> cardinal.
    Events missing a destination are skipped (they cannot conserve)."""
    conn = get_connection(project_id)
    try:
        cams = [r[0] for r in conn.execute(
            "SELECT camera_id FROM cameras WHERE intersection_id = ?",
            (intersection_id,)).fetchall()]
        if not cams:
            return {}, 0.0
        ph = ",".join("?" * len(cams))
        card = {lid: (cd or "").upper() for lid, cd in conn.execute(
            f"SELECT leg_id, cardinal_direction FROM legs WHERE camera_id IN ({ph})",
            cams).fetchall()}
        rows = conn.execute(
            f"SELECT origin_leg_id, destination_leg_id, timestamp_video "
            f"FROM vehicle_events WHERE rejected = 0 AND camera_id IN ({ph}) "
            f"AND destination_leg_id IS NOT NULL", cams).fetchall()
    finally:
        conn.close()
    vols: dict = defaultdict(int)
    tmin = tmax = None
    for ol, dl, ts in rows:
        a, b = card.get(ol), card.get(dl)
        if not a or not b:
            continue
        vols[(a, b)] += 1
        if ts is not None:
            tmin = ts if tmin is None else min(tmin, ts)
            tmax = ts if tmax is None else max(tmax, ts)
    window = (tmax - tmin) if (tmin is not None and tmax is not None) else 0.0
    return dict(vols), float(window)


def reverse_balance(project_id: str, intersection_id: int) -> dict:
    """3.1 — per-intersection reverse-movement balance report."""
    vols, window = _cardinal_volumes(project_id, intersection_id)
    short_window = window < MIN_BALANCE_WINDOW_SEC
    pairs, seen = [], set()
    for (a, b), n in sorted(vols.items(), key=lambda kv: -kv[1]):
        if (a, b) in seen or a == b:
            continue
        rev = vols.get((b, a), 0)
        seen.add((a, b)); seen.add((b, a))
        big = max(n, rev)
        if big < MIN_CELL_VOLUME:
            continue
        imb = abs(n - rev) / big if big else 0.0
        if short_window:
            verdict = "info"
        elif imb >= REVERSE_FAIL:
            verdict = "fail"
        elif imb >= REVERSE_WARN:
            verdict = "warn"
        else:
            verdict = "ok"
        pairs.append({
            "movement": f"{bound_approach(a)}B {_movement(a, b)}",
            "reverse": f"{bound_approach(b)}B {_movement(b, a)}",
            "cells": [{"origin_cardinal": a, "dest_cardinal": b, "count": n},
                      {"origin_cardinal": b, "dest_cardinal": a, "count": rev}],
            "imbalance": round(imb, 3),
            "verdict": verdict,
        })
    return {
        "check": "reverse_balance",
        "intersection_id": intersection_id,
        "window_seconds": round(window),
        "applicable": not short_window,
        "note": (None if not short_window else
                 f"window {window/3600:.1f}h < {MIN_BALANCE_WINDOW_SEC/3600:.0f}h — "
                 "directional peaking dominates short windows; informational only"),
        "pairs": pairs,
    }


def _directional_io(project_id: str, intersection_id: int) -> dict:
    """Per-position IN/OUT totals for one intersection.

    Cardinal is the leg POSITION, so it already IS the compass side: origin
    cardinal 'S' = a vehicle arriving FROM the south arm; dest cardinal 'N' =
    one leaving via the north arm. Keyed by that side: out['N'] = vehicles
    leaving northward; in_['S'] = vehicles arriving from the south."""
    vols, window = _cardinal_volumes(project_id, intersection_id)
    out = defaultdict(int)
    in_ = defaultdict(int)
    for (a, b), n in vols.items():
        in_[a] += n    # origin cardinal = position = the side it came from
        out[b] += n    # dest cardinal = position = the side it left toward
    return {"in": dict(in_), "out": dict(out), "window_seconds": window}


def corridor_consistency(project_id: str, ordered_intersections: list[int],
                         axis: str = "NS") -> dict:
    """3.2 — between-intersection flow conservation along a corridor.

    ordered_intersections: intersection_ids in geographic order, FIRST =
    southernmost (axis 'NS') or westernmost (axis 'EW'). For each adjacent
    pair (A south of B): A.out_north ~ B.in_south and B.out_south ~ A.in_north.
    Mid-block access (driveways/side streets) shows up as a consistent signed
    residual — a few % is normal, large gaps implicate counting."""
    up, down = ("N", "S") if axis.upper() == "NS" else ("E", "W")
    io = {iid: _directional_io(project_id, iid) for iid in ordered_intersections}
    links = []
    for a, b in zip(ordered_intersections, ordered_intersections[1:]):
        for (label, send, recv) in (
                (f"{a}->{b} ({up}bound)", io[a]["out"].get(up, 0), io[b]["in"].get(down, 0)),
                (f"{b}->{a} ({down}bound)", io[b]["out"].get(down, 0), io[a]["in"].get(up, 0))):
            big = max(send, recv)
            if big < MIN_LINK_VOLUME:
                verdict, gap = "info", 0.0
            else:
                gap = abs(send - recv) / big
                verdict = ("fail" if gap >= CORRIDOR_FAIL
                           else "warn" if gap >= CORRIDOR_WARN else "ok")
            links.append({"link": label, "sent": send, "received": recv,
                          "gap": round(gap, 3), "verdict": verdict})
    return {"check": "corridor_consistency", "axis": axis,
            "order": ordered_intersections, "links": links}
