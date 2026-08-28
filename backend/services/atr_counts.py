"""ATR — screenline crossing counts (the midblock tube-count product).

Plan: Deliver+ATR Part 2 (2026-08-28); charter
docs/product_gap_tmc_atr_2026-08-23.md. A midblock site is an
intersection with leg_count=2 whose legs carry operator-drawn
gate_segment screenlines. Counting composes EXISTING primitives only
(dump rows -> build_gates(leg_gates=drawn) -> all_crossings) and never
touches the turn-attribution pipeline or vehicle_events — the
degenerate 2-leg derive_movement branch is structurally unreachable.

KNOWN HAZARD handled here: pass-2's twin dedup never runs (ATR is
pass-1 only), so coexisting twin tracks would double-count a crossing.
Crossings are deduped: same gate, same direction, within
TWIN_CROSS_WINDOW_S and STITCH_STAT_DIST = one vehicle.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

from backend.services.track_chains import STITCH_STAT_DIST

TWIN_CROSS_WINDOW_S = 1.0
MIN_TRACK_POINTS = 5
CLASS_GROUPS = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def dedup_crossings(events):
    """Crossing-level twin dedup (pure): same gate, same direction,
    within TWIN_CROSS_WINDOW_S and STITCH_STAT_DIST = one physical
    vehicle. events = [(t_s, leg, inward, (x, y), class_group)].
    Returns (kept [(t, leg, inward, group)], n_dropped)."""
    events = sorted(events, key=lambda e: e[0])
    kept = []
    recent: dict[tuple, list] = defaultdict(list)
    dropped = 0
    for t, leg, inward, pos, group in events:
        key = (leg, inward)
        recent[key] = [(rt, rp) for rt, rp in recent[key]
                       if t - rt <= TWIN_CROSS_WINDOW_S]
        if any(math.hypot(pos[0] - rp[0], pos[1] - rp[1])
               <= STITCH_STAT_DIST for _rt, rp in recent[key]):
            dropped += 1
            continue
        recent[key].append((t, pos))
        kept.append((t, leg, inward, group))
    return kept, dropped


def count_screenline_crossings(project_id: str, camera_id: int,
                               variant: str,
                               bin_minutes: int = 15) -> dict | None:
    """Directional screenline counts for one dump window.

    Returns {"bins": [{start(iso), label, counts: {"legid:in"/":out": n},
    classes: {...}}], "legs": {leg_id: label}, "totals": {...},
    "window": [t_lo_iso, t_hi_iso], "crossings_deduped": n} or None
    when the dump/gates are missing.
    """
    import numpy as np

    from backend.database import get_connection, leg_geometry_for_camera
    from backend.database import list_paths_for_camera
    from backend.services.detection_cache import (
        parquet_path, resolve_content_hash)
    from backend.services.entry_gates import all_crossings, build_gates
    from backend.services.pass2_replay import load_dump, tracks_dir

    conn = get_connection(project_id)
    try:
        vid = conn.execute(
            "SELECT content_hash, fps, recording_start_datetime, path "
            "FROM videos WHERE camera_id = ? ORDER BY sort_order LIMIT 1",
            (camera_id,)).fetchone()
        if vid is None:
            return None
        fps = float(vid[1] or 10.0)
        rec_start = datetime.fromisoformat(vid[2])
        legs = {int(r[0]): r[1] for r in conn.execute(
            "SELECT leg_id, label FROM legs WHERE camera_id = ?",
            (camera_id,))}
    finally:
        conn.close()
    chash = vid[0] or resolve_content_hash(project_id, camera_id, vid[3])
    if not chash:
        return None

    geom = leg_geometry_for_camera(project_id, camera_id)
    mouths = {lid: g["mouth"] for lid, g in geom.items() if g.get("mouth")}
    heads = {lid: g.get("heading") for lid, g in geom.items()}
    drawn = {lid: g["gate"] for lid, g in geom.items() if g.get("gate")}
    if not drawn:
        return None                      # a screenline is the product
    gates = build_gates(mouths, list_paths_for_camera(project_id,
                                                      camera_id),
                        heads, leg_gates=drawn)

    td = tracks_dir(parquet_path(project_id, camera_id, chash, variant))
    from pathlib import Path
    if not (Path(td) / "meta.json").exists():
        return None
    rows = load_dump(td)

    tracks: dict[int, list] = defaultdict(list)
    classes: dict[int, list] = defaultdict(list)
    for r in rows:
        tid = int(r[0])
        tracks[tid].append((float(r[1]), float(r[2]), float(r[3])))
        classes[tid].append(int(r[7]) if len(r) > 7 else 2)

    # every crossing of a DRAWN gate, direction-bearing
    events = []   # (t_seconds, leg_id, inward, pos, class_group)
    for tid, pts in tracks.items():
        if len(pts) < MIN_TRACK_POINTS:
            continue
        cls_counts = defaultdict(int)
        for c in classes[tid]:
            cls_counts[c] += 1
        cls = max(cls_counts, key=cls_counts.get)
        group = CLASS_GROUPS.get(cls, "car")
        for f, leg, inward, pos in all_crossings(sorted(pts), gates, fps):
            if leg not in drawn:
                continue                 # only operator screenlines count
            events.append((f / fps, int(leg), bool(inward), pos, group))

    kept, dropped = dedup_crossings(events)

    if not kept:
        return {"bins": [], "legs": legs, "totals": {},
                "window": None, "crossings_deduped": dropped}

    # wall-clock bins, INCLUDING zero bins across the window
    t_lo = min(t for t, *_ in kept)
    t_hi = max(t for t, *_ in kept)
    bin_s = bin_minutes * 60
    wc_lo = rec_start + timedelta(seconds=t_lo)
    wc_lo = wc_lo.replace(minute=(wc_lo.minute // bin_minutes)
                          * bin_minutes, second=0, microsecond=0)
    bins = []
    totals: dict[str, int] = defaultdict(int)
    cur = wc_lo
    wc_hi = rec_start + timedelta(seconds=t_hi)
    while cur <= wc_hi:
        nxt = cur + timedelta(seconds=bin_s)
        counts: dict[str, int] = defaultdict(int)
        cls_counts: dict[str, int] = defaultdict(int)
        for t, leg, inward, group in kept:
            wc = rec_start + timedelta(seconds=t)
            if cur <= wc < nxt:
                key = f"{leg}:{'in' if inward else 'out'}"
                counts[key] += 1
                cls_counts[group] += 1
                totals[key] += 1
        bins.append({"start": cur.isoformat(),
                     "label": cur.strftime("%H:%M"),
                     "counts": dict(counts),
                     "classes": dict(cls_counts),
                     "total": sum(counts.values())})
        cur = nxt
    return {"bins": bins, "legs": legs, "totals": dict(totals),
            "window": [(rec_start + timedelta(seconds=t_lo)).isoformat(),
                       (rec_start + timedelta(seconds=t_hi)).isoformat()],
            "crossings_deduped": dropped,
            "bin_minutes": bin_minutes}
