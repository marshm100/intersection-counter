"""Gap-card line items — machine-proposed candidates for one flag's bin.

Operator spec (2026-08-24, R0 instrument v2,
docs/diag_lock_demo_review_2026-08-24.md lineage): a gap card must arrive
as a closed-ended LIST — specific tracked-but-uncounted vehicles, each
cued to its exact moment — not an open scrub canvas over a 15-minute bin.

This composes existing primitives READ-ONLY: track_overlay's mmap'd dump
access, the bucket_tracks counted-set join (v2_a3_split precedent),
entry_gates.classify over gates built from the camera's live geometry
(drawn gates verbatim when present). It NEVER auto-adds: items are
proposals and the human rules each one — the G-QD-1 standing law (the
eventless population measured 17/17 splices when auto-added; a human
with the live box is the designed remedy, plan_a3_split G-A3-3).
"""
from __future__ import annotations

import sqlite3

import numpy as np

from backend.database import (
    get_connection, leg_geometry_for_camera, list_paths_for_camera,
)
from backend.services.cardinals import bound_approach
from backend.services.entry_gates import build_gates, classify
from backend.services.track_chains import _end_speed
from backend.services.track_cut import FALLBACK_KIN, cut_track
from backend.services.track_overlay import _load, _resolve_variant
from backend.services.trajectory_classifier import derive_movement

PAD_SECONDS = 5.0        # bin edges are soft: tracks straddle them
MIN_POINTS = 5           # MIN_SEG_PTS — below this a track can't classify
SPEED_FLOOR_PXS = 25.0   # the QD floor: drop parked/jitter tracks
MAX_ITEMS = 60           # a card is workable, not infinite; count reported

# Operator ruling (2026-08-24, round 1: "all bad tracks — thieves or
# lingering on idle left-turners... the mouth and gate infrastructure is
# not working properly"): a gate crossing qualifies a CANDIDATE only if
# the vehicle was IN MOTION through the line — queue creep across a gate
# is not a journey. 10 px/s is the frozen stationary threshold
# (STITCH_STAT_SPEED_PXS).
CROSS_MOTION_MIN_PXS = 10.0


def _crossing_speed(pts, f):
    """Local speed (px/s equivalent per-frame basis) at frame f."""
    import math
    for i in range(len(pts) - 1):
        if pts[i][0] <= f <= pts[i + 1][0]:
            dfr = pts[i + 1][0] - pts[i][0]
            if dfr <= 0:
                return 0.0
            return math.hypot(pts[i + 1][1] - pts[i][1],
                              pts[i + 1][2] - pts[i][2]) / dfr
    return 0.0


def items_for_flag(project_id: str, flag: dict) -> dict:
    """Candidate line items for one suspected_gap flag.

    Returns {"variant", "items": [...], "n_eventless", "capped"}. Each
    item: {tid, origin_leg_id, destination_leg_id, movement, tag,
    t_first, t_cross, x, y} — times in video seconds, cued to the
    entry-gate crossing when the track has one.
    """
    cam = flag.get("camera_id")
    t_lo = flag.get("interval_start_seconds")
    t_hi = flag.get("interval_end_seconds")
    approach = (flag.get("approach") or "").upper()
    if cam is None or t_lo is None or t_hi is None:
        return {"variant": None, "items": [], "n_eventless": 0,
                "capped": False}

    variant = _resolve_variant(project_id, cam, None, t_lo, t_hi)
    if variant is None:
        return {"variant": None, "items": [], "n_eventless": 0,
                "capped": False}
    entry = _load(project_id, cam, variant)
    if entry is None:
        return {"variant": variant, "items": [], "n_eventless": 0,
                "capped": False}

    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    try:
        fps_row = conn.execute(
            "SELECT fps FROM videos WHERE camera_id = ? ORDER BY sort_order "
            "LIMIT 1", (cam,)).fetchone()
        fps = float(fps_row[0]) if fps_row and fps_row[0] else entry["fps"]

        lo = int(np.searchsorted(entry["frames"], (t_lo - PAD_SECONDS) * fps,
                                 side="left"))
        hi = int(np.searchsorted(entry["frames"], (t_hi + PAD_SECONDS) * fps,
                                 side="right"))
        sl = np.asarray(entry["rows"][lo:hi])
        if not len(sl):
            return {"variant": variant, "items": [], "n_eventless": 0,
                    "capped": False}

        # counted / rejected event tracks in the padded bin (the
        # bucket_tracks join — rejected tracks were rejected correctly
        # and are NOT re-proposed)
        kept, rej = set(), set()
        for tid, r in conn.execute(
                "SELECT vehicle_track_id, COALESCE(rejected,0) FROM "
                "vehicle_events WHERE camera_id=? AND timestamp_video>=? "
                "AND timestamp_video<? AND vehicle_track_id IS NOT NULL",
                (cam, t_lo - PAD_SECONDS, t_hi + PAD_SECONDS)):
            (kept if r == 0 else rej).add(int(tid))

        geom = leg_geometry_for_camera(project_id, cam)
        legs_full = {int(r["leg_id"]): dict(r) for r in conn.execute(
            "SELECT * FROM legs WHERE camera_id = ?", (cam,))}
    finally:
        conn.close()

    mouths = {lid: g["mouth"] for lid, g in geom.items() if g.get("mouth")}
    heads = {lid: g.get("heading") for lid, g in geom.items()}
    drawn = {lid: g["gate"] for lid, g in geom.items() if g.get("gate")}
    if not mouths:
        return {"variant": variant, "items": [], "n_eventless": 0,
                "capped": False}
    gates = build_gates(mouths, list_paths_for_camera(project_id, cam),
                        heads, leg_gates=drawn or None)

    by_tid: dict[int, list] = {}
    for r in sl:
        by_tid.setdefault(int(r[0]), []).append(
            (float(r[1]), float(r[2]), float(r[3])))

    n_eventless = 0
    items = []
    all_legs = list(legs_full.values())
    for tid, pts in by_tid.items():
        if len(pts) < MIN_POINTS or tid in kept or tid in rej:
            continue
        n_eventless += 1
        pts = sorted(pts)
        if _end_speed(pts) * fps < SPEED_FLOOR_PXS:
            continue
        o, d, of, df, op, dp, tag = classify(pts, gates, fps)
        if tag not in ("full", "entry_only") or o is None:
            continue
        card = (legs_full.get(int(o)) or {}).get("cardinal_direction")
        if approach and bound_approach(card) != approach:
            continue
        # MOTION-QUALIFIED crossings (operator ruling): entry creep-
        # crossings below the stationary threshold do not make a
        # candidate — the dwell/u-turn debris class dies here.
        if of is not None and (_crossing_speed(pts, of) * fps
                               < CROSS_MOTION_MIN_PXS):
            continue
        if (tag == "full" and df is not None
                and (_crossing_speed(pts, df) * fps
                     < CROSS_MOTION_MIN_PXS)):
            tag = "entry_only"        # exit was a creep — not evidence
            d = None
        # THIEF SIGNATURE (the validated cutter, fallback kin): a
        # flip-at-speed inside the track = it reads like a splice. Not
        # hidden — proposed WITH the label so the operator's T is a
        # one-glance confirmation, never a diagnosis.
        suspect = None
        try:
            _segs, recs = cut_track(pts, gates, fps, dict(FALLBACK_KIN))
            if any(r[1].get("rule") == "flip_at_speed" for r in recs):
                suspect = "thief"
        except Exception:
            pass
        movement = None
        if tag == "full" and d is not None:
            movement = derive_movement(legs_full[int(o)],
                                       legs_full.get(int(d)), all_legs)
        pos = op or dp or (pts[0][1], pts[0][2])
        cross_f = of if of is not None else pts[0][0]
        items.append({
            "suspect": suspect,
            "tid": tid,
            "origin_leg_id": int(o),
            "destination_leg_id": int(d) if d is not None else None,
            "movement": movement,
            "tag": tag,
            "t_first": round(pts[0][0] / fps, 2),
            "t_last": round(pts[-1][0] / fps, 2),
            "t_cross": round(float(cross_f) / fps, 2),
            "x": round(float(pos[0]), 1),
            "y": round(float(pos[1]), 1),
        })

    items.sort(key=lambda i: i["t_cross"])
    capped = len(items) > MAX_ITEMS
    return {"variant": variant, "items": items[:MAX_ITEMS],
            "n_eventless": n_eventless, "capped": capped}
