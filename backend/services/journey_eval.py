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


def score_clip(labels: list[dict], rows: np.ndarray, events: list[dict],
               clip: dict) -> dict:
    """labels: journey_labels rows for the clip. rows: the replayed dump's
    rows. events: counted vehicle_events for the camera as dicts with
    vehicle_track_id, origin_leg_id, destination_leg_id, start_frame."""
    f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
    byf = index_rows(rows, f_lo - SEARCH_FRAMES, f_hi + SEARCH_FRAMES)
    ev_by_tid = defaultdict(list)
    for e in events:
        ev_by_tid[int(e["vehicle_track_id"])].append(e)
    per_vehicle, claimed = [], set()
    for lb in labels:
        tin = (track_at(byf, lb["entry_frame"], lb["entry_x"], lb["entry_y"])
               if lb.get("entry_frame") is not None else None)
        tout = (track_at(byf, lb["exit_frame"], lb["exit_x"], lb["exit_y"])
                if lb.get("exit_frame") is not None else None)
        tids = {t for t in (tin, tout) if t is not None}
        claimed |= tids
        full = lb.get("entry_frame") is not None and lb.get("exit_frame") is not None
        if not full:
            continue
        evs = [e for t in tids for e in ev_by_tid.get(t, ())]
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
        per_vehicle.append({"label_id": lb["label_id"], "truth": truth,
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
