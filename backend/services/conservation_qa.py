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
# Peak-aware applicability (plan_reverse_balance_2026-07-29): span is the
# wrong question; coverage SHAPE is the right one. Occupancy is bucketed at
# 15 min; a hole > BALANCE_GAP_SPLIT_SEC splits blocks; declared trims or
# multi-block coverage = a peak-window claim where directional imbalance is
# expected traffic -> informational. The split threshold is MEASURED, not
# the 20-min spot convention: overnight ZERO-TRAFFIC lulls on a processed
# full-day run reach 53 min (int3, 2026-07-29) while true processing gaps
# are >= 120 min (int4/int5) — 90 min separates the classes with margin
# both ways (a 20-min split shredded int3 into 8 phantom blocks and wrongly
# demoted the one full-day camera; plan doc verdict).
BALANCE_BUCKET_SEC = 15 * 60
BALANCE_GAP_SPLIT_SEC = 90 * 60


def _coverage_blocks(project_id: str, intersection_id: int) -> int:
    """Number of continuous processed-coverage blocks at this intersection
    (15-min occupancy buckets; holes > BALANCE_GAP_SPLIT_SEC split).
    0 = no events."""
    conn = get_connection(project_id)
    try:
        buckets = [r[0] for r in conn.execute(
            "SELECT DISTINCT CAST(e.timestamp_video / ? AS INTEGER) "
            "FROM vehicle_events e JOIN cameras c ON c.camera_id = e.camera_id "
            "WHERE c.intersection_id = ? AND e.rejected = 0 "
            "AND e.timestamp_video IS NOT NULL ORDER BY 1",
            (BALANCE_BUCKET_SEC, intersection_id))]
    finally:
        conn.close()
    if not buckets:
        return 0
    allowed_gap = max(1, int(BALANCE_GAP_SPLIT_SEC // BALANCE_BUCKET_SEC))
    blocks = 1
    for prev, cur in zip(buckets, buckets[1:]):
        if cur - prev > allowed_gap:
            blocks += 1
    return blocks


def _has_peak_trims(project_id: str, intersection_id: int) -> bool:
    """True when declared trims constitute a PEAK-WINDOW claim: several
    windows, or one short one. A SINGLE continuous trim >= the balance
    floor (e.g. a declared daylight envelope) is day-shaped — reverse
    balance stays applicable there (6.4 rehearsal finding, 2026-07-29:
    accepting int3's 06:00-20:00 daylight trim must not silence its
    genuine full-day prompt)."""
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT start_wallclock, end_wallclock FROM trims "
            "WHERE intersection_id = ?", (intersection_id,)).fetchall()
    finally:
        conn.close()
    if not rows:
        return False
    if len(rows) > 1:
        return True

    def secs(hms: str) -> int:
        h, m, s = (int(x) for x in str(hms).split(":"))
        return h * 3600 + m * 60 + s
    a, b = rows[0]
    return (secs(b) - secs(a)) < MIN_BALANCE_WINDOW_SEC

# Corridor consistency: the same stream measured twice. Mid-block driveways
# add/remove some vehicles; the corridor's own healthy links run ~5-10%.
CORRIDOR_WARN = 0.15
CORRIDOR_FAIL = 0.30
MIN_LINK_VOLUME = 30


def _cardinal_volumes(project_id: str, intersection_id: int,
                      _cache: dict | None = None) -> tuple[dict, float]:
    """Aggregate counted events for an intersection into (origin_cardinal,
    dest_cardinal) -> count, plus the processed window length in seconds.

    Uses every camera on the intersection; legs map leg_id -> cardinal.
    Events missing a destination are skipped (they cannot conserve).

    `_cache`: optional {(project_id, intersection_id): result} memo for a single
    top-level computation. Each scan of vehicle_events is several seconds on a
    OneDrive-backed DB, and the acceptance/export gates need the SAME
    intersection's volumes many times over (corridor_consistency + reverse_balance
    + a per-intersection rollup); without the memo export_gate does ~30 scans.
    Default None preserves the original recompute-every-call behavior."""
    if _cache is not None and (project_id, intersection_id) in _cache:
        return _cache[(project_id, intersection_id)]
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
        # Aggregate in SQL (GROUP BY ~15 cells) rather than materializing every
        # event row in Python: on this OneDrive-backed DB fetching 17k rows took
        # ~29s vs ~1s for the grouped query (28x). Window = MIN/MAX timestamp over
        # the same rows, taken per group then reduced.
        grp = conn.execute(
            f"SELECT origin_leg_id, destination_leg_id, COUNT(*), "
            f"MIN(timestamp_video), MAX(timestamp_video) "
            f"FROM vehicle_events WHERE rejected = 0 AND camera_id IN ({ph}) "
            f"AND destination_leg_id IS NOT NULL "
            f"GROUP BY origin_leg_id, destination_leg_id", cams).fetchall()
    finally:
        conn.close()
    vols: dict = defaultdict(int)
    tmin = tmax = None
    for ol, dl, cnt, gmin, gmax in grp:
        a, b = card.get(ol), card.get(dl)
        if not a or not b:
            continue
        vols[(a, b)] += cnt
        if gmin is not None:
            tmin = gmin if tmin is None else min(tmin, gmin)
        if gmax is not None:
            tmax = gmax if tmax is None else max(tmax, gmax)
    window = (tmax - tmin) if (tmin is not None and tmax is not None) else 0.0
    result = (dict(vols), float(window))
    if _cache is not None:
        _cache[(project_id, intersection_id)] = result
    return result


def reverse_balance(project_id: str, intersection_id: int,
                    _cache: dict | None = None) -> dict:
    """3.1 — per-intersection reverse-movement balance report.

    PEAK-AWARE APPLICABILITY (plan_reverse_balance_2026-07-29): binding
    verdicts require a claim scope that is genuinely continuous-day-
    shaped — no declared trims (trims = an explicit peak-window claim),
    a SINGLE continuous coverage block, and the >=6 h floor. Over peak
    windows the AM-in/PM-out asymmetry is real traffic (the acceptance
    sim measured this check red on all five corridor intersections for
    exactly that reason), so those report informational."""
    vols, window = _cardinal_volumes(project_id, intersection_id, _cache)
    short_window = window < MIN_BALANCE_WINDOW_SEC
    trimmed = _has_peak_trims(project_id, intersection_id)
    n_blocks = _coverage_blocks(project_id, intersection_id)
    if trimmed:
        not_applicable = ("declared trims = a peak-window claim — "
                          "directional peaking is expected; informational only")
    elif n_blocks > 1:
        not_applicable = (f"coverage is {n_blocks} disjoint peak blocks — "
                          "directional peaking is expected; informational only")
    elif short_window:
        not_applicable = (f"window {window/3600:.1f}h < "
                          f"{MIN_BALANCE_WINDOW_SEC/3600:.0f}h — directional "
                          f"peaking dominates short windows; informational only")
    else:
        not_applicable = None
    short_window = not_applicable is not None
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
        "note": not_applicable,
        "pairs": pairs,
    }


def _directional_io(project_id: str, intersection_id: int,
                    _cache: dict | None = None) -> dict:
    """Per-position IN/OUT totals for one intersection.

    Cardinal is the leg POSITION, so it already IS the compass side: origin
    cardinal 'S' = a vehicle arriving FROM the south arm; dest cardinal 'N' =
    one leaving via the north arm. Keyed by that side: out['N'] = vehicles
    leaving northward; in_['S'] = vehicles arriving from the south."""
    vols, window = _cardinal_volumes(project_id, intersection_id, _cache)
    out = defaultdict(int)
    in_ = defaultdict(int)
    for (a, b), n in vols.items():
        in_[a] += n    # origin cardinal = position = the side it came from
        out[b] += n    # dest cardinal = position = the side it left toward
    return {"in": dict(in_), "out": dict(out), "window_seconds": window}


def corridor_consistency(project_id: str, ordered_intersections: list[int],
                         axis: str = "NS", _cache: dict | None = None) -> dict:
    """3.2 — between-intersection flow conservation along a corridor.

    ordered_intersections: intersection_ids in geographic order, FIRST =
    southernmost (axis 'NS') or westernmost (axis 'EW'). For each adjacent
    pair (A south of B): A.out_north ~ B.in_south and B.out_south ~ A.in_north.
    Mid-block access (driveways/side streets) shows up as a consistent signed
    residual — a few % is normal, large gaps implicate counting."""
    up, down = ("N", "S") if axis.upper() == "NS" else ("E", "W")
    io = {iid: _directional_io(project_id, iid, _cache) for iid in ordered_intersections}
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
