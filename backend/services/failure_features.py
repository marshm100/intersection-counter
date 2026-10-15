"""FEATURES OF A REVIEWABLE INSTANCE (2026-10-15; failure predictor, plan proud-wiggling-swan).
Runtime-only descriptions of the two instance types a human can review - never a camera id or a site constant:
  C  a counted journey (a vehicle_events row + its track)
  U  an uncounted moving track that crossed a line (a gap_items candidate)
ctx (one window or clip): rows (dump rows [tid, frame, cx, cy, w, h, ...]), fps, fw / fh (frame size), flags
(encounter_flags over the counted tracks), events (counted vehicle_events dicts), tag ({tid: gate tag}).
Same inputs -> same numbers (no randomness): the predictor's pulls repeat.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

TAGS = ("full", "entry_only", "exit_only", "no_crossing")
SOURCES = {"gate_full": "gate_full", "branch1": "branch1", "straight_reroute": "reroute",
           "rescue_exit": "rescue", "rescue_supports": "rescue", "motion_lane": "motion", "motion_ray": "motion"}
SRC_KEYS = ("gate_full", "branch1", "reroute", "rescue", "motion", "none")
MOVES = ("through", "left", "right", "u_turn")
NEAR_W = 1.5
DENSITY_S = 60.0


def _prep(ctx: dict) -> dict:
    """Per-context caches: track rows by id, rows by frame (counted tracks), flags by id, counted ends."""
    if "_tr" in ctx:
        return ctx
    rows = ctx["rows"]
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    srt = rows[order]
    tids, i0 = np.unique(srt[:, 0], return_index=True)
    ctx["_tr"] = dict(zip(tids.astype(int), np.split(srt, i0[1:])))
    counted = {int(e["vehicle_track_id"]) for e in ctx["events"] if e.get("vehicle_track_id") is not None}
    byf = defaultdict(list)
    for t in counted:
        r = ctx["_tr"].get(t)
        if r is not None:
            for x in r:
                byf[int(x[1])].append(x)
    ctx["_byf"] = byf
    fl = defaultdict(list)
    for f in ctx["flags"]:
        fl[f["a"]].append(f)
        fl[f["b"]].append(f)
    ctx["_fl"] = fl
    od = {}
    t_by_origin = defaultdict(list)
    for e in ctx["events"]:
        t = e.get("vehicle_track_id")
        if t is None:
            continue
        od[int(t)] = (e.get("origin_leg_id"), e.get("destination_leg_id"))
        t_by_origin[e.get("origin_leg_id")].append(float(e["timestamp_video"]))
    ctx["_od"] = od
    ctx["_tob"] = {k: np.sort(np.array(v)) for k, v in t_by_origin.items()}
    return ctx


def _track(ctx, tid):
    r = ctx["_tr"].get(int(tid))
    return r if r is not None and len(r) else None


def _track_feats(ctx, tid) -> dict:
    fps, fw, fh = ctx["fps"], ctx["fw"], ctx["fh"]
    r = _track(ctx, tid)
    if r is None:
        return {"life_s": 0.0, "w_rel": 0.0, "h_rel": 0.0, "speed_rel": 0.0, "fill": 0.0,
                "edge_birth": 0.0, "edge_death": 0.0}
    life_f = max(float(r[-1, 1] - r[0, 1]), 1.0)
    step = np.hypot(np.diff(r[:, 2]), np.diff(r[:, 3]))
    dfr = np.maximum(np.diff(r[:, 1]), 1)

    def edge(x):
        return float(min(x[2], fw - x[2], x[3], fh - x[3]) / fw)
    return {"life_s": life_f / fps, "w_rel": float(np.median(r[:, 4]) / fw), "h_rel": float(np.median(r[:, 5]) / fh),
            "speed_rel": float(np.median(step / dfr) * fps / fw) if len(step) else 0.0,
            "fill": float(len(r) / (life_f + 1)), "edge_birth": edge(r[0]), "edge_death": edge(r[-1])}


def _neighbour_feats(ctx, tid, od=None) -> dict:
    """Nearest other COUNTED track over this track's life (box widths), how long it rides close, and whether a
    close concurrent counted track carries the same (origin, dest) - the double-count shape."""
    r = _track(ctx, tid)
    out = {"nb_min_w": 9.0, "nb_close_frac": 0.0, "nb_same_od": 0.0, "nb_n": 0.0}
    if r is None:
        return out
    close = defaultdict(int)
    best = 9.0
    for x in r:
        for y in ctx["_byf"].get(int(x[1]), ()):
            if int(y[0]) == int(tid):
                continue
            d = float(np.hypot(x[2] - y[2], x[3] - y[3]) / max(min(x[4], y[4]), 1.0))
            best = min(best, d)
            if d <= NEAR_W:
                close[int(y[0])] += 1
    out["nb_min_w"] = min(best, 9.0)
    if close:
        n = len(r)
        out["nb_close_frac"] = max(close.values()) / n
        out["nb_n"] = float(len(close))
        if od is not None:
            out["nb_same_od"] = float(any(ctx["_od"].get(t) == od and c / n >= 0.3 for t, c in close.items()))
    return out


def _flag_feats(ctx, tid) -> dict:
    fl = ctx["_fl"].get(int(tid), [])
    return {"enc_n": float(len(fl)), "enc_id_ends": float(any(f["why"] == "id ends" for f in fl)),
            "enc_partial": float(any(f["why"] == "partial" for f in fl))}


def _density(ctx, origin, t) -> float:
    a = ctx["_tob"].get(origin)
    if a is None:
        return 0.0
    return float(np.searchsorted(a, t + DENSITY_S) - np.searchsorted(a, t - DENSITY_S)) / (2 * DENSITY_S / 60)


def _num(v, default):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def c_features(e: dict, ctx: dict) -> dict:
    ctx = _prep(ctx)
    tid = int(e["vehicle_track_id"])
    tag = e.get("gate_tag") or ctx["tag"].get(tid)
    src = SOURCES.get(e.get("posterior_source") or "", "none")
    mv = e.get("movement")
    od = (e.get("origin_leg_id"), e.get("destination_leg_id"))
    f = {f"tag_{k}": float(tag == k) for k in TAGS}
    f.update({f"src_{k}": float(src == k) for k in SRC_KEYS})
    f.update({f"mv_{k}": float(mv == k) for k in MOVES})
    f.update({"det_conf": _num(e.get("detection_confidence"), 1.0),
              "traj_conf": _num(e.get("trajectory_confidence"), 1.0),
              "dest_conf": _num(e.get("destination_confidence"), 1.0),
              "dest_margin": _num(e.get("destination_margin"), 1.0),
              "orig_margin": _num(e.get("origin_margin"), 1.0),
              "straight": _num(e.get("classifier_path_straightness"), 1.0),
              "path_rel": _num(e.get("classifier_path_distance"), 0.0) / ctx["fw"],
              "turn_abs": abs(_num(e.get("classifier_net_heading_change"), 0.0)) / 180.0,
              "density": _density(ctx, e.get("origin_leg_id"), float(e["timestamp_video"]))})
    f.update(_track_feats(ctx, tid))
    f.update(_neighbour_feats(ctx, tid, od))
    f.update(_flag_feats(ctx, tid))
    return f


def u_features(it: dict, ctx: dict) -> dict:
    ctx = _prep(ctx)
    tid = int(it["tid"])
    f = {"u_full": float(it.get("tag") == "full"), "u_thief": float(it.get("suspect") == "thief"),
         "density": _density(ctx, it.get("origin_leg_id"), float(it["t_cross"]))}
    f.update(_track_feats(ctx, tid))
    f.update(_neighbour_feats(ctx, tid))
    return f
