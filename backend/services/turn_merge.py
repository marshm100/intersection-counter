"""Production turn-fragment merge + S5 borderline signal (A4a,
docs/plan_A4_stage3_2026-07-10.md).

BoT/ByteTrack fragment one turning vehicle into several same-cell events (the
tracker coasts the sharp curve, the pipeline finalizes the stub, the exit
re-tracks). `merge_turn_fragments` collapses same-(origin,dest,movement)
events that start within merge_px of each other within merge_gap frames —
guarded by the VOLUME GATE: only cells whose raw count clearly exceeds
expectation merge at all, so sparse well-counted cells can't lose distinct
vehicles. Mechanism and constants ported VERBATIM from scripts/hybrid_ocbot.py
(the validated offline recipe; scripts re-import from here).

The expecteds are GT-FREE: the applied bank's supporting_count per (origin,
dest), scaled to the counting window via sample_window_seconds (blind gate,
validated 2026-07-08 — the honest cam1 cost was 10.0% vs 6.7% GT-gated, and
Miovision appears nowhere).

`borderline_merge_cells` is the S5 flag-queue signal: a cell whose raw count
sits within ±band of the gate threshold is one noise-vehicle from the merge
decision flipping (cam1 NB-left blind: 134 raw vs threshold 143 → no merge →
+38 shipped). Only computable HERE, where raw pre-merge counts exist.
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
                         pairs_out=None):
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
                        if overlap > MERGE_MAX_OVERLAP_FRAMES:
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


def bound_chain_recs(rows, fps, gates):
    """Per-track chain records for the tracks in `rows`, tagged the way the
    COUNTING DEFAULT tags them.

    track_chains.build_chain_map_ev tags with centre-point classify(); the
    counting default has used the JOURNEY STATE MACHINE (both bottom corners,
    exit terminal) since 2026-09-10 and the two disagree — a track the
    pipeline calls entry_only can read 'full' under centre points, which
    blocks the chain that should have formed. Measured on the gx1 arm DBs:
    feeding the state-machine tags took the guard from 42 to 66 rejections on
    cam1 study_0700 while cam4 stayed at 0. So mirror pipeline._gate_evidence:
    bottom corners (cx +- w/2, cy + h/2) through classify_pair when the
    machine is on, centre points through classify when it is off.
    """
    import numpy as np

    from backend.config import JOURNEY_STATE_MACHINE
    from backend.services.entry_gates import classify, classify_pair
    from backend.services.track_chains import _end_speed, endpoint_bearings

    arr = np.asarray(rows, dtype=float)
    arr = arr[np.lexsort((arr[:, 1], arr[:, 0]))]
    uniq, starts = np.unique(arr[:, 0], return_index=True)
    ends = np.append(starts[1:], len(arr))
    recs = []
    for tid, a, b in zip(uniq, starts, ends):
        sel = arr[a:b]
        if len(sel) < 5:
            continue                       # the chain map's own floor
        pts = [(float(r[1]), float(r[2]), float(r[3])) for r in sel]
        if JOURNEY_STATE_MACHINE:
            left = [(float(r[1]), float(r[2]) - float(r[4]) / 2.0,
                     float(r[3]) + float(r[5]) / 2.0) for r in sel]
            right = [(float(r[1]), float(r[2]) + float(r[4]) / 2.0,
                      float(r[3]) + float(r[5]) / 2.0) for r in sel]
            tag = classify_pair(left, right, gates, fps)[6]
        else:
            tag = classify(pts, gates, fps)[6]
        bs, be = endpoint_bearings(pts, fps)
        recs.append({"tid": int(tid), "birth": pts[0], "death": pts[-1],
                     "tag": tag, "v_end": _end_speed(pts) * fps,
                     "b_start": bs, "b_end": be})
    return recs


def bound_chain_pairs(evs, rows, fps, gates):
    """THE BOUND-CHAIN CONSERVATION GUARD's selection, side-effect free.

    `evs`: [(event_id, track_id, posterior_source)] of the unrejected events
    in play. Returns (chain_map, drop) where drop is the set of event ids to
    reject: the G-EX-2 BOUND events (posterior_source 'rescue_exit') whose
    fragment chain ALREADY holds another counted event.

    The chaining itself is track_chains.chain_tracks, UNMODIFIED and with
    every constant untouched. It already encodes exactly this pairing — its
    tag gate is A_OK = (entry_only, no_crossing) -> B_OK = (exit_only,
    no_crossing), i.e. a head that never exited followed by a tail that never
    entered, which is one vehicle in two pieces; its moving-break window is
    STITCH_MOVE_GAP_S = (-0.48, 3.0) s, commented "occlusion break mid-box",
    within STITCH_MOVE_DIST = 70 px; and a box-full journey may never chain
    (the dedup-ceiling lesson). Measured independently before that module was
    read: cam1's real pairs sit at gap p10 -0.20 / p50 0.85 s. The July
    constants and the September measurement agree, so this guard adds none.
    """
    from backend.services.track_chains import chain_tracks

    bound = {int(t): int(e) for e, t, s in evs if s == "rescue_exit"}
    counted = {int(t): int(e) for e, t, _s in evs}
    if not bound:
        return {}, set()
    chain_map: dict[int, int] = {}
    members: dict[int, list] = {}
    for i, chain in enumerate(chain_tracks(bound_chain_recs(rows, fps, gates),
                                           fps)):
        for r in chain:
            chain_map[r["tid"]] = i
            if r["tid"] in counted:
                members.setdefault(i, []).append(r["tid"])
    drop = set()
    for tid, eid in bound.items():
        cid = chain_map.get(tid)
        if cid is None:
            continue
        if any(other != tid for other in members.get(cid, ())):
            drop.add(eid)
    return chain_map, drop


def bound_chain_dedup(db: str | Path, camera_id: int, rows, fps,
                      gates) -> dict:
    """THE BOUND-CHAIN CONSERVATION GUARD (config.BOUND_CHAIN_CONSERVE):
    one vehicle is one count, applied to the journeys G-EX-2 binds.

    G-EX-2 counts a track whose EXIT was observed. On a fragmenting camera
    that track is often the tail half of a vehicle whose head half — witnessed
    entering, never exiting — was already counted, so the vehicle lands twice.
    Measured on arm gx1: of cam1 study_0700's 219 bound events, 95 have an
    already-counted entry_only track dying within 1.5 box lengths of their
    birth; on cam4 study_1100, 4 of 219. cams 1-3 run BoT-SORT recipes with no
    recovery tracker and fragment; cam4/cam5 hold one track per vehicle.

    SCOPE, and the reason this cannot cost a legacy vehicle: the pass may only
    ever reject rows whose posterior_source is 'rescue_exit'. Its worst case
    is reverting part of what G-EX-2 added. Write-then-reject (rejected=1),
    so every drop stays reviewable in the worklist.
    """
    db = str(db)
    conn = sqlite3.connect(db)
    try:
        evs = conn.execute(
            "SELECT event_id, vehicle_track_id, COALESCE(posterior_source, '') "
            "FROM vehicle_events "
            "WHERE camera_id = ? AND COALESCE(rejected, 0) = 0 "
            "AND vehicle_track_id IS NOT NULL AND vehicle_track_id >= 0",
            (camera_id,)).fetchall()
        n_bound = sum(1 for _e, _t, s in evs if s == "rescue_exit")
        _cm, drop = bound_chain_pairs(evs, rows, fps, gates)
        with conn:
            conn.executemany(
                "UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?",
                [(int(e),) for e in drop])
    finally:
        conn.close()
    return {"camera_id": camera_id, "bound_events": n_bound,
            "bound_rejected": len(drop)}


def fracture_pairs(evs, rows, fps, gates):
    """The FRACTURE RULE's pairing, side-effect free. evs: [(event_id,
    track_id)] of the events in play. Returns (recs, pairs) with pairs
    = [(a_rec, b_rec, victim_rec, gap_s, dist_over_box)]."""
    import numpy as np

    from backend.config import FRACTURE_DIST_BOXES, FRACTURE_GAP_S
    from backend.services.entry_gates import classify
    from backend.services.track_chains import (CHAIN_DIR_TOL_DEG,
                                               endpoint_bearings)
    from backend.services.track_cut import _bdiff

    arr = np.asarray(rows, dtype=float)
    recs = []
    for eid, tid in evs:
        sel = arr[arr[:, 0] == float(tid)]
        if len(sel) < 5:
            continue
        sel = sel[np.argsort(sel[:, 1])]
        pts = [(float(r[1]), float(r[2]), float(r[3])) for r in sel]
        *_o, tag = classify(pts, gates, fps)
        bs, be = endpoint_bearings(pts, fps)
        recs.append({"eid": eid, "tid": int(tid), "pts": pts,
                     "birth": pts[0], "death": pts[-1],
                     "span": pts[-1][0] - pts[0][0], "tag": tag,
                     "box": float(np.median(np.maximum(sel[:, 4],
                                                       sel[:, 5]))),
                     "b_start": bs, "b_end": be})
    recs.sort(key=lambda r: r["birth"][0])
    births = np.array([r["birth"][0] for r in recs], dtype=float)
    cands = []
    for ai, a in enumerate(recs):
        if a["tag"] not in ("entry_only", "no_crossing"):
            continue                       # A already owns its exit
        fa, xa, ya = a["death"]
        lo = int(np.searchsorted(births, fa, side="right"))
        hi = int(np.searchsorted(births, fa + FRACTURE_GAP_S * fps,
                                 side="right"))
        for bi in range(lo, hi):
            b = recs[bi]
            if b["tid"] == a["tid"] or b["death"][0] <= fa:
                continue
            gap_s = (b["birth"][0] - fa) / fps
            dist = math.hypot(b["birth"][1] - xa, b["birth"][2] - ya)
            box = max(1.0, (a["box"] + b["box"]) / 2.0)
            if dist > FRACTURE_DIST_BOXES * box:
                continue
            ba, bb = a.get("b_end"), b.get("b_start")
            if (ba is not None and bb is not None
                    and _bdiff(ba, bb) > CHAIN_DIR_TOL_DEG):
                continue
            cands.append((dist / box + 0.5 * gap_s, ai, bi, gap_s,
                          dist / box))
    cands.sort(key=lambda c: c[0])
    used = set()
    pairs = []
    for _s, ai, bi, gap_s, rel in cands:
        if ai in used or bi in used:
            continue
        used.add(ai); used.add(bi)
        a, b = recs[ai], recs[bi]
        # the shorter track is the fragment; on a tie the earlier one
        victim = a if a["span"] <= b["span"] else b
        pairs.append((a, b, victim, gap_s, rel))
    return recs, pairs


def fracture_track_dedup(db: str | Path, camera_id: int, rows, fps,
                         gates) -> dict:
    """THE FRACTURE RULE (config.FRACTURE_DEDUP): reject the shorter
    event of every drop-and-recapture pair. A pair is track A dying
    and track B being born within FRACTURE_GAP_S at a point within
    FRACTURE_DIST_BOXES box lengths of A's death, B outliving A, A
    still lacking its exit crossing (entry_only / no_crossing under
    the pinned gates), and the two endpoint bearings agreeing within
    CHAIN_DIR_TOL_DEG when both exist. Only tracks that carry an
    unrejected event take part (no event, nothing to double count).
    Greedy nearest pair by (dist / box + 0.5 * gap_s), each track in
    at most one pair. Write-then-reject (rejected=1), movement-
    agnostic: one vehicle is one count."""
    import numpy as np

    from backend.config import FRACTURE_DIST_BOXES, FRACTURE_GAP_S
    from backend.services.entry_gates import classify
    from backend.services.track_chains import (CHAIN_DIR_TOL_DEG,
                                               endpoint_bearings)
    from backend.services.track_cut import _bdiff

    db = str(db)
    conn = sqlite3.connect(db)
    try:
        evs = conn.execute(
            "SELECT event_id, vehicle_track_id FROM vehicle_events "
            "WHERE camera_id = ? AND COALESCE(rejected, 0) = 0 "
            "AND vehicle_track_id IS NOT NULL AND vehicle_track_id >= 0",
            (camera_id,)).fetchall()
        _recs, pairs = fracture_pairs(evs, rows, fps, gates)
        drop = {v["eid"] for _a, _b, v, _g, _r in pairs}
        n_pairs = len(pairs)
        with conn:
            conn.executemany(
                "UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?",
                [(int(e),) for e in drop])
    finally:
        conn.close()
    return {"camera_id": camera_id, "fracture_pairs": n_pairs,
            "fracture_rejected": len(drop)}


def continuation_pairs(evs, rows, fps, gates):
    """THE PREDICTED-CONTINUATION RULE's pairing, side-effect free.
    evs: [(event_id, track_id, origin_leg_id)] of the events in play.
    Returns (recs, pairs) with pairs = [(a_rec, b_rec, gap_s,
    residual_over_box)]; a_rec is always the fragment that yields.

    The fracture rule measured from A's DEATH point; this one measures
    from where A would BE: A's death + its end velocity x the gap. Every
    threshold is an existing frozen constant — the chain rule's moving-
    break window (STITCH_MOVE_GAP_S), the tracker's position-recovery
    reach in box widths (TRACKER_RECOVERY_REACH, box = the wider of the
    two boxes, tracker._recovery_cost), the bearing window
    (CHAIN_BEARING_END_S) for the end velocity and the direction gate
    (CHAIN_DIR_TOL_DEG)."""
    import numpy as np

    from backend.config import TRACKER_RECOVERY_REACH
    from backend.services.entry_gates import classify
    from backend.services.track_chains import (CHAIN_BEARING_END_S,
                                               CHAIN_DIR_TOL_DEG,
                                               STITCH_MOVE_GAP_S,
                                               endpoint_bearings)
    from backend.services.track_cut import _bdiff

    arr = np.asarray(rows, dtype=float)
    recs = []
    for eid, tid, origin in evs:
        sel = arr[arr[:, 0] == float(tid)]
        if len(sel) < 5:
            continue
        sel = sel[np.argsort(sel[:, 1])]
        pts = [(float(r[1]), float(r[2]), float(r[3])) for r in sel]
        *_o, tag = classify(pts, gates, fps)
        bs, be = endpoint_bearings(pts, fps)
        fd = pts[-1][0]
        k = int(np.searchsorted(sel[:, 1], fd - CHAIN_BEARING_END_S * fps))
        df = fd - float(sel[k, 1])
        vel = ((float(sel[-1, 2] - sel[k, 2]) / df,
                float(sel[-1, 3] - sel[k, 3]) / df) if df > 0 else (0.0, 0.0))
        recs.append({"eid": eid, "tid": int(tid), "origin": origin,
                     "pts": pts, "birth": pts[0], "death": pts[-1],
                     "tag": tag, "vel": vel,
                     "w_birth": float(sel[0, 4]), "w_death": float(sel[-1, 4]),
                     "b_start": bs, "b_end": be})
    recs.sort(key=lambda r: r["birth"][0])
    births = np.array([r["birth"][0] for r in recs], dtype=float)
    cands = []
    for ai, a in enumerate(recs):
        if a["tag"] not in ("entry_only", "no_crossing"):
            continue                       # A already owns its exit
        fa, xa, ya = a["death"]
        lo = int(np.searchsorted(births, fa + STITCH_MOVE_GAP_S[0] * fps,
                                 side="left"))
        hi = int(np.searchsorted(births, fa + STITCH_MOVE_GAP_S[1] * fps,
                                 side="right"))
        for bi in range(lo, hi):
            b = recs[bi]
            if b["tid"] == a["tid"] or b["death"][0] <= fa:
                continue
            if a["origin"] is None or b["origin"] != a["origin"]:
                continue                   # never trade a witnessed origin
            gap_f = b["birth"][0] - fa
            px, py = xa + a["vel"][0] * gap_f, ya + a["vel"][1] * gap_f
            box = max(a["w_death"], b["w_birth"])
            if box <= 0:
                continue
            rel = math.hypot(b["birth"][1] - px, b["birth"][2] - py) / box
            if rel >= TRACKER_RECOVERY_REACH:
                continue
            ba, bb = a.get("b_end"), b.get("b_start")
            if (ba is not None and bb is not None
                    and _bdiff(ba, bb) > CHAIN_DIR_TOL_DEG):
                continue
            gap_s = gap_f / fps
            cands.append((rel + 0.5 * max(gap_s, 0.0), ai, bi, gap_s, rel))
    cands.sort(key=lambda c: c[0])
    used = set()
    pairs = []
    for _s, ai, bi, gap_s, rel in cands:
        if ai in used or bi in used:
            continue
        used.add(ai); used.add(bi)
        pairs.append((recs[ai], recs[bi], gap_s, rel))
    return recs, pairs


def continuation_dedup(db: str | Path, camera_id: int, rows, fps,
                       gates) -> dict:
    """THE PREDICTED-CONTINUATION RULE (config.CONTINUATION_DEDUP): reject
    the event of a fragment that lacks its exit when a counted track of the
    same origin is born, within the chain rule's moving-break window, inside
    the tracker's recovery reach of where the fragment would be by then.
    Runs after the fracture rule and the bound-chain guard and cleans only
    their residue. Write-then-reject (rejected=1), movement-agnostic: one
    vehicle is one count."""
    db = str(db)
    conn = sqlite3.connect(db)
    try:
        evs = conn.execute(
            "SELECT event_id, vehicle_track_id, origin_leg_id "
            "FROM vehicle_events "
            "WHERE camera_id = ? AND COALESCE(rejected, 0) = 0 "
            "AND vehicle_track_id IS NOT NULL AND vehicle_track_id >= 0",
            (camera_id,)).fetchall()
        _recs, pairs = continuation_pairs(evs, rows, fps, gates)
        drop = {a["eid"] for a, _b, _g, _r in pairs}
        with conn:
            conn.executemany(
                "UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?",
                [(int(e),) for e in drop])
    finally:
        conn.close()
    return {"camera_id": camera_id, "continuation_pairs": len(pairs),
            "continuation_rejected": len(drop)}


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


def merge_replay_turns(db: str | Path, camera_id: int, *,
                       window_seconds: float,
                       expected_by_cell: dict | None = None) -> dict:
    """A4a post-pass on a pass-2 replay DB: volume-gated same-cell turn-fragment
    merge. Merged-away fragments are marked rejected=1 (non-destructive,
    reviewable in the worklist) — never deleted. THROUGH events are untouched
    by construction (the loader selects turns only).

    expected_by_cell overrides the bank expecteds (tests); default = the
    replay DB's own applied bank, time-scaled. Returns stats incl. the S5
    borderline cells for the caller to emit as review_flags."""
    db = str(db)
    conn = sqlite3.connect(db)
    try:
        turns = _load_turns(conn, camera_id)
        expected = (expected_by_cell if expected_by_cell is not None
                    else bank_expecteds(conn, camera_id, window_seconds))
        from backend.config import (MERGE_EXCESS_ONLY, QUEUE_AWARE_MERGE,
                                    TURN_MERGE)
        pairs: list[dict] = []
        if TURN_MERGE:
            keep = merge_turn_fragments(turns, MERGE_PX, MERGE_GAP,
                                        expected_by_cell=expected,
                                        vol_factor=VOL_FACTOR,
                                        queue_aware=QUEUE_AWARE_MERGE,
                                        excess_only=MERGE_EXCESS_ONLY,
                                        pairs_out=pairs)
        else:
            keep = {ev["id"] for ev in turns}        # arm mo1: merge off
        # diagnostics sidecar: every absorption the merge made or declined
        try:
            Path(db).with_suffix(".merge_pairs.json").write_text(
                json.dumps({"camera_id": camera_id,
                            "excess_only": MERGE_EXCESS_ONLY,
                            "pairs": pairs}))
        except OSError:                              # pragma: no cover
            logger.warning("merge-pair sidecar not written for %s", db)
        drop = [ev["id"] for ev in turns if ev["id"] not in keep]
        with conn:
            conn.executemany(
                "UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?",
                [(i,) for i in drop])
        borderline = borderline_merge_cells(turns, expected, VOL_FACTOR)
    finally:
        conn.close()
    return {"camera_id": camera_id, "turns": len(turns), "kept": len(keep),
            "merged_away": len(drop), "borderline": borderline,
            "window_seconds": window_seconds}


def s5_flags(camera_id: int, borderline: list[dict],
             leg_cardinals: dict[int, str], bound_approach) -> list[dict]:
    """Turn `borderline_merge_cells` output into insert_flags(**f) dicts
    (kind suspected_gap, subtype merge_borderline) — the S5 feeder
    (plan_flagqueue_B_2026-07-09). Called inside the rebuild path so the
    flags survive clear_open_flags."""
    flags = []
    for b in borderline:
        o, d = b["cell"]
        ap = bound_approach(leg_cardinals.get(o, ""))
        flags.append({
            "kind": "suspected_gap", "subtype": "merge_borderline",
            "camera_id": camera_id, "approach": ap, "movement": None,
            "impact": float(abs(b["raw"] - b["expected"])),
            "reason": (f"{ap}B turn cell {o}->{d}: {b['raw']} raw fragments vs "
                       f"merge threshold {b['threshold']} (expected "
                       f"{round(b['expected'])}) — the merge decision is one "
                       f"noise-vehicle from flipping; spot-check this cell."),
            "evidence": {"origin_leg_id": o, "destination_leg_id": d,
                         "raw": b["raw"], "expected": round(b["expected"], 1),
                         "threshold": b["threshold"], "merges": b["merges"]},
            "batch_key": None,
        })
    return flags
