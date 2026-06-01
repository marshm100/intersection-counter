"""Derive the EB-right (L24->L22) turn path from RAW BoT tracker tracks and append
it to a bank. (docs/reid_project_plan_2026-06-01.md, Stage E.)

The pipeline drops ~11/13 EB-right tracks at destination attribution (no EB-right
path in the bank -> the fallback derive_movement returns insufficient_data ->
dropped). But the bank can't derive an EB-right path from EVENTS because the events
were dropped — a chicken-and-egg. We break it by deriving the path from the RAW
tracker tracks (BoT sustains ~11 EB-right), which never hit the pipeline event loss.
Adding the path lets the joint scorer keep + correctly attribute these turns.

This is the same data-driven path mechanism the bank already uses, just sourced from
raw tracker output for a sparse cross-street cell the post-pipeline derivation misses.

Usage:  py scripts/add_ebright_path.py --in evaluations/recal_cam1_odturns.json \
            --out evaluations/recal_cam1_odturns_ebr.json
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path)
from backend.services.tracker import create_tracker_backend
from scripts.auto_calibrate import _fit_mean_polyline
from groundtruth import VIDEO_START
from od_accuracy import manual_od_by_cell

# All (origin_leg, dest_leg, movement) turn cells (cam1 OD geometry, from
# recalibrate_camera.OD_DEST with corrected labels {22:NB,23:SB,24:EB,25:WB}). The
# script SKIPS any cell already present in the bank (the event-based derivation
# covered it) and any with < min_support raw tracks — so it only FILLS sparse
# cross-street cells the post-pipeline derivation missed (cam1: just EB-right; the
# rest are camera-general for Phase D corridor rollout).
CELLS = [
    (22, 24, "left"),    # NB-left  -> EB
    (22, 25, "right"),   # NB-right -> WB
    (23, 25, "left"),    # SB-left  -> WB
    (23, 24, "right"),   # SB-right -> EB
    (24, 23, "left"),    # EB-left  -> SB
    (24, 22, "right"),   # EB-right -> NB  (the cam1 sparse-loss cell)
    (25, 22, "left"),    # WB-left  -> NB
    (25, 23, "right"),   # WB-right -> SB
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="evaluations/recal_cam1_odturns.json")
    ap.add_argument("--out", default="evaluations/recal_cam1_odturns_ebr.json")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--min-support", type=int, default=5)
    ap.add_argument("--min-path", type=float, default=100.0)
    ap.add_argument("--poly-pts", type=int, default=15)
    args = ap.parse_args()

    c = sqlite3.connect("data/projects/97a7849a/project.db")
    v = c.execute("SELECT path,file_size_bytes,total_frames,fps FROM videos WHERE camera_id=1 ORDER BY sort_order LIMIT 1").fetchone()
    legs = {lid: json.loads(oz)[0] for lid, oz in c.execute("SELECT leg_id,origin_zone FROM legs WHERE camera_id=1") if oz}
    c.close()
    fps = float(v[3])
    ch, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path("97a7849a", 1, ch, DEFAULT_VARIANT)
    f_lo = int((VIDEO_START.replace(hour=int(args.start_hms[:2]), minute=int(args.start_hms[3:5])) - VIDEO_START).total_seconds() * fps)
    f_hi = f_lo + int(args.minutes * 60 * fps)
    frames = [(f, ds) for f, ds in DetectionCacheReader(pq).iter_frames() if f_lo <= f < f_hi]

    def nearest(pt):
        return min(legs, key=lambda l: math.hypot(pt[0]-legs[l][0], pt[1]-legs[l][1]))

    def path_len(pts):
        return sum(math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1]) for i in range(1, len(pts)))

    be = create_tracker_backend("botsort", track_activation_threshold=0.25, frame_rate=int(fps))
    tr = defaultdict(list)
    for fidx, dets in frames:
        for tk in be.update(dets, fidx):
            tr[tk["track_id"]].append(tuple(tk["center"]))

    # Real-movement gate: only fill a cell that Miovision says is a REAL turn in
    # this WINDOW (manual >= min_support). Without this, through-FRAGMENTS that
    # geometrically end mid-arterial (e.g. NB-through stubs near L25) would have
    # >=5 raw tracks and we'd add a PHANTOM NB-right path, inflating the very
    # phantom we fight. (Window-restricted — whole-day totals defeat the gate.)
    manual_by_cell = manual_od_by_cell(args.start_hms, args.minutes)

    bank = json.loads(Path(args.inp).read_text())
    existing = {(p["origin_leg_id"], p["destination_leg_id"]) for p in bank["paths"]}
    added = []
    for o, d, mv in CELLS:
        man = manual_by_cell.get((o, d), 0.0)
        if man < args.min_support:
            print(f"  cell {o}->{d} {mv}: manual {man:.0f} (< {args.min_support}) — not a real movement, SKIP")
            continue
        if (o, d) in existing:
            print(f"  cell {o}->{d}: already in bank — SKIP")
            continue
        grp = [pts for pts in tr.values()
               if len(pts) >= 4 and path_len(pts) >= args.min_path
               and nearest(pts[0]) == o and nearest(pts[-1]) == d]
        if len(grp) < args.min_support:
            print(f"  cell {o}->{d} {mv}: only {len(grp)} raw tracks (< {args.min_support}) — SKIP")
            continue
        poly = _fit_mean_polyline(grp, args.poly_pts)
        bank["paths"].append({
            "origin_leg_id": o, "destination_leg_id": d, "movement_label": mv,
            "polyline": [[round(x, 1), round(y, 1)] for x, y in poly],
            "supporting_count": len(grp), "source": "data-driven-rawtrack"})
        added.append((o, d, mv, len(grp)))
        print(f"  cell {o}->{d} {mv}: {len(grp)} raw tracks -> path added")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(bank, indent=2))
    print(f"wrote {args.out}  ({len(bank['paths'])} paths, +{len(added)} from raw tracks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
