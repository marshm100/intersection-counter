"""Stage-2 detector validation: does yolo26l@1280 reduce through-track DUPLICATION
vs yolo26s@960? Run the SAME tracker (BoT-SORT) over each detection-cache variant
for the same window, group raw tracks by (nearest origin leg, nearest dest leg),
and compare the through-cell track counts to the Miovision manual volume. Fewer
raw through-tracks (closer to manual) = less ID duplication = the detector is the
lever.

Usage:
  py scripts/compare_detector_dup.py --camera 5 --minutes 5 \
      --variants balanced_960_skip1 accurate_1280_skip1
"""
from __future__ import annotations
import argparse, math, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services.detection_cache import (
    DetectionCacheReader, compute_video_content_hash, parquet_path)
from backend.services.tracker import create_tracker_backend
from od_accuracy import leg_idx, idx_name, manual_od_by_cell
from groundtruth import VIDEO_START

PROJECT = "97a7849a"


def track_stats(pq, fps, f_lo, f_hi, tracker="bytetrack", min_path=80.0):
    """Run the tracker over the cache window; return (n_frames, n_detections,
    n_tracks_total, n_tracks_long). n_tracks_long (tracks that actually traverse,
    plen>=min_path) is the duplication proxy: fewer long tracks for the same real
    traffic = less ID duplication/fragmentation."""
    frames = [(f, ds) for f, ds in DetectionCacheReader(pq).iter_frames() if f_lo <= f < f_hi]
    be = create_tracker_backend(tracker, track_activation_threshold=0.25, frame_rate=int(fps))
    tr = defaultdict(list)
    ndet = 0
    for fidx, dets in frames:
        ndet += len(dets)
        for tk in be.update(dets, fidx):
            tr[tk["track_id"]].append(tuple(tk["center"]))

    def plen(p):
        return sum(math.hypot(p[i][0]-p[i-1][0], p[i][1]-p[i-1][1]) for i in range(1, len(p)))

    long_tracks = sum(1 for pts in tr.values() if len(pts) >= 4 and plen(pts) >= min_path)
    return len(frames), ndet, len(tr), long_tracks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--variants", nargs="+", default=["balanced_960_skip1", "accurate_1280_skip1"])
    ap.add_argument("--tracker", default="bytetrack", help="bytetrack (shipped through arm) or botsort")
    args = ap.parse_args()
    cam = args.camera

    c = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    v = c.execute("SELECT path,file_size_bytes,total_frames,fps FROM videos "
                  "WHERE camera_id=? ORDER BY sort_order LIMIT 1", (cam,)).fetchone()
    c.close()
    fps = float(v[3])
    ch, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    f_lo = int((t0 - VIDEO_START).total_seconds() * fps)
    f_hi = f_lo + int(args.minutes * 60 * fps)

    man = manual_od_by_cell(args.start_hms, args.minutes, camera_id=cam)
    man_total = sum(man.values())
    print(f"cam{cam} {args.start_hms}+{args.minutes:.0f}min  tracker={args.tracker}  "
          f"manual total vehicles={man_total:.0f}\n")
    print(f"{'variant':<22}{'frames':>8}{'dets':>9}{'tracks':>8}{'long_trk':>9}{'long/manual':>13}")
    for var in args.variants:
        pq = parquet_path(PROJECT, cam, ch, var)
        if not pq.exists():
            print(f"{var:<22}  [cache missing]")
            continue
        nfr, ndet, ntr, nlong = track_stats(pq, fps, f_lo, f_hi, tracker=args.tracker)
        ratio = nlong / man_total if man_total else 0
        print(f"{var:<22}{nfr:>8}{ndet:>9}{ntr:>8}{nlong:>9}{ratio:>12.2f}x")
    print("\nlong_trk closer to manual total (ratio -> 1.0) = less ID duplication/fragmentation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
