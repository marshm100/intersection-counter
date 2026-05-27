"""Data-driven leg + path-bank recalibration (Phase 3, steps 1-3).

Rebuilds the leg reference_headings + the path bank from the regenerated
trajectories, using only the RELIABLE signals (tails for direction; shape +
manual TMC counts for labels) — never the suspect stored reference_headings or
the mid-turn entry tangents. See docs/recalibration_plan_2026-05-27.md.

Steps:
  1. Origins from START points only (single-linkage cluster); reference_heading
     from the data-derived origin->center geometry (not old headings, not
     entries). Each origin blob mapped to a manual approach name by anchor.
  2. Label-free SHAPE clustering (feature vector + Ward) -> K path clusters,
     each with a median polyline + count + median tail heading.
  3. Per-approach ASSIGNMENT of clusters -> movements: match cluster counts to
     the manual movement vector, gated by tail-heading feasibility (a cluster
     may only take a movement whose geometric exit direction is within a sector
     of the cluster's tail). Breaks the circularity: tails give feasibility,
     manual gives targets, shape gives the polylines.

Emits a suggestion JSON (auto_cal schema + an `updated_legs` block). Does NOT
write legs/paths directly — review via recalibrate_viz.py, then apply.

Usage:
  py scripts/recalibrate_camera.py --out evaluations/recal_cam1.json
  py scripts/recalibrate_camera.py --k 8 --min-support 5 --start-min-samples 5
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.auto_calibrate import _fit_mean_polyline, _resample_by_arclength, dbscan_like
from backend.services.trajectory_classifier import _exit_velocity
from groundtruth import (
    ALL_MVT, BUCKET_SECONDS, bucket_to_footage_seconds, db_processed_window,
    overlap_seconds, parse_manual_csv,
)
from replay_attribution_changes import PROJECT_DB, load_events, load_legs

# Manual study approach entrances (image coords), from groundtruth.py comments.
APPROACH_ANCHORS = {
    "SB N Belt Line Rd":   (494.0, 217.0),
    "NB N Belt Line Rd":   (143.0, 357.0),
    "WB Private Driveway": (541.0, 357.0),
    "EB Northwest Dr":     (227.0, 227.0),
}
APPROACH_TO_LEG = {  # inverse of groundtruth.LEG_TO_APPROACH
    "SB N Belt Line Rd": 22, "NB N Belt Line Rd": 23,
    "WB Private Driveway": 24, "EB Northwest Dr": 25,
}
FEASIBILITY_SECTOR_DEG = 65.0
POLYLINE_PTS = 15


def _heading_of(vx: float, vy: float) -> float:
    return math.degrees(math.atan2(vx, -vy)) % 360


def _tail_heading(traj) -> float:
    vx, vy = _exit_velocity(traj)
    return _heading_of(vx, vy)


def _circular_median_deg(degs: list[float]) -> float:
    if not degs:
        return 0.0
    s = sum(math.sin(math.radians(d)) for d in degs)
    c = sum(math.cos(math.radians(d)) for d in degs)
    return math.degrees(math.atan2(s, c)) % 360


def _ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _nearest(pt, anchors: dict):
    best, bd = None, 1e18
    for name, (ax, ay) in anchors.items():
        d = (pt[0] - ax) ** 2 + (pt[1] - ay) ** 2
        if d < bd:
            bd, best = d, name
    return best, math.sqrt(bd)


def extract_shape_features(traj, n_mid: int = 4) -> np.ndarray:
    start = np.asarray(traj[0], dtype=float)
    end = np.asarray(traj[-1], dtype=float)
    rs = _resample_by_arclength(traj, n_mid + 2)
    mids = np.asarray(rs[1:-1], dtype=float).ravel()
    vx, vy = _exit_velocity(traj)
    return np.concatenate([start, end, mids, [vx, vy]])


def manual_for_window(window) -> dict:
    """Manual[approach_name][movement] apportioned to the footage-second window."""
    manual = parse_manual_csv()
    out = {a: {m: 0.0 for m in ALL_MVT} for a in APPROACH_ANCHORS}
    p0, p1 = window
    for label, bucket in manual.items():
        b0, b1 = bucket_to_footage_seconds(label)
        ov = overlap_seconds(p0, p1, b0, b1)
        if ov <= 0:
            continue
        scale = ov / BUCKET_SECONDS
        for a in APPROACH_ANCHORS:
            if a in bucket:
                for m in ALL_MVT:
                    out[a][m] += bucket[a][m] * scale
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evaluations/recal_cam1.json")
    ap.add_argument("--k", type=int, default=8, help="shape clusters")
    ap.add_argument("--min-support", type=int, default=5, help="min trajectories per path cluster")
    ap.add_argument("--start-min-samples", type=int, default=5)
    ap.add_argument("--start-eps", type=float, default=60.0)
    args = ap.parse_args()

    conn = sqlite3.connect(str(PROJECT_DB))
    legs = load_legs(conn)
    events = load_events(conn)
    conn.close()
    trajs = [e["trajectory"] for e in events if e["trajectory"] and len(e["trajectory"]) >= 4]
    print(f"loaded {len(trajs)} trajectories (>=4 pts), {len(legs)} legs")
    window = db_processed_window()
    manual = manual_for_window(window)

    # --- Step 1: origins from START points; heading from origin->center geometry ---
    starts = np.array([t[0] for t in trajs], dtype=float)
    labels = dbscan_like(starts, args.start_eps, args.start_min_samples)
    blobs = []
    for zid in sorted(set(labels)):
        if zid == -1:
            continue
        idx = np.where(labels == zid)[0]
        centroid = starts[idx].mean(axis=0)
        tails = [_tail_heading(trajs[i]) for i in idx]
        blobs.append({"centroid": (float(centroid[0]), float(centroid[1])),
                      "count": int(len(idx)), "tail_median": _circular_median_deg(tails)})
    if not blobs:
        print("No origin blobs found — lower --start-min-samples."); return 1
    center = (float(np.mean([b["centroid"][0] for b in blobs])),
              float(np.mean([b["centroid"][1] for b in blobs])))
    for b in blobs:
        name, dist = _nearest(b["centroid"], APPROACH_ANCHORS)
        b["approach"] = name
        b["anchor_dist"] = dist
        b["leg_id"] = APPROACH_TO_LEG[name]
        # reference_heading = approach travel direction = origin -> intersection center
        b["reference_heading"] = _heading_of(center[0] - b["centroid"][0],
                                              center[1] - b["centroid"][1])
    print(f"\n=== Step 1: {len(blobs)} origin blobs (center~{tuple(round(c) for c in center)}) ===")
    for b in blobs:
        print(f"  blob -> {b['approach']:<22} leg L{b['leg_id']} count={b['count']:<4} "
              f"origin={tuple(round(c) for c in b['centroid'])} "
              f"new_ref={b['reference_heading']:.0f} anchor_dist={b['anchor_dist']:.0f}")

    # --- Step 2: label-free shape clustering ---
    feats = np.array([extract_shape_features(t) for t in trajs])
    mu, sd = feats.mean(0), feats.std(0) + 1e-9
    Z = linkage((feats - mu) / sd, method="ward")
    clabels = fcluster(Z, t=args.k, criterion="maxclust")
    clusters = []
    for cid in sorted(set(clabels)):
        idx = [i for i in range(len(trajs)) if clabels[i] == cid]
        if len(idx) < args.min_support:
            continue
        members = [trajs[i] for i in idx]
        start_c = np.mean([m[0] for m in members], axis=0)
        end_c = np.mean([m[-1] for m in members], axis=0)
        clusters.append({
            "count": len(idx),
            "polyline": _fit_mean_polyline(members, POLYLINE_PTS),
            "tail_median": _circular_median_deg([_tail_heading(m) for m in members]),
            "start_centroid": (float(start_c[0]), float(start_c[1])),
            "end_centroid": (float(end_c[0]), float(end_c[1])),
        })
    covered = sum(c["count"] for c in clusters)
    print(f"\n=== Step 2: {len(clusters)} shape clusters (K={args.k}, min_support={args.min_support}) "
          f"covering {covered}/{len(trajs)} traj ({covered/len(trajs)*100:.0f}%) ===")

    # Assign each cluster to an origin blob (by start centroid) + dest leg (by end centroid).
    for c in clusters:
        ob, _ = min(((b, math.dist(c["start_centroid"], b["centroid"])) for b in blobs),
                    key=lambda t: t[1])
        c["origin_leg"] = ob["leg_id"]
        c["approach"] = ob["approach"]
        c["ref_heading"] = ob["reference_heading"]
        db_, _ = min(((b, math.dist(c["end_centroid"], b["centroid"])) for b in blobs),
                     key=lambda t: t[1])
        c["dest_leg"] = db_["leg_id"]

    # --- Step 3: per-approach assignment of clusters -> movements ---
    def expected_exit(ref, mvt):
        return {"thru": ref, "left": (ref - 90) % 360,
                "right": (ref + 90) % 360, "uturn": (ref + 180) % 360}[mvt]

    print(f"\n=== Step 3: assignment (feasibility sector {FEASIBILITY_SECTOR_DEG:.0f} deg) ===")
    paths = []
    for b in blobs:
        appr = b["approach"]
        cls = sorted([c for c in clusters if c["origin_leg"] == b["leg_id"]],
                     key=lambda c: -c["count"])
        remaining = dict(manual[appr])  # movement -> remaining budget
        for c in cls:
            feas = [m for m in ALL_MVT
                    if _ang_diff(c["tail_median"], expected_exit(b["reference_heading"], m))
                    <= FEASIBILITY_SECTOR_DEG]
            if not feas:
                c["movement"] = "unassigned"
                continue
            # pick feasible movement with the largest remaining manual budget
            m = max(feas, key=lambda mm: remaining.get(mm, 0))
            c["movement"] = m
            remaining[m] = max(0.0, remaining.get(m, 0) - c["count"])
            paths.append({
                "origin_leg_id": b["leg_id"], "destination_leg_id": c["dest_leg"],
                "movement_label": {"thru": "through", "uturn": "u_turn"}.get(m, m),
                "polyline": [[round(x, 1), round(y, 1)] for x, y in c["polyline"]],
                "supporting_count": c["count"], "source": "data-driven",
            })
            print(f"  L{b['leg_id']} {appr:<20} cluster n={c['count']:<3} "
                  f"tail={c['tail_median']:.0f} -> {m:<6} (dest L{c['dest_leg']})")

    # --- Validation: assigned per-(approach, movement) vs manual ---
    print(f"\n=== Assigned vs manual (window {window[0]:.0f}-{window[1]:.0f}s) ===")
    assigned = {}
    for c in clusters:
        if c.get("movement") in ALL_MVT:
            assigned[(c["approach"], c["movement"])] = \
                assigned.get((c["approach"], c["movement"]), 0) + c["count"]
    print(f"{'approach':<22} {'mvt':<6} {'manual':>7} {'assigned':>9}")
    for appr in APPROACH_ANCHORS:
        for m in ALL_MVT:
            man = manual[appr][m]
            asg = assigned.get((appr, m), 0)
            if man < 0.5 and asg == 0:
                continue
            print(f"{appr:<22} {m:<6} {man:>7.1f} {asg:>9}")

    out = {
        "project": "97a7849a", "camera_id": 1, "window_sec": list(window),
        "intersection_center": list(center),
        "updated_legs": [{"leg_id": b["leg_id"], "approach": b["approach"],
                          "origin_point": [round(b["centroid"][0], 1), round(b["centroid"][1], 1)],
                          "reference_heading": round(b["reference_heading"], 1)} for b in blobs],
        "paths": paths,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nwrote suggestion -> {args.out}  ({len(paths)} paths, {len(blobs)} legs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
