"""Turn-fragment merge mechanics + twin-track dedup + bank expecteds.

The production turn merge and its S5 merge_borderline flag were deleted
2026-11-20: the tracklet linker joins fragments, so no merge runs in pass 2.
`merge_turn_fragments` and `borderline_merge_cells` stay ONLY because the
offline recipe scripts/hybrid_ocbot.py re-imports them; `twin_track_dedup`
and `bank_expecteds` are live.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

TURNS = ("left", "right", "u_turn")
# Frozen constants (hybrid_ocbot defaults; cam2-validated, blind-swept).
MERGE_PX = 30.0
MERGE_GAP = 40.0
VOL_FACTOR = 1.3
FALLBACK_SAMPLE_SECONDS = 1800.0   # corridor banks were 30-min samples
# Queue-aware merge (counted-path A, 2026-08-27): real fragments of ONE
# vehicle occupy near-disjoint time spans — a vehicle is one track at a
# time, and fragments micro-overlap only at a handoff. Queue successors
# COEXIST for seconds (the next car is born at the same queue-tail
# pixel while the dweller still lives), which is how the merge ate
# genuine vehicles in exactly the deficit cells (177 SB_right
# merged-away vs a 141-vehicle deficit at 0700). Frames, matching
# MERGE_GAP's unit convention (~0.5 s at 25 fps).
MERGE_MAX_OVERLAP_FRAMES = 12.0


def merge_turn_fragments(turns, merge_px, merge_gap, expected_by_cell=None,
                         vol_factor=1.3, queue_aware=False, excess_only=False,
                         pairs_out=None, max_overlap=MERGE_MAX_OVERLAP_FRAMES):
    """Ported verbatim from scripts/hybrid_ocbot.py (see its docstring for the
    A2 volume-gate rationale). `turns` = dicts with id/ol/dl/mv/s/e/start.
    queue_aware adds the span-overlap discriminator (see
    MERGE_MAX_OVERLAP_FRAMES). Returns the kept event ids.

    excess_only (config.MERGE_EXCESS_ONLY): a cell over its gate gives up
    only its EXCESS over the gate — the predicate loop runs unchanged, its
    absorptions are ranked by strength (start_dist / merge_px + gap /
    merge_gap, normalised by the frozen constants) and only the strongest
    (len(cell) - floor(gate)) are applied. Removes the all-or-nothing cliff.
    pairs_out, when a list, receives every absorption as a dict (root,
    absorbed, strength, applied) — diagnostics only."""
    by = defaultdict(list)
    for ev in turns:
        by[(ev["ol"], ev["dl"], ev["mv"])].append(ev)
    keep = []
    for cell, evs in by.items():
        evs.sort(key=lambda e: e["s"])
        excess = None
        if expected_by_cell is not None:
            exp = expected_by_cell.get((cell[0], cell[1]), 0)
            gate = vol_factor * max(exp, 1)
            if len(evs) <= gate:
                keep.extend(e["id"] for e in evs)
                continue
            if excess_only:
                excess = len(evs) - math.floor(gate)
        absorbed = []
        used = [False] * len(evs)
        for i, ei in enumerate(evs):
            if used[i]:
                continue
            used[i] = True
            keep.append(ei["id"])
            if ei["start"] is None:
                continue
            for j in range(i + 1, len(evs)):
                ej = evs[j]
                if used[j] or ej["start"] is None:
                    continue
                if (ej["s"] - ei["e"]) <= merge_gap and math.hypot(
                        ei["start"][0] - ej["start"][0],
                        ei["start"][1] - ej["start"][1]) <= merge_px:
                    if queue_aware:
                        overlap = (min(ei["e"], ej["e"])
                                   - max(ei["s"], ej["s"]))
                        if overlap > max_overlap:
                            continue   # coexisting = two vehicles, keep
                    used[j] = True   # fragment of the same turning vehicle
                    dist = math.hypot(ei["start"][0] - ej["start"][0],
                                      ei["start"][1] - ej["start"][1])
                    gap = max(ej["s"] - ei["e"], 0.0)
                    absorbed.append((dist / merge_px + gap / merge_gap,
                                     ei["id"], ej["id"]))
        applied = absorbed
        if excess is not None and len(absorbed) > excess:
            ranked = sorted(absorbed, key=lambda a: a[0])
            applied = ranked[:max(excess, 0)]
            done = {a[2] for a in applied}
            keep.extend(a[2] for a in absorbed if a[2] not in done)
        if pairs_out is not None:
            done = {a[2] for a in applied}
            pairs_out.extend({"cell": list(cell), "root": a[1],
                              "absorbed": a[2], "strength": round(a[0], 4),
                              "applied": a[2] in done} for a in absorbed)
    return set(keep)


def borderline_merge_cells(turns, expected_by_cell, vol_factor=1.3,
                           band=0.2) -> list[dict]:
    """S5 — cells whose raw fragment count sits within ±band of the volume-gate
    threshold (the noise-sensitive merge decisions). Ported verbatim."""
    raw = Counter((ev["ol"], ev["dl"]) for ev in turns)
    out = []
    for cell, n in raw.items():
        exp = (expected_by_cell or {}).get(cell)
        if not exp:
            continue
        thr = vol_factor * max(exp, 1)
        if thr * (1 - band) <= n <= thr * (1 + band):
            out.append({"cell": cell, "raw": n, "expected": exp,
                        "threshold": round(thr, 1),
                        "merges": n > thr})
    return out


# Counted-path C2 (operator scenes 1-2, anatomy measured 2026-08-27):
# COEXISTING TWINS — two simultaneous tracks on one vehicle (spawned
# together at a queue; one dies early, the other carries on), BOTH
# minting events. Not the sequential stop-fracture (that class collapses
# at the dump) and invisible to the turn merge (births can sit > 30 px
# apart and the spans overlap — which the queue-aware predicate now
# rightly protects). The identity test is per-frame: the twin RIDES the
# same vehicle, so its boxes overlap the survivor's frame by frame.
TWIN_OVERLAP_FRAC = 0.6   # common span >= this fraction of the shorter life
TWIN_IOU_MIN = 0.2        # median per-frame box IoU over common frames
                          # (boxes on ONE vehicle overlap; queue neighbors
                          # never do — their IoU is ~0 at any distance)


def twin_track_dedup(db: str | Path, camera_id: int, rows, fps) -> dict:
    """Reject the shorter event of every coexisting-twin pair. Pure
    identity test on the dump rows (tid, frame, cx, cy, bw, bh, ...):
    spans overlap >= TWIN_OVERLAP_FRAC of the shorter track's life,
    median common-frame center distance <= STITCH_STAT_DIST, median
    common-frame IoU >= TWIN_IOU_MIN. Write-then-reject (rejected=1,
    reviewable), matching the merge semantics. Movement-agnostic:
    one vehicle is one count regardless of how the twin classified."""
    import numpy as np

    from backend.services.track_chains import STITCH_STAT_DIST

    db = str(db)
    conn = sqlite3.connect(db)
    try:
        evs = conn.execute(
            "SELECT event_id, vehicle_track_id, start_frame, frame_number "
            "FROM vehicle_events WHERE camera_id = ? AND rejected = 0 "
            "AND vehicle_track_id IS NOT NULL AND vehicle_track_id >= 0",
            (camera_id,)).fetchall()
        arr = np.asarray(rows)
        by_tid = {}
        for eid, tid, sf, ef in evs:
            if tid not in by_tid:
                sel = arr[arr[:, 0] == float(tid)]
                if not len(sel):
                    continue
                sel = sel[np.argsort(sel[:, 1])]
                by_tid[tid] = sel
        ev_list = [(eid, tid, by_tid[tid]) for eid, tid, _sf, _ef in evs
                   if tid in by_tid]
        ev_list.sort(key=lambda e: e[2][0, 1])
        drop = set()
        n_pairs = 0
        for i, (ei, ti, ai) in enumerate(ev_list):
            if ei in drop:
                continue
            i0, i1 = ai[0, 1], ai[-1, 1]
            for ej, tj, aj in ev_list[i + 1:]:
                if ej in drop or tj == ti:
                    continue
                j0, j1 = aj[0, 1], aj[-1, 1]
                if j0 > i1:
                    break
                ov = min(i1, j1) - max(i0, j0)
                short_len = min(i1 - i0, j1 - j0)
                if short_len <= 0 or ov < TWIN_OVERLAP_FRAC * short_len:
                    continue
                lo, hi = max(i0, j0), min(i1, j1)
                si = ai[(ai[:, 1] >= lo) & (ai[:, 1] <= hi)]
                sj = aj[(aj[:, 1] >= lo) & (aj[:, 1] <= hi)]
                common, ii, jj = np.intersect1d(
                    si[:, 1], sj[:, 1], return_indices=True)
                if len(common) < 5:
                    continue
                pi, pj = si[ii], sj[jj]
                d = np.hypot(pi[:, 2] - pj[:, 2], pi[:, 3] - pj[:, 3])
                if np.median(d) > STITCH_STAT_DIST:
                    continue
                x1 = np.maximum(pi[:, 2] - pi[:, 4] / 2, pj[:, 2] - pj[:, 4] / 2)
                x2 = np.minimum(pi[:, 2] + pi[:, 4] / 2, pj[:, 2] + pj[:, 4] / 2)
                y1 = np.maximum(pi[:, 3] - pi[:, 5] / 2, pj[:, 3] - pj[:, 5] / 2)
                y2 = np.minimum(pi[:, 3] + pi[:, 5] / 2, pj[:, 3] + pj[:, 5] / 2)
                inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
                a_i = pi[:, 4] * pi[:, 5]
                a_j = pj[:, 4] * pj[:, 5]
                iou = inter / np.maximum(a_i + a_j - inter, 1e-6)
                if np.median(iou) < TWIN_IOU_MIN:
                    continue
                # one vehicle, two events: the shorter track is the twin
                victim = ej if (j1 - j0) <= (i1 - i0) else ei
                drop.add(victim)
                n_pairs += 1
                if victim == ei:
                    break
        with conn:
            conn.executemany(
                "UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?",
                [(int(e),) for e in drop])
    finally:
        conn.close()
    return {"camera_id": camera_id, "twin_pairs": n_pairs,
            "twin_rejected": len(drop)}


def _load_turns(conn: sqlite3.Connection, camera_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT event_id, movement, origin_leg_id, destination_leg_id, "
        "start_frame, frame_number, trajectory_data FROM vehicle_events "
        "WHERE camera_id = ? AND rejected = 0 AND movement IN (?,?,?)",
        (camera_id, *TURNS)).fetchall()
    out = []
    for eid, mv, ol, dl, sf, ef, tj in rows:
        try:
            traj = json.loads(tj) if tj else []
        except Exception:
            traj = []
        s = sf if sf is not None else ef
        e = ef if ef is not None else sf
        out.append({"id": eid, "mv": mv, "ol": ol, "dl": dl, "s": s, "e": e,
                    "start": traj[0] if traj else None})
    return out


def bank_expecteds(conn: sqlite3.Connection, camera_id: int,
                   window_seconds: float) -> dict[tuple, float]:
    """{(origin,dest): expected count over window_seconds} from the applied
    bank's supporting_count, time-scaled by each path's sample window."""
    out: dict[tuple, float] = {}
    for o, d, sc, sw in conn.execute(
            "SELECT origin_leg_id, destination_leg_id, supporting_count, "
            "sample_window_seconds FROM intersection_paths WHERE camera_id = ?",
            (camera_id,)):
        if sw is None:
            logger.warning(
                "intersection_paths cam%s (%s->%s): sample_window_seconds is "
                "NULL — assuming %ss (legacy 30-min sample bank)",
                camera_id, o, d, FALLBACK_SAMPLE_SECONDS)
            sw = FALLBACK_SAMPLE_SECONDS
        out[(o, d)] = float(sc) * (window_seconds / float(sw))
    return out
