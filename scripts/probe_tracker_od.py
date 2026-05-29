"""Compare trackers on the SAME cached detections: how many of each OD movement
does each tracker SUSTAIN? Greedy NN-link is the detection-supported ceiling;
OC-SORT fragments sharp cross-street turns (EB); does BoT-SORT (less
momentum-reliant association) sustain them?

Runs each backend faithfully (real cached bboxes), assigns each track an OD cell
by (start nearest origin-leg, end nearest dest-leg), tallies. Focus: EB-left
(EB->SB) and EB-right (EB->NB) — greedy got 24/22, OC-SORT ~4.

Usage:  py scripts/probe_tracker_od.py --trackers ocsort,botsort
"""
from __future__ import annotations
import argparse, json, math, sqlite3, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import (
    DetectionCacheReader, compute_video_content_hash, parquet_path, DEFAULT_VARIANT)
from backend.services.tracker import create_tracker_backend
from detection_vs_tracking_probe import link_detections

LEG_NAME = {22: "NB", 23: "SB", 24: "EB", 25: "WB"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trackers", default="ocsort,botsort")
    ap.add_argument("--min-pts", type=int, default=6)
    ap.add_argument("--min-path", type=float, default=100.0)
    args = ap.parse_args()
    c = sqlite3.connect("data/projects/97a7849a/project.db")
    v = c.execute("SELECT path,file_size_bytes,total_frames FROM videos WHERE camera_id=1 ORDER BY sort_order LIMIT 1").fetchone()
    legs = {lid: json.loads(oz)[0] for lid, oz in c.execute("SELECT leg_id,origin_zone FROM legs WHERE camera_id=1") if oz}
    c.close()
    ch, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path("97a7849a", 1, ch, DEFAULT_VARIANT)
    frames = list(DetectionCacheReader(pq).iter_frames())

    def nearest(pt):
        return min(legs, key=lambda lid: math.hypot(pt[0]-legs[lid][0], pt[1]-legs[lid][1]))

    def path_len(pts):
        return sum(math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1]) for i in range(1, len(pts)))

    def od_tally(tracks):
        od = defaultdict(int)
        for pts in tracks:
            if len(pts) >= args.min_pts and path_len(pts) >= args.min_path:
                od[(nearest(pts[0]), nearest(pts[-1]))] += 1
        return od

    # greedy reference
    by_frame = {f: [(d["center"][0], d["center"][1]) for d in ds] for f, ds in frames}
    results = {"greedy": od_tally([tk["pts"] for tk in link_detections(by_frame, gate_px=35.0, max_gap=8)])}
    for name in args.trackers.split(","):
        be = create_tracker_backend(name.strip(), track_activation_threshold=0.25)
        tr = defaultdict(list)
        for fidx, dets in frames:
            for tk in be.update(dets, fidx):
                tr[tk["track_id"]].append(tuple(tk["center"]))
        results[name.strip()] = od_tally(list(tr.values()))

    cells = [(24, 23, "EB-left"), (24, 22, "EB-right"), (22, 24, "NB-left"),
             (23, 24, "SB-right"), (22, 23, "NB-thru"), (23, 22, "SB-thru")]
    print(f"OD-cell track counts (>= {args.min_pts}pts, >={args.min_path:.0f}px). manual: EB-left 27, EB-right 36, NB-left 96, SB-right 34, NB-thru 593, SB-thru 424")
    hdr = f"{'movement':<10}" + "".join(f"{k:>10}" for k in results)
    print(hdr); print("-" * len(hdr))
    for o, d, name in cells:
        print(f"{name:<10}" + "".join(f"{results[k].get((o, d), 0):>10}" for k in results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
