"""Score a tracking arm against journey labels (2026-09-30,
docs/research_tracking_2026-09-29.md phase 0b).

For every labelled vehicle: find the track under the operator's entry click
at the entry frame and the track under the exit click at the exit frame, then
look at what the arm counted for those tracks. Each vehicle gets ONE outcome:

  correct   exactly one counted event, with the labelled origin and destination
  wrong     exactly one counted event, with a different origin or destination
  double    two or more counted events for the vehicle
  missed    no counted event
  no_track  no track under a click (a detection gap at that moment)

plus a BROKEN flag when the entry and exit clicks land on different track ids
(one vehicle split into pieces). Counted events inside the clip that belong to
no labelled vehicle are PHANTOMS. Only full journeys (both sides labelled) are
scored for outcome; partial labels (inside at the clip start or end) are used
only to claim their tracks, so their events are not called phantoms.
Dev-validation only.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

SEARCH_FRAMES = 2          # look this many frames either side of a click
BOX_PAD = 0.25             # a click may sit this fraction of the box outside it
# A car is tracked to the image edge and the operator clicks its exit as it
# LEAVES the screen, a moment after the track ended (cam1 labels, 2026-09-30:
# 9 of 11 "no_track" exits were the entry track ending 1-5 frames earlier,
# within 1.4 boxes of the click). The entry track stands in for the exit when
# it ended this close before the exit click. The mirror holds at the entry: a
# car driving INTO view is clicked at once and its track is born 1-3 frames
# later (cam3 labels: 10 southbound cars entering at the bottom edge).
END_TOL_S = 0.5
END_TOL_BOXES = 1.5


def track_at(rows_by_frame: dict, frame: int, x: float, y: float):
    """The track id whose box contains (x, y) at `frame` (nearest centre wins;
    boxes padded by BOX_PAD; +-SEARCH_FRAMES tolerance). None if none."""
    best, best_d = None, float("inf")
    for df in range(SEARCH_FRAMES + 1):
        for f in {frame - df, frame + df}:
            for r in rows_by_frame.get(f, ()):
                cx, cy, bw, bh = float(r[2]), float(r[3]), float(r[4]), float(r[5])
                if (abs(x - cx) <= bw * (0.5 + BOX_PAD)
                        and abs(y - cy) <= bh * (0.5 + BOX_PAD)):
                    d = (x - cx) ** 2 + (y - cy) ** 2
                    if d < best_d:
                        best, best_d = int(r[0]), d
        if best is not None:
            return best
    return None


def index_rows(rows: np.ndarray, f_lo: int, f_hi: int) -> dict:
    sel = rows[(rows[:, 1] >= f_lo) & (rows[:, 1] <= f_hi)]
    out = defaultdict(list)
    for r in sel:
        out[int(r[1])].append(r)
    return out


def _ends(rows: np.ndarray) -> tuple[dict, dict]:
    """Each track's first and last row."""
    if not len(rows):
        return {}, {}
    o = np.lexsort((rows[:, 1], rows[:, 0]))
    r = rows[o]
    tids, i0 = np.unique(r[:, 0], return_index=True)
    i1 = np.r_[i0[1:], len(r)] - 1
    return ({int(t): r[i] for t, i in zip(tids, i0)},
            {int(t): r[i] for t, i in zip(tids, i1)})


def _rear_point(byf: dict, tid: int, frame: int, r) -> tuple[float, float]:
    """Where the operator clicks: the BACK TYRE (operator 2026-09-30: clicks
    are made as the back tyre crosses the gate). The box's lower half, set back
    from the centre against the direction of travel (from the same track a few
    frames either side); the lower centre if the track has no motion here."""
    cx, cy, bw, bh = float(r[2]), float(r[3]), float(r[4]), float(r[5])
    pts = [(f, q) for f in range(frame - 3, frame + 4)
           for q in byf.get(f, ()) if int(q[0]) == tid]
    ux = uy = 0.0
    if len(pts) >= 2:
        (fa, a), (fb, b) = min(pts, key=lambda p: p[0]), max(pts, key=lambda p: p[0])
        dx, dy = float(b[2] - a[2]), float(b[3] - a[3])
        n = float(np.hypot(dx, dy))
        if n > 1e-6:
            ux, uy = dx / n, dy / n
    back = 0.7 * (abs(ux) * bw / 2 + abs(uy) * bh / 2)
    return cx - ux * back, cy + bh / 4 - uy * back


def _candidates(byf: dict, ends: dict, frame: int, x: float, y: float,
                fps: float, side: str) -> dict:
    """Track id -> cost of matching this click. Under the click (inside the
    padded box): the click's distance from the box's BACK-TYRE point in
    half-diagonals, plus a little per frame of search. Otherwise a track BORN
    just after an entry click (side 'in') or that ENDED just before an exit
    click (side 'out'), close to it: cost 2 + its distance in box widths."""
    out: dict = {}
    for df in range(-SEARCH_FRAMES, SEARCH_FRAMES + 1):
        for r in byf.get(frame + df, ()):
            bw, bh = max(float(r[4]), 1.0), max(float(r[5]), 1.0)
            d = max(abs(x - r[2]) / (bw / 2), abs(y - r[3]) / (bh / 2))
            if d <= 1 + 2 * BOX_PAD:
                rx, ry = _rear_point(byf, int(r[0]), frame + df, r)
                c = (np.hypot(x - rx, y - ry) / (0.5 * np.hypot(bw, bh))
                     + 0.1 * abs(df))
                t = int(r[0])
                out[t] = min(out.get(t, c), c)
    for t, r in ends.items():
        if t in out:
            continue
        gap = (float(r[1]) - frame) if side == "in" else (frame - float(r[1]))
        if -SEARCH_FRAMES <= gap <= END_TOL_S * fps:
            dist = np.hypot(x - r[2], y - r[3]) / max(float(r[4]), 1.0)
            if dist <= END_TOL_BOXES:
                out[t] = 2.0 + dist
    return out


def _assign_clicks(labels: list[dict], rows: np.ndarray, byf: dict,
                   fps: float) -> tuple[dict, dict]:
    """One-to-one: every entry click gets its own track and every exit click
    its own track, solved over the whole clip at once (cam2 labels
    2026-09-30: in a packed queue a click can sit on the neighbour's box, and
    a greedy nearest match shifted a whole platoon by one car)."""
    from scipy.optimize import linear_sum_assignment
    lo = min((int(f) for f in byf), default=0) - int(END_TOL_S * fps) - 1
    hi = max((int(f) for f in byf), default=0) + int(END_TOL_S * fps) + 1
    live = np.unique(rows[(rows[:, 1] >= lo) & (rows[:, 1] <= hi), 0]) if len(rows) else []
    sub = rows[np.isin(rows[:, 0], live)] if len(rows) else rows
    first, last = _ends(sub)
    result = []
    for side, ends in (("in", first), ("out", last)):
        lids, cands = [], []
        for lb in labels:
            f = lb.get(f"{'entry' if side == 'in' else 'exit'}_frame")
            if f is None:
                continue
            x = lb[f"{'entry' if side == 'in' else 'exit'}_x"]
            y = lb[f"{'entry' if side == 'in' else 'exit'}_y"]
            lids.append(lb["label_id"])
            cands.append(_candidates(byf, ends, int(f), x, y, fps, side))
        tids = sorted({t for c in cands for t in c})
        got: dict = {}
        if lids and tids:
            col = {t: j for j, t in enumerate(tids)}
            big = 1e6
            m = np.full((len(lids), len(tids)), big)
            for i, c in enumerate(cands):
                for t, v in c.items():
                    m[i, col[t]] = v
            ri, ci = linear_sum_assignment(m)
            got = {lids[i]: tids[j] for i, j in zip(ri, ci) if m[i, j] < big}
        result.append(got)
    return result[0], result[1]


def score_clip(labels: list[dict], rows: np.ndarray, events: list[dict],
               clip: dict, fps: float = 10.0) -> dict:
    """labels: journey_labels rows for the clip. rows: the replayed dump's
    rows. events: counted vehicle_events for the camera as dicts with
    vehicle_track_id, origin_leg_id, destination_leg_id, start_frame."""
    f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
    byf = index_rows(rows, f_lo - SEARCH_FRAMES, f_hi + SEARCH_FRAMES)
    ev_by_tid = defaultdict(list)
    for e in events:
        ev_by_tid[int(e["vehicle_track_id"])].append(e)
    entry_of, exit_of = _assign_clicks(labels, rows, byf, fps)
    # every track is credited to ONE vehicle: the one that entered on it,
    # else the one that left on it
    owner: dict = {}
    for side in (exit_of, entry_of):
        for lid, t in side.items():
            owner[t] = lid
    claimed = set(owner)
    per_vehicle = []
    for lb in labels:
        lid = lb["label_id"]
        tin, tout = entry_of.get(lid), exit_of.get(lid)
        tids = {t for t in (tin, tout) if t is not None}
        full = lb.get("entry_frame") is not None and lb.get("exit_frame") is not None
        if not full:
            continue
        evs = [e for t in tids if owner.get(t) == lid for e in ev_by_tid.get(t, ())]
        truth = (lb["entry_leg_id"], lb["exit_leg_id"])
        if tin is None or tout is None:
            outcome = "no_track"
        elif not evs:
            outcome = "missed"
        elif len(evs) > 1:
            outcome = "double"
        elif (evs[0]["origin_leg_id"], evs[0]["destination_leg_id"]) == truth:
            outcome = "correct"
        else:
            outcome = "wrong"
        per_vehicle.append({"label_id": lid, "truth": truth,
                            "outcome": outcome,
                            "broken": tin is not None and tout is not None and tin != tout,
                            "tracks": sorted(tids), "n_events": len(evs)})
    phantoms = [e for e in events
                if f_lo <= int(e.get("start_frame") or -1) <= f_hi
                and int(e["vehicle_track_id"]) not in claimed]
    truth_cells = Counter(v["truth"] for v in per_vehicle)
    ours_cells = Counter((e["origin_leg_id"], e["destination_leg_id"]) for e in events
                         if f_lo <= int(e.get("start_frame") or -1) <= f_hi)
    outcomes = Counter(v["outcome"] for v in per_vehicle)
    n = len(per_vehicle)
    return {"n_full": n, "outcomes": dict(outcomes),
            "correct_rate": (outcomes["correct"] / n) if n else None,
            "broken": sum(v["broken"] for v in per_vehicle),
            "phantoms": len(phantoms),
            "cells": {f"{o}->{d}": {"truth": truth_cells.get((o, d), 0),
                                    "ours": ours_cells.get((o, d), 0)}
                      for (o, d) in sorted(set(truth_cells) | set(ours_cells),
                                           key=lambda c: (str(c[0]), str(c[1])))},
            "per_vehicle": per_vehicle}


def mcnemar(a: dict, b: dict) -> dict:
    """Paired comparison of two arms' per-vehicle success (outcome == correct)
    on the same labels. Exact binomial two-sided p on the discordant pairs."""
    from math import comb
    sa = {v["label_id"]: v["outcome"] == "correct" for v in a["per_vehicle"]}
    sb = {v["label_id"]: v["outcome"] == "correct" for v in b["per_vehicle"]}
    common = sa.keys() & sb.keys()
    only_a = sum(1 for k in common if sa[k] and not sb[k])
    only_b = sum(1 for k in common if sb[k] and not sa[k])
    n = only_a + only_b
    k = min(only_a, only_b)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / (2 ** n)) if n else 1.0
    return {"vehicles": len(common), "a_only_correct": only_a,
            "b_only_correct": only_b, "p_value": p}
