"""Decide the SB-through overcount FIX: coverage-floor vs fragment-stitching.

Root cause established (scripts/diagnose_sb_overcount.py): OC-SORT fragments
westbound throughs; the low 0.28 joint-scorer coverage floor lets each fragment
count as a full SB-through (576-631 vs manual ~424). Two candidate fixes:

  (B) THROUGH-SPECIFIC COVERAGE FLOOR — raise the min coverage for through-
      labelled paths so partial fragments don't count. CLEAN only if the extra
      tracks are low-coverage fragments AND real throughs are high-coverage.
      RISK: late-detected real throughs are also low-coverage -> would drop them.
  (C) FRAGMENT STITCHING — merge tracklets of one vehicle (tail->head continuity)
      before attribution. Tracker-agnostic; preserves truncated-through recall.

This probe, for OC-SORT SB-through tracks:
  1. coverage-fraction distribution vs the SB-through polyline (from the bank),
  2. a greedy stitch simulation -> resulting SB-through count,
so we can see which fix separates phantoms from real vehicles without collateral.

Usage:  py scripts/diagnose_sb_coverage.py
"""
from __future__ import annotations

import argparse
import json
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


def path_len_xy(pts):
    return sum(math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1])
               for i in range(1, len(pts)))


def is_sb_through(pts):
    if len(pts) < 5:
        return False
    x0, y0 = pts[0][1], pts[0][2]
    x1, y1 = pts[-1][1], pts[-1][2]
    ys = [p[2] for p in pts]
    return (x1 < x0 - 120) and (abs(y1 - y0) < 80) and (180 <= np.median(ys) <= 275)


def polyline_cumlen(poly):
    cum = [0.0]
    for i in range(1, len(poly)):
        cum.append(cum[-1] + math.hypot(poly[i][0]-poly[i-1][0], poly[i][1]-poly[i-1][1]))
    return cum


def coverage_fraction(track_xy, poly, cum):
    """Fraction of polyline arc-length spanned by the track: project each track
    point to nearest polyline vertex, take (max-min arc pos)/total."""
    total = cum[-1]
    if total <= 0:
        return 0.0
    positions = []
    for x, y in track_xy:
        best_i, best_d = 0, float("inf")
        for i, (px, py) in enumerate(poly):
            d = (x-px)**2 + (y-py)**2
            if d < best_d:
                best_d, best_i = d, i
        positions.append(cum[best_i])
    return (max(positions) - min(positions)) / total


def stitch(tracks, gap_max=150, join_px=70.0):
    """Greedy tracklet stitching: iteratively merge track A (ends) -> track B
    (starts) when B starts within gap_max frames after A ends and within join_px
    of A's last point. tracks: list of [(f,x,y)] sorted by start frame."""
    tracks = sorted([list(t) for t in tracks], key=lambda t: t[0][0])
    merged = True
    while merged:
        merged = False
        for i in range(len(tracks)):
            if tracks[i] is None:
                continue
            a = tracks[i]
            best_j, best_cost = None, float("inf")
            for j in range(len(tracks)):
                if j == i or tracks[j] is None:
                    continue
                b = tracks[j]
                gap = b[0][0] - a[-1][0]
                if not (0 < gap <= gap_max):
                    continue
                d = math.hypot(a[-1][1]-b[0][1], a[-1][2]-b[0][2])
                if d <= join_px and d < best_cost:
                    best_cost, best_j = d, j
            if best_j is not None:
                tracks[i] = a + tracks[best_j]
                tracks[best_j] = None
                merged = True
        tracks = [t for t in tracks if t is not None]
    return tracks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--activation", type=float, default=0.25)
    ap.add_argument("--bank", default="evaluations/recal_cam1_nbleftonly.json")
    args = ap.parse_args()

    bank = json.loads(Path(args.bank).read_text())
    sb_poly = None
    for p in bank["paths"]:
        if p["origin_leg_id"] == 22 and p["movement_label"] == "through":
            sb_poly = [(x, y) for x, y in p["polyline"]]
    assert sb_poly, "SB-through polyline not found in bank"
    cum = polyline_cumlen(sb_poly)
    print(f"SB-through polyline: {len(sb_poly)} pts, arc-len={cum[-1]:.0f}px\n")

    conn = sqlite3.connect(str(Path("data/projects") / args.project / "project.db"))
    v = conn.execute("SELECT path,file_size_bytes,total_frames FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
                     (args.camera,)).fetchone()
    conn.close()
    chash, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path(args.project, args.camera, chash, DEFAULT_VARIANT)
    frames = list(DetectionCacheReader(pq).iter_frames())

    be = create_tracker_backend("ocsort", track_activation_threshold=args.activation)
    trajs = defaultdict(list)
    for fidx, dets in frames:
        for tk in be.update(dets, fidx):
            cx, cy = tk["center"]
            trajs[tk["track_id"]].append((fidx, float(cx), float(cy)))
    sb = [p for p in trajs.values() if is_sb_through(p)]
    print(f"OC-SORT SB-through tracks: {len(sb)}  (manual target ~424)\n")

    covs = [coverage_fraction([(x, y) for _, x, y in t], sb_poly, cum) for t in sb]
    covs = np.array(covs)
    print("[coverage-fraction distribution of OC-SORT SB-through tracks]")
    for lo, hi in [(0.0,0.28),(0.28,0.4),(0.4,0.6),(0.6,0.8),(0.8,1.01)]:
        n = int(((covs>=lo)&(covs<hi)).sum())
        print(f"   cov [{lo:.2f},{hi:.2f}): {n:>4}")
    print(f"   median coverage={np.median(covs):.2f}\n")
    print("[count surviving a THROUGH coverage floor]  (fix B)")
    for floor in (0.28, 0.4, 0.5, 0.6, 0.7):
        print(f"   floor {floor:.2f}: {int((covs>=floor).sum()):>4} tracks")

    print("\n[fragment-stitch simulation]  (fix C)")
    for gap, join in [(60,60),(90,70),(150,70),(150,90)]:
        st = stitch(sb, gap_max=gap, join_px=join)
        st_sb = [t for t in st if is_sb_through(t)]
        print(f"   stitch gap<={gap} join<={join}px:  {len(sb)} -> {len(st_sb)} SB-through tracks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
