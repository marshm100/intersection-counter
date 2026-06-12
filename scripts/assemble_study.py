"""Assemble FULL-STUDY events for a camera from its study detection caches
(Phase 4 deliverable — the 6h peak-period / 24h study to Excel).

The study cache variants are built by the long-running cache-only pass
(evaluations/study_cachebuild.log). This script retracks every study segment
with the camera's VALIDATED recipe — shipped bank polylines + persisted
per-camera calib knobs (buffered-IoU, birth thresholds, cost metric) — into
one side DB, then (with --apply) swaps the camera's events in project.db in a
single transaction, with a backup first.

Segments per camera mirror the Miovision study windows:
  cams 1/2/4/5: 07-09 + 11-13 + 16-18 (6h peak-period study)
  cam 3:        00:00-24:00 (24h study)

Usage:
  py scripts/assemble_study.py --camera 1            # measure-only side DB
  py scripts/assemble_study.py --camera 1 --apply    # swap into project.db
"""
from __future__ import annotations
import argparse, json, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import get_processing_mode_config
from backend.database import get_camera_calibration_params, list_trims
from backend.services.detection_cache import (
    DetectionCacheReader, cache_exists, compute_video_content_hash, parquet_path)
from backend.services.pipeline import ProcessingPipeline
from reprocess_camera import _load_camera_context
from hybrid_prototype import list_paths_for_camera_tmp
from groundtruth import VIDEO_START
from scratch import scratch_dir

PROJECT = "97a7849a"

# (variant, start_hms, minutes) per camera — must match the cache build.
PEAK_SEGMENTS = [("study_0700", "07:00:00", 120.0),
                 ("study_1100", "11:00:00", 120.0),
                 ("study_1600", "16:00:00", 120.0)]
STUDY = {1: PEAK_SEGMENTS, 2: PEAK_SEGMENTS, 4: PEAK_SEGMENTS, 5: PEAK_SEGMENTS,
         3: [("study_0000", "00:00:00", 1440.0)]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--backend", default="botsort",
                    help="tracker backend for the retrack (validated recipe = botsort)")
    ap.add_argument("--bank", default=None,
                    help="bank JSON; default evaluations/shipped_bank_cam<N>.json")
    ap.add_argument("--out-db", default=None)
    ap.add_argument("--mode", default="balanced")
    ap.add_argument("--segments", default=None,
                    help="JSON [[variant, start_hms, minutes], ...] override "
                         "(testing / partial assemblies)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cam = args.camera
    segments = (json.loads(args.segments) if args.segments else STUDY.get(cam))
    if not segments:
        raise SystemExit(f"no study definition for camera {cam}")
    bank_path = args.bank or f"evaluations/shipped_bank_cam{cam}.json"
    out_db = Path(args.out_db or scratch_dir(PROJECT) / f"cam{cam}_study.db")

    proj_db = f"data/projects/{PROJECT}/project.db"
    conn = sqlite3.connect(proj_db)
    ctx = _load_camera_context(conn, cam)
    conn.close()
    video = ctx["video"]
    fps = float(video["fps"])
    calib = get_camera_calibration_params(PROJECT, cam)
    mode_cfg = get_processing_mode_config(args.mode)
    sug = json.loads(Path(bank_path).read_text())
    chash, _ = compute_video_content_hash(
        video["path"], file_size_bytes=video.get("file_size_bytes"),
        total_frames=video["total_frames"])

    # Every segment's cache must exist before we start.
    missing = []
    seg_windows = []
    for variant, hms, minutes in segments:
        pq = parquet_path(PROJECT, cam, chash, variant)
        if not cache_exists(pq):
            missing.append(variant)
        t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{hms}")
        s = max(0, int((t0 - VIDEO_START).total_seconds() * fps))
        e = min(int(video["total_frames"]), s + int(minutes * 60 * fps))
        seg_windows.append((variant, pq, s, e))
    if missing:
        raise SystemExit(f"cam{cam}: study caches not built yet: {missing} "
                         f"(see evaluations/study_cachebuild.log)")

    # Side DB seeded from project.db: bank paths in, this camera's events out.
    shutil.copy2(proj_db, out_db)
    c = sqlite3.connect(str(out_db))
    with c:
        for ul in sug.get("updated_legs", []):
            c.execute("UPDATE legs SET reference_heading=? WHERE leg_id=? AND camera_id=?",
                      (ul["reference_heading"], ul["leg_id"], cam))
        c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (cam,))
        now = datetime.now().isoformat()
        for p in sug.get("paths", []):
            if p.get("destination_leg_id") is None:
                continue
            c.execute("INSERT OR REPLACE INTO intersection_paths (camera_id, origin_leg_id, "
                      "destination_leg_id, polyline, movement_label, supporting_count, "
                      "source, created_at) VALUES (?,?,?,?,?,?,?,?)",
                      (cam, p["origin_leg_id"], p["destination_leg_id"],
                       json.dumps(p["polyline"]), p["movement_label"],
                       p.get("supporting_count", 0), p.get("source", "data-driven"), now))
        c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (cam,))
    c.close()
    c = sqlite3.connect(str(out_db))
    rctx = _load_camera_context(c, cam)
    c.close()
    paths = list_paths_for_camera_tmp(out_db, cam)
    trims = list_trims(PROJECT, ctx["intersection_id"]) or [{"trim_id": None}]

    # One fresh pipeline per segment (no track continuity across study gaps);
    # all write into the same side DB.
    for variant, pq, s, e in seg_windows:
        print(f"cam{cam} segment {variant}: frames {s}..{e} "
              f"({(e - s) / fps / 60:.0f} min)")
        pipe = ProcessingPipeline(
            project_id=PROJECT, db_path=str(out_db), video_path=video["path"],
            legs=rctx["legs"], fps=fps,
            video_start_time=video["recording_start_datetime"],
            video_id=video["video_id"],
            yolo_model=mode_cfg["yolo_model"], yolo_imgsz=mode_cfg["yolo_imgsz"],
            yolo_confidence=mode_cfg["yolo_confidence"],
            detection_skip=mode_cfg["detection_skip"],
            tracker_match_threshold=mode_cfg.get("tracker_match_threshold"),
            tracker_activation_threshold=mode_cfg.get("tracker_activation_threshold"),
            calibration_params=calib, paths=paths, tracker_backend=args.backend)
        pipe._v3_camera_id = cam
        pipe._v3_trim_id = trims[0]["trim_id"]
        pipe.process_cached(DetectionCacheReader(pq), s, e,
                            detection_skip=mode_cfg["detection_skip"])
        print(f"  -> {pipe.vehicle_count} vehicles "
              f"(quality-filtered {pipe.n_quality_filtered})")

    c = sqlite3.connect(str(out_db))
    n = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (cam,)).fetchone()[0]
    c.close()
    print(f"cam{cam} study assembly: {n} events across {len(seg_windows)} segment(s)")

    if args.apply:
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = Path(f"data/projects/{PROJECT}/backups/{ts}_pre_cam{cam}_study.db")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proj_db, backup)
        c = sqlite3.connect(proj_db)
        cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)").fetchall()
                if r[1] != "event_id"]
        cl = ",".join(cols)
        with c:
            c.execute("ATTACH DATABASE ? AS src", (str(out_db),))
            before = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?",
                               (cam,)).fetchone()[0]
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (cam,))
            c.execute(f"INSERT INTO vehicle_events ({cl}) "
                      f"SELECT {cl} FROM src.vehicle_events WHERE camera_id=?", (cam,))
            after = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?",
                              (cam,)).fetchone()[0]
        c.execute("DETACH DATABASE src")
        c.close()
        print(f"[apply] cam{cam} events {before} -> {after}. Backup: {backup}")
    else:
        print(f"(not applied — side DB at {out_db})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
