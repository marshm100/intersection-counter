"""Settle the SB-through overcount: are OC-SORT's ~576 SB-through tracks ~424
DISTINCT vehicles (=> Miovision undercounts) or ~424 vehicles with ~150 DUPLICATE
track-IDs (=> dedup-at-counting is the robust fix)?

Counts UNIQUE crossings of a virtual tripwire (vertical line x=X0 mid-arterial),
deduped by time+lane: two crossings within `win` frames and `dy` px of each other
are the same physical vehicle (no two real cars occupy one point at one instant).
This is fragmentation/duplication-robust counting — the count = physical vehicles,
not track segments. Run on all three trackers as cross-checks.

Usage:  py scripts/diagnose_sb_tripwire.py
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import (
    DetectionCacheReader, compute_video_content_hash, parquet_path, DEFAULT_VARIANT,
)
from backend.services.tracker import create_tracker_backend
from detection_vs_tracking_probe import link_detections


def is_sb_through(pts):
    if len(pts) < 5:
        return False
    x0, y0 = pts[0][1], pts[0][2]
    x1, y1 = pts[-1][1], pts[-1][2]
    ys = [p[2] for p in pts]
    return (x1 < x0 - 120) and (abs(y1 - y0) < 80) and (180 <= np.median(ys) <= 275)


def crossing(track, x0):
    """Frame and y where the track crosses x=x0 going westbound (x decreasing).
    Linear interp between the straddling points. None if it never crosses."""
    for i in range(1, len(track)):
        f0, xa, ya = track[i-1]
        f1, xb, yb = track[i]
        if (xa - x0) * (xb - x0) <= 0 and xa != xb:
            t = (xa - x0) / (xa - xb)
            return (f0 + t * (f1 - f0), ya + t * (yb - ya))
    return None


def dedup_crossings(crossings, win=15, dy=35.0):
    """crossings: list of (frame, y). Greedy temporal+lane clustering -> n unique."""
    crossings = sorted(crossings)
    clusters = []  # each: (last_frame, y)
    for f, y in crossings:
        hit = None
        for c in clusters:
            if abs(f - c[0]) <= win and abs(y - c[1]) <= dy:
                hit = c
                break
        if hit is None:
            clusters.append([f, y])
        else:
            hit[0] = f  # advance so a slow straggle chains, not double-counts
    return len(clusters)


def run_tracker(name, frames, activation):
    be = create_tracker_backend(name, track_activation_threshold=activation)
    trajs = defaultdict(list)
    for fidx, dets in frames:
        for tk in be.update(dets, fidx):
            cx, cy = tk["center"]
            trajs[tk["track_id"]].append((fidx, float(cx), float(cy)))
    return list(trajs.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--activation", type=float, default=0.25)
    ap.add_argument("--x0", type=float, default=300.0, help="tripwire x (mid-arterial)")
    ap.add_argument("--win", type=int, default=15, help="dedup time window (frames)")
    ap.add_argument("--dy", type=float, default=35.0, help="dedup lane tolerance (px)")
    args = ap.parse_args()

    conn = sqlite3.connect(str(Path("data/projects") / args.project / "project.db"))
    v = conn.execute("SELECT path,file_size_bytes,total_frames FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
                     (args.camera,)).fetchone()
    conn.close()
    chash, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path(args.project, args.camera, chash, DEFAULT_VARIANT)
    frames = list(DetectionCacheReader(pq).iter_frames())
    print(f"tripwire x={args.x0}  dedup win={args.win}f dy={args.dy}px  (manual SB-through ~424)\n")

    sources = {}
    by_frame = {f: [(d["center"][0], d["center"][1]) for d in dets] for f, dets in frames}
    greedy = link_detections(by_frame, gate_px=35.0, max_gap=8)
    sources["greedy"] = [[(f, x, y) for f, (x, y) in zip(tk["frames"], tk["pts"])] for tk in greedy]
    sources["bytetrack"] = run_tracker("bytetrack", frames, args.activation)
    sources["ocsort"] = run_tracker("ocsort", frames, args.activation)

    for name in ("bytetrack", "ocsort", "greedy"):
        sb = [t for t in sources[name] if is_sb_through(t)]
        cr = [crossing(t, args.x0) for t in sb]
        cr = [c for c in cr if c is not None]
        uniq = dedup_crossings(cr, win=args.win, dy=args.dy)
        print(f"[{name:<9}] SB-through tracks={len(sb):>4}  cross x={args.x0:.0f}: {len(cr):>4}  "
              f"UNIQUE (deduped)={uniq:>4}")

    print("\n>> If OC-SORT unique ~= manual 424  => extras are DUPLICATE IDs (dedup-at-counting fixes it).")
    print(">> If OC-SORT unique >> 424          => distinct vehicles (Miovision undercount; different problem).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
