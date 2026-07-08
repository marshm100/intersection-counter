"""PASS 1 of the two-pass architecture (MASTER_PLAN 2c): dump RAW tracks.

Full-frame tracking over a window of the detection cache with ZERO semantics —
no legs, channels, box, or classification. Every confirmed track point is
persisted, so pass 2 (box-clip classify + count) can be re-run in minutes and
NOTHING is lost to shape-matching (the cam2 SB/WB collapse — see
docs/spike_reid_cam2_results_2026-07-08.md).

Mirrors build_bank_gtfree's collection loop (create_tracker_backend + cache
reader + per-camera calib knobs, live-parity ByteTrack by default) but keeps
the per-point FRAME INDEX so pass 2 can timestamp gate crossings and bin
counts by crossing time.

Output: <parquet>.tracks/ directory (memmap-streamed, same pattern as the ReID
sidecar): rows.npy [N,4] float32 = (track_id, frame, cx, cy) in emit order,
count.txt = valid rows. RAM stays flat regardless of window length.

Usage:
  py scripts/dump_raw_tracks.py --camera 2 --variant study_0700 \
     --start-hms 07:00:00 --minutes 120
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.database import get_camera_calibration_params
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path)
from backend.services.tracker import create_tracker_backend
from groundtruth import VIDEO_START


def tracks_path(pq: Path) -> Path:
    return pq.with_name(pq.stem + ".tracks")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=2)
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--variant", default=None)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=120.0)
    ap.add_argument("--backend", default="bytetrack",
                    help="live-parity default; the 2x2 showed tracker family is "
                         "not the cam2 lever (spike results doc)")
    args = ap.parse_args()

    conn = sqlite3.connect(f"data/projects/{args.project}/project.db")
    v = conn.execute("SELECT path,file_size_bytes,total_frames,fps FROM videos "
                     "WHERE camera_id=? ORDER BY sort_order LIMIT 1",
                     (args.camera,)).fetchone()
    conn.close()
    vpath, fsize, total_frames, fps = v[0], v[1], v[2], float(v[3])
    ch, _ = compute_video_content_hash(vpath, file_size_bytes=fsize, total_frames=total_frames)
    pq = parquet_path(args.project, args.camera, ch, args.variant or DEFAULT_VARIANT)
    out = tracks_path(pq)

    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    f_lo = int((t0 - VIDEO_START).total_seconds() * fps)
    f_hi = f_lo + int(args.minutes * 60 * fps)

    calib = get_camera_calibration_params(args.project, args.camera)
    activation = float(calib.get("tracker_activation_threshold") or 0.25)
    match = float(calib.get("tracker_match_threshold") or 0.8)
    buf = float(calib.get("bbox_buffer_scale") or 1.0)
    be = create_tracker_backend(
        args.backend,
        track_activation_threshold=activation,
        minimum_matching_threshold=match,
        frame_rate=int(fps))
    print(f"{args.backend} activation={activation} match={match} buf={buf} "
          f"frames [{f_lo},{f_hi}) cam{args.camera}", flush=True)

    # Upper bound: one emitted point per detection (+20% slack for coasting).
    reader = DetectionCacheReader(pq)
    n_dets = 0
    for fidx, dets in reader.iter_frames():
        if f_lo <= fidx < f_hi:
            n_dets += len(dets)
    cap_rows = int(n_dets * 1.2) + 1000
    print(f"{n_dets} detections in window; pre-sizing {cap_rows} rows", flush=True)

    from numpy.lib.format import open_memmap
    out.mkdir(parents=True, exist_ok=True)
    mm = open_memmap(out / "rows.npy", mode="w+", dtype=np.float32, shape=(cap_rows, 4))

    w = done = 0
    for fidx, dets in DetectionCacheReader(pq).iter_frames():
        if not (f_lo <= fidx < f_hi):
            continue
        if buf != 1.0:
            inflated = []
            for d in dets:
                x1, y1, x2, y2 = d["bbox"]
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                hw, hh = (x2 - x1) * buf / 2, (y2 - y1) * buf / 2
                d = dict(d); d["bbox"] = [cx - hw, cy - hh, cx + hw, cy + hh]
                inflated.append(d)
            dets = inflated
        for t in be.update(dets, fidx):
            if w >= cap_rows:
                raise SystemExit(f"row capacity {cap_rows} exceeded at frame {fidx} "
                                 f"— raise the slack factor")
            cx, cy = t["center"]
            mm[w] = (float(t["track_id"]), float(fidx), float(cx), float(cy))
            w += 1
        done += 1
        if done % 5000 == 0:
            mm.flush()
            print(f"  tracked {done} frames ({w} points)...", flush=True)

    mm.flush(); del mm
    (out / "count.txt").write_text(str(w))
    rows = np.load(out / "rows.npy", mmap_mode="r")[:w]
    n_tracks = len(np.unique(rows[:, 0]))
    print(f"wrote {out}  ({w} points, {n_tracks} tracks)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
