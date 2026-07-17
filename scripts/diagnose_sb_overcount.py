"""Diagnose the SB-through OC-SORT overcount (631 vs manual 424; ByteTrack 412).

Root-cause question: WHAT are the ~200 extra SB-through tracks OC-SORT emits?
Three candidate mechanisms, three different fixes:
  (A) OVERLAPPING DUPLICATES  — two track_ids on the same vehicle at the same
      time (parallel ghost). Fix: tracker association (det_thresh/use_byte/inertia).
  (B) SEQUENTIAL FRAGMENTS    — one vehicle split into consecutive tracks (A ends
      ~where B begins). Fix: max_age / gap bridging.
  (C) SHORT SPURIOUS          — brief stubs admitted by the loose pipeline filter
      (TRAJECTORY_MIN_POINTS=5 / MIN_DISTANCE_PX=50). Fix: stricter min-track filter.

Runs both backends on the SAME cached detections (detection set held constant, so
any delta is purely the tracker) and characterises the SB-through pool of each.

Usage:  py scripts/diagnose_sb_overcount.py
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


def run_backend(name, frames, **kw):
    """Return {track_id: [(fidx, x, y), ...]} ascending by frame."""
    be = create_tracker_backend(name, **kw)
    trajs = defaultdict(list)
    for fidx, dets in frames:
        for tk in be.update(dets, fidx):
            cx, cy = tk["center"]
            trajs[tk["track_id"]].append((fidx, float(cx), float(cy)))
    return trajs


def path_len(pts):
    return sum(math.hypot(pts[i][1] - pts[i-1][1], pts[i][2] - pts[i-1][2])
               for i in range(1, len(pts)))


def is_sb_through(pts):
    """SB through = westbound along the arterial: x decreases markedly, stays in
    the arterial y-band, low net vertical travel. Origin leg22 (x~433,y~211) ->
    dest leg23 (x~155,y~241)."""
    if len(pts) < 5:
        return False
    x0, y0 = pts[0][1], pts[0][2]
    x1, y1 = pts[-1][1], pts[-1][2]
    ys = [p[2] for p in pts]
    return (x1 < x0 - 120) and (abs(y1 - y0) < 80) and (180 <= np.median(ys) <= 275)


def frame_range(pts):
    return pts[0][0], pts[-1][0]


def overlap_frames(a, b):
    lo = max(a[0][0], b[0][0]); hi = min(a[-1][0], b[-1][0])
    return max(0, hi - lo)


def median_sep_during_overlap(a, b):
    """Median centroid distance between two tracks over their overlapping frames."""
    da = {f: (x, y) for f, x, y in a}
    db = {f: (x, y) for f, x, y in b}
    common = sorted(set(da) & set(db))
    if not common:
        return None
    d = [math.hypot(da[f][0] - db[f][0], da[f][1] - db[f][1]) for f in common]
    return float(np.median(d)), len(common)


def characterize(pool, min_pts, min_path, dup_sep_px=35.0, dup_min_overlap=5,
                 frag_gap_max=60, frag_join_px=60.0):
    """pool: list of trajs (each [(f,x,y)]). Return diagnostic counts."""
    n_total = len(pool)
    substantial = [p for p in pool if len(p) >= min_pts and path_len(p) >= min_path]
    short = [p for p in pool if not (len(p) >= min_pts and path_len(p) >= min_path)]

    # (A) overlapping duplicates: pairs sharing >=dup_min_overlap frames within dup_sep_px
    dup_pairs = 0
    dup_members = set()
    P = pool
    for i in range(len(P)):
        for j in range(i + 1, len(P)):
            if overlap_frames(P[i], P[j]) < dup_min_overlap:
                continue
            ms = median_sep_during_overlap(P[i], P[j])
            if ms and ms[0] <= dup_sep_px and ms[1] >= dup_min_overlap:
                dup_pairs += 1
                dup_members.add(i); dup_members.add(j)

    # (B) sequential fragments: track A ends, track B starts within frag_gap_max
    # frames and frag_join_px of A's last point (and B continues forward).
    frag_pairs = 0
    frag_members = set()
    for i in range(len(P)):
        ai_end_f, ai_end = P[i][-1][0], (P[i][-1][1], P[i][-1][2])
        for j in range(len(P)):
            if i == j:
                continue
            bj_start_f, bj_start = P[j][0][0], (P[j][0][1], P[j][0][2])
            gap = bj_start_f - ai_end_f
            if 0 < gap <= frag_gap_max:
                d = math.hypot(ai_end[0] - bj_start[0], ai_end[1] - bj_start[1])
                if d <= frag_join_px:
                    frag_pairs += 1
                    frag_members.add(i); frag_members.add(j)

    return {
        "total": n_total,
        "substantial": len(substantial),
        "short_spurious": len(short),
        "overlap_dup_pairs": dup_pairs,
        "overlap_dup_tracks": len(dup_members),
        "seq_frag_pairs": frag_pairs,
        "seq_frag_tracks": len(frag_members),
        "med_pts": int(np.median([len(p) for p in substantial])) if substantial else 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--activation", type=float, default=0.25)
    ap.add_argument("--min-pts", type=int, default=5)       # pipeline filter
    ap.add_argument("--min-path", type=float, default=50.0)  # pipeline filter
    ap.add_argument("--greedy-gate", type=float, default=35.0)
    ap.add_argument("--greedy-gap", type=int, default=8)
    args = ap.parse_args()

    conn = sqlite3.connect(str(Path("data/projects") / args.project / "project.db"))
    v = conn.execute("SELECT path,file_size_bytes,total_frames FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
                     (args.camera,)).fetchone()
    conn.close()
    chash, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path(args.project, args.camera, chash, DEFAULT_VARIANT)
    frames = list(DetectionCacheReader(pq).iter_frames())
    print(f"cache={pq.name}  frames_with_dets={len(frames)}  "
          f"pipeline_filter: min_pts={args.min_pts} min_path={args.min_path}px\n")

    # Tracker-independent reference: naive greedy nearest-neighbour linker on the
    # SAME detections. This is "what the detections alone support" — a yardstick
    # that neither ByteTrack nor OC-SORT biases. Convert its output to (f,x,y).
    by_frame = {f: [(d["center"][0], d["center"][1]) for d in dets] for f, dets in frames}
    greedy = link_detections(by_frame, gate_px=args.greedy_gate, max_gap=args.greedy_gap)
    greedy_tr = [[(f, x, y) for f, (x, y) in zip(tk["frames"], tk["pts"])] for tk in greedy]
    g_sb = [p for p in greedy_tr if is_sb_through(p)]
    print(f"[greedy-linker ref]  gate={args.greedy_gate}px max_gap={args.greedy_gap}  "
          f"all_tracks={len(greedy_tr)}  SB-through={len(g_sb)}\n")

    kw = dict(track_activation_threshold=args.activation)
    for name in ("bytetrack", "ocsort"):
        trajs = run_backend(name, frames, **kw)
        allp = list(trajs.values())
        sb = [p for p in allp if is_sb_through(p)]
        d = characterize(sb, args.min_pts, args.min_path)
        # wide-gap fragment check: duplicates separated by a long OC-SORT coast
        dwide = characterize(sb, args.min_pts, args.min_path, frag_gap_max=150)
        print(f"[{name}]  all_tracks={len(allp)}  SB-through={len(sb)} "
              f"(substantial={d['substantial']} short_spurious={d['short_spurious']} med_pts={d['med_pts']})")
        print(f"    overlapping-duplicate pairs={d['overlap_dup_pairs']} "
              f"(tracks involved={d['overlap_dup_tracks']})")
        print(f"    sequential-fragment pairs: gap<=60={d['seq_frag_pairs']}  "
              f"gap<=150={dwide['seq_frag_pairs']} (tracks<=150={dwide['seq_frag_tracks']})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
