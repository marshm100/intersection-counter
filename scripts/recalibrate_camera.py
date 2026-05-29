"""Data-driven leg + path-bank recalibration (Phase 3, direction-based).

Rebuilds the leg reference_headings + path bank from regenerated trajectories.
At this camera detection is late and starts span a continuous horizontal band, so
origins are NOT recoverable from start-point clustering. Instead we separate flows
by DIRECTION OF TRAVEL: the two opposite dominant tail-heading modes define the
arterial axis (the through pair); off-axis tails are turns. Movements come from the
flow geometry; approach identity from count-matching the manual TMC. Only the
reliable signals are used (tails + counts), never the suspect stored headings or
mid-turn entry tangents. See docs/recalibration_plan_2026-05-27.md.

Emits a suggestion JSON (updated_legs + paths). Does NOT write the DB.

Usage:
  py scripts/recalibrate_camera.py --out evaluations/recal_cam1.json
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.auto_calibrate import _fit_mean_polyline
from backend.services.trajectory_classifier import _exit_velocity
from groundtruth import (
    ALL_MVT, BUCKET_SECONDS, bucket_to_footage_seconds, db_processed_window,
    overlap_seconds, parse_manual_csv,
)
from replay_attribution_changes import PROJECT_DB, load_events, load_legs

# Manual study approaches; the two Belt Line ones carry the through arterial.
BELT_APPROACHES = ["NB N Belt Line Rd", "SB N Belt Line Rd"]   # arterial (through pair)
SIDE_APPROACHES = ["EB Northwest Dr", "WB Private Driveway"]    # side streets (turns)
# Corrected 2026-05-29: leg labels were 180°-rotated (see memory
# project_leg_labels_swapped). NB=22, SB=23, EB=24, WB=25.
APPROACH_TO_LEG = {"NB N Belt Line Rd": 22, "SB N Belt Line Rd": 23,
                   "EB Northwest Dr": 24, "WB Private Driveway": 25}
# Miovision OD destination for each (approach, turn) — the ground-truth where each
# turn EXITS (from the per-minute XML OD matrix; memory reference_miovision_perminute_od).
# Used to route turn clusters geometrically instead of by fragile count-match.
OD_DEST = {
    ("NB N Belt Line Rd", "left"):  "EB Northwest Dr",
    ("NB N Belt Line Rd", "right"): "WB Private Driveway",
    ("SB N Belt Line Rd", "left"):  "WB Private Driveway",
    ("SB N Belt Line Rd", "right"): "EB Northwest Dr",
    ("EB Northwest Dr", "left"):    "SB N Belt Line Rd",
    ("EB Northwest Dr", "right"):   "NB N Belt Line Rd",
    ("WB Private Driveway", "left"):  "NB N Belt Line Rd",
    ("WB Private Driveway", "right"): "SB N Belt Line Rd",
}
THROUGH_TOL_DEG = 45.0
POLYLINE_PTS = 15


def _heading_of(vx, vy):
    return math.degrees(math.atan2(vx, -vy)) % 360


def _tail_heading(traj):
    return _heading_of(*_exit_velocity(traj))


def _ang_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def _circ_mean(degs):
    s = sum(math.sin(math.radians(d)) for d in degs)
    c = sum(math.cos(math.radians(d)) for d in degs)
    return math.degrees(math.atan2(s, c)) % 360 if degs else 0.0


def _resample(traj, n=12):
    """Arc-length resample a trajectory to n points (reduces jitter)."""
    pts = np.asarray(traj, dtype=float)
    if len(pts) < 2:
        return pts
    seg = np.sqrt(((pts[1:] - pts[:-1]) ** 2).sum(1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    if cum[-1] == 0:
        return pts
    want = np.linspace(0, cum[-1], n)
    return np.column_stack([np.interp(want, cum, pts[:, 0]),
                            np.interp(want, cum, pts[:, 1])])


def _signed_curvature(traj):
    """(cumulative_abs_turn_deg, signed_sum_deg) over a resampled trajectory.

    Robust to entry truncation: it measures how much the OBSERVED path bends,
    independent of the (unreliable) absolute entry heading. Signed sum > 0 is a
    right rotation (image convention), < 0 left. Distinguishes a turn (high
    cumulative bend) from a through (low) even when tails coincide (NB-left tail
    == SB-through tail)."""
    p = _resample(traj, 12)
    if len(p) < 3:
        return 0.0, 0.0
    abs_t, signed = 0.0, 0.0
    for i in range(1, len(p) - 1):
        a = math.atan2(p[i][0] - p[i-1][0], -(p[i][1] - p[i-1][1]))
        b = math.atan2(p[i+1][0] - p[i][0], -(p[i+1][1] - p[i][1]))
        d = math.degrees((b - a + math.pi) % (2 * math.pi) - math.pi)
        abs_t += abs(d); signed += d
    return abs_t, signed


def _bearing(frm, to):
    return math.degrees(math.atan2(to[0] - frm[0], -(to[1] - frm[1]))) % 360


def detect_axis(tails, bin_deg=15):
    """Return (dir_a, dir_b) — the two opposite dominant tail directions."""
    nb = int(360 / bin_deg)
    hist = [0] * nb
    for t in tails:
        hist[int(t // bin_deg) % nb] += 1
    a = max(range(nb), key=lambda i: hist[i])
    dir_a = a * bin_deg + bin_deg / 2
    opp = (dir_a + 180) % 360
    cand = [i for i in range(nb) if _ang_diff(i * bin_deg + bin_deg / 2, opp) <= 30]
    b = max(cand, key=lambda i: hist[i]) if cand else int((a + nb // 2) % nb)
    dir_b = b * bin_deg + bin_deg / 2
    # refine each as circular mean of tails closest to it
    ta = [t for t in tails if _ang_diff(t, dir_a) <= _ang_diff(t, dir_b)]
    tb = [t for t in tails if _ang_diff(t, dir_b) < _ang_diff(t, dir_a)]
    return _circ_mean(ta) if ta else dir_a, _circ_mean(tb) if tb else dir_b


def manual_for_window(window):
    manual = parse_manual_csv()
    out = {a: {m: 0.0 for m in ALL_MVT} for a in APPROACH_TO_LEG}
    p0, p1 = window
    for label, bucket in manual.items():
        b0, b1 = bucket_to_footage_seconds(label)
        ov = overlap_seconds(p0, p1, b0, b1)
        if ov <= 0:
            continue
        sc = ov / BUCKET_SECONDS
        for a in APPROACH_TO_LEG:
            if a in bucket:
                for m in ALL_MVT:
                    out[a][m] += bucket[a][m] * sc
    return out


def derive_turn_paths(trajs, legs_by_id, manual, center, *, min_support=5,
                      turn_curv_thresh=55.0, max_clusters=8, vol_factor=2.0,
                      min_arc_px=130.0):
    """Exit-driven turn-path derivation (docs/turn_attribution_plan_2026-05-29.md).

    Split turns from throughs by cumulative curvature (robust to truncated
    entries), cluster the turn pool on the reliable exit suffix, assign
    destination by tail->leg bearing and origin+label by manual count-match on
    rotation sense. Returns (paths, assigned_rows). Emits REAL (origin, dest,
    label) rows so the joint scorer attributes turns at Tier-0."""
    from scipy.cluster.hierarchy import fcluster, linkage

    pool = []  # (traj, signed_curv)
    for t in trajs:
        absc, signed = _signed_curvature(t)
        if absc >= turn_curv_thresh:
            pool.append((t, signed))
    if len(pool) < min_support:
        return [], []

    feats = []
    for t, _ in pool:
        rs = _resample(t, 12)
        tail = _tail_heading(t)
        half = rs[len(rs) // 2:]            # latter (observed) half only
        end = rs[-1]
        feats.append([end[0], end[1],
                      math.sin(math.radians(tail)) * 60,
                      math.cos(math.radians(tail)) * 60,
                      *half[::2].flatten()])
    F = np.asarray(feats, dtype=float)
    F = (F - F.mean(0)) / (F.std(0) + 1e-6)
    K = min(max_clusters, len(pool))
    labels = fcluster(linkage(F, method="ward"), t=K, criterion="maxclust")

    clusters = []
    for c in set(labels):
        ms = [pool[i] for i in range(len(pool)) if labels[i] == c]
        if len(ms) < min_support:
            continue
        ts = [m[0] for m in ms]
        clusters.append({
            "count": len(ts),
            "tail": _circ_mean([_tail_heading(t) for t in ts]),
            "rotation": "right" if np.median([m[1] for m in ms]) > 0 else "left",
            "polyline": _fit_mean_polyline(ts, POLYLINE_PTS),
        })

    # OD-anchored routing (memory reference_miovision_perminute_od): a turn's
    # (origin_leg -> dest_leg) is FIXED by the Miovision OD matrix, so route each
    # cluster geometrically against that matrix instead of count-matching rotation
    # sense (which force-fit arterial-contaminated clusters onto cross-street cells
    # and over-attributed). valid_od[(origin_leg, dest_leg)] = (movement, manual_cnt).
    valid_od = {}
    for appr, leg_id in APPROACH_TO_LEG.items():
        for mv in ("left", "right"):
            cnt = manual.get(appr, {}).get(mv, 0.0)
            dest_appr = OD_DEST.get((appr, mv))
            dest_leg = APPROACH_TO_LEG.get(dest_appr) if dest_appr else None
            if cnt >= min_support and dest_leg is not None:
                valid_od[(leg_id, dest_leg)] = (mv, cnt, appr)

    leg_bear = {lid: _bearing(center, lg["origin"]) for lid, lg in legs_by_id.items()}

    def _dist(p, lid):
        o = legs_by_id[lid]["origin"]
        return math.hypot(p[0] - o[0], p[1] - o[1])

    # Route every cluster to an OD movement, then keep ONE path per
    # (origin, dest, movement) — the intersection_paths schema is UNIQUE on
    # (camera, origin, dest), and multiple clusters per movement are sub-arcs of
    # one maneuver. Keep the dominant (largest) cluster as the representative.
    best: dict = {}   # (o, d, mv) -> (cluster, cnt, appr)
    for cl in clusters:
        dest = min(leg_bear, key=lambda lid: _ang_diff(leg_bear[lid], cl["tail"]))
        start = cl["polyline"][0]
        cands = [(o, d, mv, cnt, appr) for (o, d), (mv, cnt, appr) in valid_od.items()
                 if d == dest and mv == cl["rotation"]]
        if not cands:
            continue
        o, d, mv, cnt, appr = min(cands, key=lambda c: _dist(start, c[0]))
        key = (o, d, mv)
        if key not in best or cl["count"] > best[key][0]["count"]:
            best[key] = (cl, cnt, appr)

    def _arc(poly):
        return sum(math.hypot(poly[i][0]-poly[i-1][0], poly[i][1]-poly[i-1][1])
                   for i in range(1, len(poly)))

    paths, assigned = [], []
    for (o, d, mv), (cl, cnt, appr) in best.items():
        # Volume-sanity gate (plan validation gate): a representative cluster far
        # larger than the manual movement is arterial-contaminated (the EB
        # over-attribution) — drop rather than emit a polyline that vacuums
        # through traffic.
        if cl["count"] > vol_factor * cnt:
            assigned.append((appr, mv, cl["count"], d, round(cl["tail"]), "DROP>vol"))
            continue
        # Min-arc gate: a stub turn polyline (short observed arc) over-attributes —
        # any through passing through its region clears the coverage floor. A real
        # turn traverses a substantial arc. (Drops the EB cross-street stubs that
        # steal through traffic; keeps the long arterial turns like NB-left.)
        if _arc(cl["polyline"]) < min_arc_px:
            assigned.append((appr, mv, cl["count"], d, round(cl["tail"]), "DROP<arc"))
            continue
        paths.append({"origin_leg_id": o, "destination_leg_id": d,
                      "movement_label": mv,
                      "polyline": [[round(x, 1), round(y, 1)] for x, y in cl["polyline"]],
                      "supporting_count": cl["count"], "source": "data-driven"})
        assigned.append((appr, mv, cl["count"], d, round(cl["tail"]), "ok"))
    return paths, assigned


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evaluations/recal_cam1.json")
    ap.add_argument("--min-support", type=int, default=5)
    args = ap.parse_args()

    conn = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(conn)
    events = load_events(conn)
    conn.close()
    trajs = [e["trajectory"] for e in events if e["trajectory"] and len(e["trajectory"]) >= 4]
    window = db_processed_window()
    manual = manual_for_window(window)
    tails = [_tail_heading(t) for t in trajs]
    median_start_x = float(np.median([t[0][0] for t in trajs]))
    print(f"loaded {len(trajs)} trajectories; window {window[0]:.0f}-{window[1]:.0f}s")

    # --- Step 1: arterial axis + flow groups (no start-zone clustering) ---
    dir_a, dir_b = detect_axis(tails)
    print(f"\n=== Step 1: arterial axis ~ {dir_a:.0f} / {dir_b:.0f} deg ===")
    groups: dict[str, list] = {}
    for t in trajs:
        th = _tail_heading(t)
        da, db = _ang_diff(th, dir_a), _ang_diff(th, dir_b)
        if min(da, db) <= THROUGH_TOL_DEG:
            key = "through_a" if da < db else "through_b"   # by travel direction
        else:
            # off-axis turn: rotation sense of tail vs nearest axis direction
            base = dir_a if da < db else dir_b
            cross = math.sin(math.radians(th - base))
            key = "turn_right" if cross > 0 else "turn_left"
        groups.setdefault(key, []).append(t)
    for k, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"  {k:<12} n={len(g):<4} median_tail={_circ_mean([_tail_heading(x) for x in g]):.0f}")
    thru_groups = sorted([k for k in groups if k.startswith("through")],
                         key=lambda k: -len(groups[k]))
    covered = sum(len(groups[k]) for k in thru_groups)
    # Gate 1: through pair dominates
    print(f"  through pair covers {covered}/{len(trajs)} ({covered/len(trajs)*100:.0f}%) "
          f"[gate: >=70%]")

    # --- Step 2: median polyline + stats per group ---
    def stat(g):
        return {"count": len(g), "polyline": _fit_mean_polyline(g, POLYLINE_PTS),
                "tail": _circ_mean([_tail_heading(x) for x in g]),
                "start_x": float(np.median([x[0][0] for x in g])),
                "start_pt": [float(np.median([x[0][0] for x in g])),
                             float(np.median([x[0][1] for x in g]))]}
    gstats = {k: stat(g) for k, g in groups.items() if len(g) >= args.min_support}

    # --- Step 3: assign through pair -> Belt legs by GEOMETRY (direction) ---
    # Count-rank (biggest group -> biggest manual) is fragile: when one direction
    # is over-counted enough to outrank the other it mis-assigns NB<->SB (it did,
    # post-relabel). Instead anchor on geometry: each belt leg's through travels
    # from its entry origin toward the OPPOSITE belt leg, so match each observed
    # through group to the leg whose expected through-heading its tail is nearest.
    # (Leg labels corrected 2026-05-29 — memory project_leg_labels_swapped.)
    leg_origin = {lg["leg_id"]: lg["origin_zone"][0] for lg in legs if lg.get("origin_zone")}
    belt_legs = [APPROACH_TO_LEG[a] for a in BELT_APPROACHES]   # [NB, SB]
    other_of = {belt_legs[0]: belt_legs[1], belt_legs[1]: belt_legs[0]}
    exp_tail = {lid: _bearing(leg_origin[lid], leg_origin[other_of[lid]]) for lid in belt_legs}
    leg_to_appr = {APPROACH_TO_LEG[a]: a for a in BELT_APPROACHES}
    updated_legs, paths = [], []
    assigned = {}
    used_legs: set = set()
    for gk in thru_groups[:2]:
        gs = gstats.get(gk)
        if gs is None:
            continue
        cand = [lid for lid in belt_legs if lid not in used_legs]
        leg_id = min(cand, key=lambda lid: _ang_diff(exp_tail[lid], gs["tail"]))
        used_legs.add(leg_id)
        appr = leg_to_appr[leg_id]
        dest_leg = other_of[leg_id]
        # origin_point intentionally NOT emitted. At this camera detection is
        # late and starts span the full road width, so median(start) is a band
        # centroid, not a real approach entry (see module docstring). We keep the
        # engineer-placed leg origin and update reference_heading only; the
        # data-driven PATHS carry attribution (pipeline._assign_origin is
        # polyline-first). median_start is recorded for audit/debug only.
        updated_legs.append({"leg_id": leg_id, "approach": appr,
                             "reference_heading": round(gs["tail"], 1),
                             "median_start": [round(gs["start_pt"][0], 1), round(gs["start_pt"][1], 1)]})
        paths.append({"origin_leg_id": leg_id, "destination_leg_id": dest_leg,
                      "movement_label": "through",
                      "polyline": [[round(x, 1), round(y, 1)] for x, y in gs["polyline"]],
                      "supporting_count": gs["count"], "source": "data-driven"})
        assigned[(appr, "thru")] = gs["count"]
        print(f"\n  through group {gk} (n={gs['count']}, tail={gs['tail']:.0f}) -> "
              f"{appr} (L{leg_id}) through, dest L{dest_leg}, ref={gs['tail']:.0f}")

    # --- Turn paths: exit-driven clustering + count-match (real dest + label) ---
    legs_by_id = {lg["leg_id"]: {"origin": lg["origin_zone"][0],
                                 "ref": lg["reference_heading"], "label": lg["label"]}
                  for lg in legs if lg.get("origin_zone")}
    center = [float(np.mean([g["origin"][0] for g in legs_by_id.values()])),
              float(np.mean([g["origin"][1] for g in legs_by_id.values()]))]
    turn_paths, turn_assigned = derive_turn_paths(
        trajs, legs_by_id, manual, center, min_support=args.min_support)
    paths.extend(turn_paths)
    print(f"\n=== Turn paths (OD-anchored, n={len(turn_paths)}; center={[round(c) for c in center]}) ===")
    for appr, mvt, cnt, dest, tail, status in turn_assigned:
        if status == "ok":
            assigned[(appr, mvt)] = cnt
        print(f"  {appr} {mvt} n={cnt} -> dest L{dest} (tail={tail}) [{status}]")

    # --- Validation gate: assigned vs manual ---
    print(f"\n=== Gate: assigned vs manual (window) ===")
    print(f"{'approach':<22} {'mvt':<6} {'manual':>7} {'assigned':>9}")
    for appr in APPROACH_TO_LEG:
        for m in ALL_MVT:
            man = manual[appr][m]
            asg = assigned.get((appr, m), 0)
            if man < 0.5 and asg == 0:
                continue
            print(f"{appr:<22} {m:<6} {man:>7.1f} {asg:>9}")

    out = {"project": "97a7849a", "camera_id": 1, "window_sec": list(window),
           "arterial_axis_deg": [round(dir_a, 1), round(dir_b, 1)],
           "updated_legs": updated_legs, "paths": paths}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nwrote suggestion -> {args.out}  ({len(paths)} paths, {len(updated_legs)} legs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
