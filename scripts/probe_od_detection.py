"""Phase A0: are the MISSING EB cross-street turns present in the raw DETECTIONS?

Greedy-links the cached detections (tracker-independent), assigns each proto-track
an origin leg (nearest leg origin to its first point) and dest leg (nearest to its
last point), and tallies the origin->dest matrix. If EB-origin (L24) turning
proto-tracks exist in the raw detections (~manual EB-left 27 + EB-right 36) but the
pipeline emits ~0, the gap is TRACKING/ATTRIBUTION (recoverable). If they're absent
from the raw detections too, it's a DETECTION/sensor-angle limit on this view.

Usage:  py scripts/probe_od_detection.py
"""
from __future__ import annotations
import math, sqlite3, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import (
    DetectionCacheReader, compute_video_content_hash, parquet_path, DEFAULT_VARIANT)
from detection_vs_tracking_probe import link_detections, _net_turn

LEG_NAME = {22: "NB", 23: "SB", 24: "EB", 25: "WB"}


def main() -> int:
    c = sqlite3.connect("data/projects/97a7849a/project.db")
    v = c.execute("SELECT path,file_size_bytes,total_frames FROM videos WHERE camera_id=1 ORDER BY sort_order LIMIT 1").fetchone()
    import json
    legs = {}
    for lid, oz in c.execute("SELECT leg_id, origin_zone FROM legs WHERE camera_id=1"):
        if oz:
            legs[lid] = json.loads(oz)[0]
    c.close()
    print("leg origins:", {LEG_NAME[k]: [round(x) for x in v2] for k, v2 in legs.items()})
    ch, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path("97a7849a", 1, ch, DEFAULT_VARIANT)
    by_frame = {}
    for f, ds in DetectionCacheReader(pq).iter_frames():
        by_frame[f] = [(d["center"][0], d["center"][1]) for d in ds]

    def nearest(pt):
        return min(legs, key=lambda lid: math.hypot(pt[0]-legs[lid][0], pt[1]-legs[lid][1]))

    proto = [tk for tk in link_detections(by_frame, gate_px=35.0, max_gap=8)
             if len(tk["pts"]) >= 6 and sum(math.hypot(tk["pts"][i][0]-tk["pts"][i-1][0], tk["pts"][i][1]-tk["pts"][i-1][1]) for i in range(1, len(tk["pts"]))) >= 100]
    od = defaultdict(int)
    for tk in proto:
        o = nearest(tk["pts"][0]); d = nearest(tk["pts"][-1])
        od[(o, d)] += 1
    print(f"\nproto-tracks (>=6pts, >=100px path): {len(proto)}")
    print("raw-detection OD matrix (origin->dest, nearest-leg):")
    for (o, d), n in sorted(od.items(), key=lambda kv: -kv[1]):
        tag = "  <== EB cross-street turn" if o == 24 and d in (22, 23) else ""
        print(f"  {LEG_NAME[o]}->{LEG_NAME[d]}: {n}{tag}")
    eb_l = od.get((24, 23), 0); eb_r = od.get((24, 22), 0)
    print(f"\nEB-origin turns in RAW detections: EB-left(EB->SB)={eb_l} (manual 27), EB-right(EB->NB)={eb_r} (manual 36)")
    print(">> present in raw  => TRACKING/ATTRIBUTION gap (recoverable). absent => DETECTION/sensor limit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
