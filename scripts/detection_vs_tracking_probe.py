"""Is the turn signal lost at DETECTION or at TRACKING?

The manual counts were produced by Miovision on the SAME video, so the turns ARE
in this footage. This probe links the cached raw YOLO detections into proto-tracks
with a naive greedy nearest-neighbour linker (NOT our ByteTrack), then counts how
many proto-tracks trace a TURN (large net heading change). Compare to the turn
trajectories our pipeline actually produced:
  - many turn curves in the raw detections, few in our tracks  -> TRACKING gap.
  - no turn curves even in the raw detections                  -> DETECTION gap.

Usage:  py scripts/detection_vs_tracking_probe.py
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import (
    compute_video_content_hash, parquet_path, read_metadata,
)
from replay_attribution_changes import PROJECT_DB, load_events


def _net_turn(pts):
    """Net heading change (deg) entry-segment vs exit-segment of a point list."""
    if len(pts) < 4:
        return 0.0
    def hd(a, b):
        return math.degrees(math.atan2(b[0] - a[0], -(b[1] - a[1])))
    k = max(1, len(pts) // 4)
    entry = hd(pts[0], pts[k]); exit_ = hd(pts[-1 - k], pts[-1])
    return (exit_ - entry + 180) % 360 - 180


def link_detections(by_frame, gate_px=35.0, max_gap=8):
    """Greedy nearest-neighbour linker. Returns list of dicts {pts, frames}."""
    tracks = []          # active: {"pts","frames","last_xy","last_f"}
    done = []
    for f in sorted(by_frame):
        dets = by_frame[f]
        still = []
        for tk in tracks:
            (done if f - tk["last_f"] > max_gap else still).append(tk)
        tracks = still
        used = set()
        for tk in tracks:
            best, bd = None, gate_px
            for i, (x, y) in enumerate(dets):
                if i in used:
                    continue
                d = math.hypot(x - tk["last_xy"][0], y - tk["last_xy"][1])
                if d < bd:
                    bd, best = d, i
            if best is not None:
                used.add(best)
                tk["pts"].append(dets[best]); tk["frames"].append(f)
                tk["last_xy"] = dets[best]; tk["last_f"] = f
        for i, xy in enumerate(dets):
            if i not in used:
                tracks.append({"pts": [xy], "frames": [f], "last_xy": xy, "last_f": f})
    done.extend(tracks)
    return done


def _duty(tk):
    """(duty_cycle, max_internal_gap) for a proto-track."""
    fs = tk["frames"]
    span = fs[-1] - fs[0] + 1
    gaps = [fs[i] - fs[i-1] for i in range(1, len(fs))]
    return len(fs) / span, (max(gaps) if gaps else 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--min-pts", type=int, default=6)
    ap.add_argument("--turn-deg", type=float, default=45.0)
    ap.add_argument("--gate", type=float, default=35.0, help="linker match gate px")
    ap.add_argument("--min-path", type=float, default=0.0,
                    help="min total path length (px) to count as a real track/turn (excludes jitter)")
    ap.add_argument("--parquet", default=None, help="override cache parquet path (e.g. balanced .bak)")
    args = ap.parse_args()

    conn = sqlite3.connect(str(PROJECT_DB))
    v = conn.execute("SELECT path,file_size_bytes,total_frames FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
                     (args.camera,)).fetchone()
    chash, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pqp = Path(args.parquet) if args.parquet else parquet_path(args.project, args.camera, chash)
    meta = read_metadata(pqp) or {}
    print(f"cache: model={meta.get('model')} imgsz={meta.get('imgsz')} conf={meta.get('confidence')}")

    t = pq.read_table(pqp).to_pandas()
    cx = ((t["bbox_x1"] + t["bbox_x2"]) / 2).to_numpy()
    cy = ((t["bbox_y1"] + t["bbox_y2"]) / 2).to_numpy()
    fr = t["frame_idx"].to_numpy()
    by_frame = {}
    for x, y, f in zip(cx, cy, fr):
        by_frame.setdefault(int(f), []).append((float(x), float(y)))

    def _path_len(p):
        return sum(math.hypot(p[i][0]-p[i-1][0], p[i][1]-p[i-1][1]) for i in range(1, len(p)))
    proto = [tk for tk in link_detections(by_frame, gate_px=args.gate)
             if len(tk["pts"]) >= args.min_pts and _path_len(tk["pts"]) >= args.min_path]
    pturn = [tk for tk in proto if abs(_net_turn(tk["pts"])) >= args.turn_deg]
    puturn = [tk for tk in proto if abs(_net_turn(tk["pts"])) >= 135]
    print(f"\n[RAW DETECTIONS -> naive proto-tracks]")
    print(f"  proto-tracks (>= {args.min_pts} pts, path>= {args.min_path:.0f}px): {len(proto)}")
    print(f"  that trace a TURN (|net heading|>= {args.turn_deg:.0f} deg): {len(pturn)}")
    print(f"  of which u-turn-ish (>=135): {len(puturn)}")
    if pturn:
        spans = [abs(tk['pts'][-1][0]-tk['pts'][0][0]) for tk in pturn]
        print(f"  turn proto-track x-span: med={np.median(spans):.0f}px  net-turn examples: "
              f"{[round(_net_turn(tk['pts'])) for tk in pturn[:8]]}")

    # DETECTION CONSISTENCY: duty cycle (dets/frame-span) + max internal gap.
    def _stats(tracks):
        d = [_duty(tk) for tk in tracks]
        duties = [x[0] for x in d]; gaps = [x[1] for x in d]
        return (np.median(duties), np.mean([x >= 0.9 for x in duties]) * 100, np.median(gaps))
    print(f"\n[DETECTION CONSISTENCY]  per proto-track duty cycle = dets / frame-span")
    dm, dpc, gm = _stats(proto)
    print(f"  ALL proto-tracks:  duty med={dm:.2f}  %>=0.9={dpc:.0f}%  max-gap med={gm:.0f}")
    if pturn:
        dm, dpc, gm = _stats(pturn)
        print(f"  TURN proto-tracks: duty med={dm:.2f}  %>=0.9={dpc:.0f}%  max-gap med={gm:.0f}")
    through = [tk for tk in proto if abs(_net_turn(tk["pts"])) < args.turn_deg]
    if through:
        dm, dpc, gm = _stats(through)
        print(f"  THRU proto-tracks: duty med={dm:.2f}  %>=0.9={dpc:.0f}%  max-gap med={gm:.0f}")

    # our pipeline's actual turn trajectories
    ev = load_events(conn); conn.close()
    ours = [e for e in ev if e["trajectory"] and len(e["trajectory"]) >= args.min_pts]
    ours_turn = [e for e in ours if abs(_net_turn(e["trajectory"])) >= args.turn_deg]
    print(f"\n[OUR PIPELINE tracks]  total>= {args.min_pts}pts: {len(ours)}  trace a TURN: {len(ours_turn)}")

    print(f"\nVERDICT: raw-detection turn proto-tracks={len(pturn)} vs our turn tracks={len(ours_turn)}.")
    print("  >> many in raw, few in ours  => TRACKING gap (we fragment turns).")
    print("  >> few in raw too            => DETECTION gap (curve not detected).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
