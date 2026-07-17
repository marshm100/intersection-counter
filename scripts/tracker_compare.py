"""A/B two trackers on the SAME cached detections: does OC-SORT reconstruct the
turn trajectories that IoU-only ByteTrack fragments?

The detection set is held constant (the cache), so any difference in captured
turns is purely the tracker. This is the Step-0 turn-tracking audit the OC-SORT
seam was gated on.

Usage:  py scripts/tracker_compare.py
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

from backend.config import TRACKER_ACTIVATION_THRESHOLD
from backend.services.detection_cache import (
    DetectionCacheReader, compute_video_content_hash, parquet_path, read_metadata,
)
from backend.services.tracker import create_tracker_backend


def _net_turn(pts):
    if len(pts) < 4:
        return 0.0
    def hd(a, b):
        return math.degrees(math.atan2(b[0] - a[0], -(b[1] - a[1])))
    k = max(1, len(pts) // 4)
    return (hd(pts[-1 - k], pts[-1]) - hd(pts[0], pts[k]) + 180) % 360 - 180


def _path_len(p):
    return sum(math.hypot(p[i][0] - p[i-1][0], p[i][1] - p[i-1][1]) for i in range(1, len(p)))


def run_backend(name, frames, **kw):
    """frames: list of (frame_idx, [det_dict,...]) ascending. Returns trajectories."""
    be = create_tracker_backend(name, **kw)
    trajs = defaultdict(list)
    for fidx, dets in frames:
        for tk in be.update(dets, fidx):
            trajs[tk["track_id"]].append(tuple(tk["center"]))
    return list(trajs.values())


def summarize(name, trajs, min_pts, min_path, turn_deg):
    keep = [p for p in trajs if len(p) >= min_pts and _path_len(p) >= min_path]
    turns = [p for p in keep if abs(_net_turn(p)) >= turn_deg]
    spans = [abs(p[-1][0] - p[0][0]) for p in keep] or [0]
    print(f"  {name:<10} tracks(total)={len(trajs):<5} substantial={len(keep):<4} "
          f"TURNS={len(turns):<4} med_xspan={np.median(spans):.0f}px "
          f"med_pts={int(np.median([len(p) for p in keep])) if keep else 0}")
    return len(turns), len(keep)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--activation", type=float, default=TRACKER_ACTIVATION_THRESHOLD)
    ap.add_argument("--min-pts", type=int, default=10)
    ap.add_argument("--min-path", type=float, default=120.0)
    ap.add_argument("--turn-deg", type=float, default=45.0)
    args = ap.parse_args()

    conn = sqlite3.connect(str(Path("data/projects") / args.project / "project.db"))
    v = conn.execute("SELECT path,file_size_bytes,total_frames FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
                     (args.camera,)).fetchone()
    conn.close()
    chash, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pqp = parquet_path(args.project, args.camera, chash)
    meta = read_metadata(pqp) or {}
    print(f"cache: model={meta.get('model')} imgsz={meta.get('imgsz')} conf={meta.get('confidence')}  "
          f"activation={args.activation}")

    frames = list(DetectionCacheReader(pqp).iter_frames())
    print(f"frames with detections: {len(frames)}\n")

    kw = dict(track_activation_threshold=args.activation)
    print("[TURN CAPTURE on identical detections]")
    bt_turns, bt_keep = summarize("bytetrack", run_backend("bytetrack", frames, **kw),
                                  args.min_pts, args.min_path, args.turn_deg)
    oc_turns, oc_keep = summarize("ocsort", run_backend("ocsort", frames, **kw),
                                  args.min_pts, args.min_path, args.turn_deg)
    print(f"\nVERDICT: turns  bytetrack={bt_turns}  ocsort={oc_turns}")
    if oc_turns > bt_turns * 1.3:
        print("  >> OC-SORT recovers materially more turns from the SAME detections => TRACKING gap confirmed + fix in hand.")
    elif oc_turns <= bt_turns:
        print("  >> No tracking gain => detection consistency is the binding constraint, not the tracker.")
    else:
        print("  >> Modest gain — tracking helps but isn't the whole story.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
