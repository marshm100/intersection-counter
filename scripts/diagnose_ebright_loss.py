"""Pinpoint WHERE the pipeline loses EB-right (EB->NB, L24->L22) tracks.

Raw BoT sustains ~11 EB-right tracks but the pipeline event layer keeps only ~2-5
(memory project_leg_labels_swapped). This wraps _finalize_vehicle_data to record the
FATE of every finalized track — start/end nearest-leg, whether an origin was assigned
at entry (None -> dropped at the no-origin gate, pipeline.py:682), whether it was
dropped as insufficient_data, and the final origin/movement written. Then it tallies
the EB-right geometric cell so we can see the exact drop mechanism before fixing it.

Usage:  py scripts/diagnose_ebright_loss.py [--reid-cache <npz>]
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import get_processing_mode_config
from backend.database import get_calibration_params, list_trims
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path)
from backend.services.pipeline import ProcessingPipeline
from reprocess_camera import _load_camera_context
from test_recal_effect import list_paths_for_camera_tmp
from groundtruth import VIDEO_START


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suggestion", default="evaluations/recal_cam1_odturns.json")
    ap.add_argument("--reid-cache", default=None)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--out-db", default="data/projects/97a7849a/_hybrid_tmp/_ebdiag.db")
    args = ap.parse_args()
    camera = 1

    conn = sqlite3.connect("data/projects/97a7849a/project.db")
    ctx = _load_camera_context(conn, camera)
    conn.close()
    video = ctx["video"]; fps = float(video["fps"])
    calib = get_calibration_params("97a7849a", ctx["intersection_id"])
    mode_cfg = get_processing_mode_config("balanced")
    sug = json.loads(Path(args.suggestion).read_text())

    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    start = (t0 - VIDEO_START).total_seconds()
    s = int(start * fps); e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"),
                                          total_frames=video["total_frames"])
    pq = parquet_path("97a7849a", camera, chash, DEFAULT_VARIANT)

    tdb = Path(args.out_db)
    shutil.copy2("data/projects/97a7849a/project.db", tdb)
    c = sqlite3.connect(str(tdb))
    with c:
        c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (camera,))
        now = datetime.now().isoformat()
        for p in sug.get("paths", []):
            if p.get("destination_leg_id") is None:
                continue
            c.execute("INSERT OR REPLACE INTO intersection_paths (camera_id, origin_leg_id, destination_leg_id, polyline, movement_label, supporting_count, source, created_at) "
                      "VALUES (?,?,?,?,?,?, 'data-driven', ?)",
                      (camera, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                       p["movement_label"], p.get("supporting_count", 0), now))
        c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (camera,))
    c.close()
    c = sqlite3.connect(str(tdb)); rctx = _load_camera_context(c, camera); c.close()
    legs = {lg["leg_id"]: lg["origin_zone"][0] for lg in rctx["legs"] if lg.get("origin_zone")}

    def nearest(pt):
        return min(legs, key=lambda l: math.hypot(pt[0] - legs[l][0], pt[1] - legs[l][1]))

    tracker_kwargs = None
    if args.reid_cache:
        from reid_embedding_cache import ReidEmbeddingCache
        tracker_kwargs = {"with_reid": True, "reid_embeddings": ReidEmbeddingCache(args.reid_cache)}

    paths = list_paths_for_camera_tmp(tdb, camera)
    pipe = ProcessingPipeline(
        project_id="97a7849a", db_path=str(tdb), video_path=video["path"], legs=rctx["legs"],
        fps=fps, video_start_time=video["recording_start_datetime"], video_id=video["video_id"],
        yolo_model=mode_cfg["yolo_model"], yolo_imgsz=mode_cfg["yolo_imgsz"], yolo_confidence=mode_cfg["yolo_confidence"],
        detection_skip=mode_cfg["detection_skip"], tracker_match_threshold=mode_cfg.get("tracker_match_threshold"),
        tracker_activation_threshold=0.25, calibration_params=calib, paths=paths,
        tracker_backend="botsort", tracker_kwargs=tracker_kwargs)
    pipe._v3_camera_id = camera
    pipe._v3_trim_id = (list_trims("97a7849a", ctx["intersection_id"]) or [{"trim_id": None}])[0]["trim_id"]

    records = []
    orig = pipe._finalize_vehicle_data

    def wrap(track_id, vehicle, frame_number):
        traj = vehicle.get("trajectory", [])
        sl = nearest(traj[0]) if len(traj) >= 2 else None
        el = nearest(traj[-1]) if len(traj) >= 2 else None
        entry_origin = vehicle.get("origin_leg_id")
        ins0 = pipe.n_insufficient_data
        orig(track_id, vehicle, frame_number)
        rec = {"sl": sl, "el": el, "npts": len(traj),
               "entry_origin": entry_origin,
               "final_origin": vehicle.get("origin_leg_id"),
               "dropped_insuf": pipe.n_insufficient_data > ins0}
        records.append(rec)

    pipe._finalize_vehicle_data = wrap
    pipe.process_cached(DetectionCacheReader(pq), s, e, detection_skip=mode_cfg["detection_skip"])

    # --- analysis ---
    eb = [r for r in records if r["sl"] == 24 and r["el"] == 22 and r["npts"] >= 4]
    all24 = [r for r in records if r["sl"] == 24 and r["npts"] >= 4]
    print(f"ReID={'on' if args.reid_cache else 'off'}  total finalized tracks={len(records)}")
    print(f"\ntracks STARTING near L24 (EB approach), >=4pts: {len(all24)}")
    print(f"  end-leg distribution: {dict(Counter(r['el'] for r in all24))}  (22=NB/EB-right, 23=SB/EB-left)")
    print(f"\nEB-RIGHT geometric (start L24, end L22), >=4pts: {len(eb)}  (raw BoT sustains ~11)")
    print(f"  entry_origin (None = dropped at no-origin gate): {dict(Counter(r['entry_origin'] for r in eb))}")
    print(f"  final_origin (after joint scorer):               {dict(Counter(r['final_origin'] for r in eb))}")
    print(f"  dropped as insufficient_data: {sum(r['dropped_insuf'] for r in eb)}")
    kept = [r for r in eb if r['final_origin'] is not None and not r['dropped_insuf']]
    print(f"  -> KEPT as an event: {len(kept)}   DROPPED: {len(eb) - len(kept)}")
    print(f"  npts of EB-right tracks: {sorted(r['npts'] for r in eb)}")
    # fate of dropped ones
    dropped = [r for r in eb if not (r['final_origin'] is not None and not r['dropped_insuf'])]
    no_origin = [r for r in dropped if r['entry_origin'] is None and r['final_origin'] is None]
    print(f"  dropped breakdown: no-origin gate={len(no_origin)}, "
          f"insufficient_data={sum(r['dropped_insuf'] for r in dropped)}, "
          f"other={len(dropped)-len(no_origin)-sum(r['dropped_insuf'] for r in dropped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
