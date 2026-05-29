"""Correct (frame-aligned) dedup ceiling for OC-SORT SB-through.

Duplicates must be SAME PLACE AT THE SAME FRAME (whole-curve similarity is wrong
— all throughs share the lane). Uses per-frame (f,x,y). Union-find merges:
  (overlap)    two tracks share >= ovl frames with median per-frame sep <= sep px
  (sequential) A ends, B starts within gap frames and join px of A's tail
Reports SB-through track count after merging = the best dedup can do.

Usage:  py scripts/dedup_ceiling.py
"""
from __future__ import annotations

import argparse, math, sqlite3, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import (
    DetectionCacheReader, compute_video_content_hash, parquet_path, DEFAULT_VARIANT)
from backend.services.tracker import create_tracker_backend


def is_sb_through(pts):
    if len(pts) < 5: return False
    x0, y0 = pts[0][1], pts[0][2]; x1, y1 = pts[-1][1], pts[-1][2]
    return (x1 < x0 - 120) and (abs(y1 - y0) < 80) and (180 <= np.median([p[2] for p in pts]) <= 275)


def merge_count(tracks, sep, ovl, gap, join):
    n = len(tracks); parent = list(range(n))
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[rb] = ra
    maps = [{f: (x, y) for f, x, y in t} for t in tracks]
    span = [(t[0][0], t[-1][0]) for t in tracks]
    for i in range(n):
        for j in range(i + 1, n):
            if min(span[i][1], span[j][1]) - max(span[i][0], span[j][0]) >= ovl:
                common = set(maps[i]) & set(maps[j])
                if len(common) >= ovl:
                    seps = [math.hypot(maps[i][f][0]-maps[j][f][0], maps[i][f][1]-maps[j][f][1]) for f in common]
                    if np.median(seps) <= sep:
                        union(i, j); continue
            for a, b in ((i, j), (j, i)):
                g = span[b][0] - span[a][1]
                if 0 <= g <= gap:
                    d = math.hypot(tracks[a][-1][1]-tracks[b][0][1], tracks[a][-1][2]-tracks[b][0][2])
                    if d <= join:
                        union(i, j); break
    return len({find(i) for i in range(n)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--activation", type=float, default=0.25)
    args = ap.parse_args()
    conn = sqlite3.connect("data/projects/97a7849a/project.db")
    v = conn.execute("SELECT path,file_size_bytes,total_frames FROM videos WHERE camera_id=1 ORDER BY sort_order LIMIT 1").fetchone()
    conn.close()
    chash, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path("97a7849a", 1, chash, DEFAULT_VARIANT)
    frames = list(DetectionCacheReader(pq).iter_frames())
    be = create_tracker_backend("ocsort", track_activation_threshold=args.activation)
    trajs = defaultdict(list)
    for fidx, dets in frames:
        for tk in be.update(dets, fidx):
            trajs[tk["track_id"]].append((fidx, float(tk["center"][0]), float(tk["center"][1])))
    sb = [t for t in trajs.values() if is_sb_through(t)]
    print(f"OC-SORT SB-through tracks: {len(sb)}  (manual 424, ByteTrack 425)\n")
    print(f"{'overlap-only':<22}{merge_count(sb, 35, 5, 0, 0):>6}")
    print(f"{'overlap+seq tight':<22}{merge_count(sb, 35, 5, 45, 55):>6}")
    print(f"{'overlap+seq loose':<22}{merge_count(sb, 45, 5, 90, 75):>6}")
    print(f"{'aggressive':<22}{merge_count(sb, 60, 4, 150, 90):>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
