"""Headless repopulating reprocess for one camera (Attribution v2, Step 1 run).

Drives the v3 pipeline over a camera's trim windows WITHOUT the server/UI, with
detection-cache write-through enabled. This is the "repopulating reprocess" the
implementation plan calls for: the surviving DB has only ~144 trajectories (the
original 9,785 were deleted with no backup), so the replay/tuning harness is
statistically dead until trajectories are regenerated. One run of this script:

  (a) regenerates vehicle_events for the camera under current logic,
  (b) write-throughs the reference Parquet detection cache (so subsequent
      tracker/attribution experiments retrack in minutes — see process_cached),
  (c) lets you snapshot a fresh B0 baseline to diff future changes against
      (the original A1 baseline is unrecoverable).

It mirrors backend/routers/intersections.py's v3 executor (legs + paths + calib
+ _v3_camera_id/_v3_trim_id) so regenerated events carry the right camera_id /
trim_id that scripts/per_movement_accuracy.py filters on.

DESTRUCTIVE: with --yes it DELETES the camera's existing vehicle_events first so
the regeneration is clean. Requires --yes to run (dry-run prints the plan).

Usage:
  py scripts/reprocess_camera.py                       # dry-run: print the plan
  py scripts/reprocess_camera.py --yes                 # regenerate (hours on CPU)
  py scripts/reprocess_camera.py --yes --baseline B0_baseline
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import get_processing_mode_config
from backend.database import (
    get_calibration_params,
    list_paths_for_camera,
    list_trims,
)
from backend.services.detection_cache import (
    DEFAULT_VARIANT,
    DetectionCacheWriter,
    compute_video_content_hash,
    parquet_path,
)
from backend.services.pipeline import ProcessingPipeline


def _project_db(project_id: str) -> Path:
    return Path("data/projects") / project_id / "project.db"


def _load_camera_context(conn: sqlite3.Connection, camera_id: int) -> dict:
    conn.row_factory = sqlite3.Row
    cam = conn.execute(
        "SELECT camera_id, intersection_id FROM cameras WHERE camera_id=?",
        (camera_id,),
    ).fetchone()
    if cam is None:
        raise SystemExit(f"Camera {camera_id} not found.")
    video = conn.execute(
        "SELECT video_id, path, fps, total_frames, recording_start_datetime, "
        "file_size_bytes FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (camera_id,),
    ).fetchone()
    if video is None:
        raise SystemExit(f"Camera {camera_id} has no video.")
    legs = [dict(r) for r in conn.execute(
        "SELECT * FROM legs WHERE camera_id=? ORDER BY sort_order", (camera_id,),
    ).fetchall()]
    for leg in legs:
        oz = leg.get("origin_zone")
        if isinstance(oz, str):
            import json
            leg["origin_zone"] = json.loads(oz)
    return {
        "intersection_id": cam["intersection_id"],
        "video": dict(video),
        "legs": legs,
    }


def _trim_frame_window(trim: dict, rec_start_iso: str, fps: float,
                       total_frames: int) -> tuple[int, int]:
    """Map a trim's wallclock window to [start_frame, end_frame) in the video."""
    rec_start = datetime.fromisoformat(rec_start_iso)
    date = rec_start.date().isoformat()
    t_start = datetime.fromisoformat(f"{date}T{trim['start_wallclock']}")
    t_end = datetime.fromisoformat(f"{date}T{trim['end_wallclock']}")
    start_f = int((t_start - rec_start).total_seconds() * fps)
    end_f = int((t_end - rec_start).total_seconds() * fps)
    start_f = max(0, min(start_f, total_frames))
    end_f = max(start_f, min(end_f, total_frames))
    return start_f, end_f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--mode", default="balanced")
    ap.add_argument("--variant", default=None,
                    help="detection-cache variant name (parquet stem). Defaults to "
                         "DEFAULT_VARIANT (balanced_960_skip1). Set this to write a "
                         "non-default cache (e.g. accurate_1280_skip1) WITHOUT clobbering "
                         "the shipped 960 cache.")
    ap.add_argument("--yes", action="store_true",
                    help="actually run (DELETES the camera's events first); "
                         "without it, prints the plan and exits")
    ap.add_argument("--no-cache", action="store_true",
                    help="don't write the detection cache (regenerate events only)")
    ap.add_argument("--cache-only", action="store_true",
                    help="NON-DESTRUCTIVE: build the detection cache without touching "
                         "project.db events. The pipeline writes its events to a throwaway "
                         "temp DB (discarded); the real cache parquet is still written. Use "
                         "to (re)build caches for ALREADY-SHIPPED cameras without losing their "
                         "events. Implies cache write-through.")
    ap.add_argument("--audit", action="store_true",
                    help="collect per-track detection-vs-association audit stats "
                         "(P2.C) to detections/<hash>/track_audit.json")
    ap.add_argument("--start-hms", default=None,
                    help="process a single custom window starting at this wallclock "
                         "HH:MM:SS instead of the full trims (for a quick 15-min bucket)")
    ap.add_argument("--minutes", type=float, default=15.0,
                    help="duration in minutes for --start-hms (default 15)")
    ap.add_argument("--baseline", default=None,
                    help="after the run, snapshot per_movement_accuracy to "
                         "evaluations/<name>.json (e.g. B0_baseline)")
    ap.add_argument("--device", default="openvino",
                    help="detector device: 'openvino' (Intel iGPU, ~3x CPU, "
                         "DEFAULT), 'cpu', or 'auto'. The Intel GPU path is "
                         "proven (yolo26s@960 ~7fps vs 2.33 CPU); it needs a "
                         "pre-exported model (auto-exported below if missing).")
    args = ap.parse_args()

    # Detector reads DEVICE from the env at construction (see detect_device).
    import os
    os.environ["DEVICE"] = args.device

    db_path = _project_db(args.project)
    if not db_path.exists():
        raise SystemExit(f"No project DB at {db_path}")

    conn = sqlite3.connect(str(db_path))
    ctx = _load_camera_context(conn, args.camera)
    intersection_id = ctx["intersection_id"]
    video = ctx["video"]
    legs = ctx["legs"]
    trims = list_trims(args.project, intersection_id)
    paths = list_paths_for_camera(args.project, args.camera)
    calib = get_calibration_params(args.project, intersection_id)
    mode_cfg = get_processing_mode_config(args.mode)
    fps = float(video["fps"])

    if args.start_hms:
        # Single custom window (quick bucket) instead of the full trims.
        rec_start = datetime.fromisoformat(video["recording_start_datetime"])
        date = rec_start.date().isoformat()
        t0 = datetime.fromisoformat(f"{date}T{args.start_hms}")
        s = int((t0 - rec_start).total_seconds() * fps)
        e = s + int(args.minutes * 60 * fps)
        s = max(0, min(s, video["total_frames"]))
        e = max(s, min(e, video["total_frames"]))
        label_trim = {
            "trim_id": trims[0]["trim_id"] if trims else None,
            "start_wallclock": args.start_hms,
            "end_wallclock": f"+{args.minutes:g}min",
        }
        windows = [((s, e), label_trim)]
    else:
        windows = [(_trim_frame_window(t, video["recording_start_datetime"], fps,
                                       video["total_frames"]), t) for t in trims]

    existing = conn.execute(
        "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (args.camera,),
    ).fetchone()[0]

    print(f"Project {args.project} camera {args.camera} (intersection {intersection_id})")
    print(f"Video: {video['path']}")
    print(f"  fps={fps} total_frames={video['total_frames']} "
          f"rec_start={video['recording_start_datetime']}")
    print(f"Mode: {args.mode} -> model={mode_cfg['yolo_model']} imgsz={mode_cfg['yolo_imgsz']} "
          f"conf={mode_cfg['yolo_confidence']} skip={mode_cfg['detection_skip']}")
    print(f"Device: {args.device}"
          + ("  (Intel iGPU via OpenVINO)" if args.device == "openvino" else ""))
    print(f"Legs: {len(legs)}  Paths: {len(paths)}  Trims: {len(trims)}")
    total_frames_to_do = 0
    for (s, e), t in windows:
        dur_min = (e - s) / fps / 60.0
        total_frames_to_do += (e - s)
        print(f"  trim {t['trim_id']} {t['start_wallclock']}-{t['end_wallclock']}: "
              f"frames [{s}, {e}) (~{dur_min:.0f} min of video)")
    print(f"Total frames to process: {total_frames_to_do:,}")
    print(f"Existing camera-{args.camera} vehicle_events: {existing}")
    print(f"Detection cache: {'DISABLED' if args.no_cache else 'write-through ENABLED'}")

    if not args.yes:
        print("\nDRY RUN. Re-run with --yes to delete existing events and reprocess.")
        conn.close()
        return 0

    # Pre-export the OpenVINO model BEFORE the destructive delete, out of the
    # pipeline hot path. The detector raises (no silent CPU fallback) if the
    # export is missing/mismatched, so doing it here means a missing export
    # fails loud BEFORE we delete events — never deleting for a run that can't
    # detect. (Skips instantly if the export already matches.)
    if args.device == "openvino":
        from scripts.export_yolo_openvino import export_one
        print("\nEnsuring OpenVINO export (Intel iGPU) ...")
        export_one(mode_cfg["yolo_model"], int(mode_cfg["yolo_imgsz"]))

    # The pipeline writes its events to pipeline_db. Normally that's the real
    # project.db (after a destructive clean). In --cache-only mode we point it at
    # a throwaway COPY so the real project.db events are NEVER touched — only the
    # detection cache (written independently below) lands for real.
    pipeline_db = str(db_path)
    tmp_db = None
    if args.cache_only:
        import shutil, tempfile
        # Scratch lives in the SYSTEM temp dir, not the OneDrive project dir —
        # OneDrive holds file locks (WinError 5/32) that block cleanup. Unique
        # name per process so concurrent/leftover runs never collide on the copy.
        tmp_db = Path(tempfile.gettempdir()) / f"_cacheonly_p{os.getpid()}_cam{args.camera}.db"
        shutil.copy2(db_path, tmp_db)
        pipeline_db = str(tmp_db)
        print(f"\n[cache-only] NON-DESTRUCTIVE: events -> throwaway {tmp_db}; "
              f"real camera-{args.camera} events left intact.")
        conn.close()
    else:
        # Destructive: clean the camera's events for a fresh repopulate.
        print(f"\nDeleting {existing} existing camera-{args.camera} events ...")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("DELETE FROM vehicle_events WHERE camera_id=?", (args.camera,))
        conn.commit()
        conn.close()

    # One detection-cache writer per (camera, video-hash) covering all trims.
    writer = None
    if not args.no_cache:
        chash, method = compute_video_content_hash(
            video["path"], file_size_bytes=video.get("file_size_bytes"),
            total_frames=video["total_frames"],
        )
        pq = parquet_path(args.project, args.camera, chash, args.variant or DEFAULT_VARIANT)
        writer = DetectionCacheWriter(pq_path=pq, metadata={
            "camera_id": args.camera, "content_hash": chash, "method": method,
            "model": mode_cfg["yolo_model"], "imgsz": mode_cfg["yolo_imgsz"],
            "confidence": mode_cfg["yolo_confidence"],
            "detection_skip": mode_cfg["detection_skip"],
            "windows": [[s, e] for (s, e), _ in windows],
        })
        print(f"Cache -> {pq}  (hash {chash[:16]}…)")
        # Persist the hash on the videos row (pipeline_db == real db unless cache-only).
        c2 = sqlite3.connect(pipeline_db)
        c2.execute("UPDATE videos SET content_hash=?, content_hash_method=? WHERE video_id=?",
                   (chash, method, video["video_id"]))
        c2.commit(); c2.close()

    run_start = time.time()
    done_frames = 0
    audit_records: list = []
    try:
        for (s, e), t in windows:
            print(f"\n=== Trim {t['trim_id']} frames [{s}, {e}) ===")
            pipeline = ProcessingPipeline(
                project_id=args.project, db_path=pipeline_db,
                video_path=video["path"], legs=legs, fps=fps,
                video_start_time=video["recording_start_datetime"],
                video_id=video["video_id"],
                yolo_model=mode_cfg["yolo_model"], yolo_imgsz=mode_cfg["yolo_imgsz"],
                yolo_confidence=mode_cfg["yolo_confidence"],
                detection_skip=mode_cfg["detection_skip"],
                tracker_match_threshold=mode_cfg.get("tracker_match_threshold"),
                tracker_activation_threshold=mode_cfg.get("tracker_activation_threshold"),
                calibration_params=calib, paths=paths,
            )
            pipeline._v3_camera_id = args.camera
            pipeline._v3_trim_id = t["trim_id"]
            if writer is not None:
                pipeline._detection_cache_writer = writer
            if args.audit:
                pipeline._audit_mode = True

            def _cb(data, _s=s, _e=e):
                nonlocal done_frames
                fn = data.get("frame_number", _s)
                elapsed = time.time() - run_start
                eff_fps = (done_frames + (fn - _s)) / elapsed if elapsed > 0 else 0
                print(f"  frame {fn}/{_e}  veh={data.get('vehicle_count')}  "
                      f"{eff_fps:.1f} fps  elapsed {elapsed/60:.1f} min", flush=True)

            pipeline.process_video(frame_skip=300, start_frame=s, end_frame=e,
                                   callback=_cb)
            done_frames += (e - s)
            if args.audit:
                audit_records.extend(pipeline._audit_records)
    finally:
        if writer is not None:
            n = writer.close()
            print(f"\nDetection cache written: {n:,} detections.")
        if args.audit:
            import json
            audit_path = (Path("data/projects") / args.project / "detections"
                          / str(args.camera) / "track_audit.json")
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(json.dumps(audit_records))
            print(f"Audit: wrote {len(audit_records)} track records -> {audit_path}")

    elapsed = time.time() - run_start
    if tmp_db is not None:
        c3 = sqlite3.connect(pipeline_db)
        new_count = c3.execute(
            "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (args.camera,)).fetchone()[0]
        c3.close()
        # Release any lingering pipeline sqlite handles before unlinking.
        del pipeline
        import gc; gc.collect()
        for p in (tmp_db, tmp_db.with_name(tmp_db.name + "-wal"), tmp_db.with_name(tmp_db.name + "-shm")):
            try:
                if p.exists():
                    p.unlink()
            except OSError as ex:
                print(f"  (scratch leftover, harmless: {p.name}: {ex})")
        print(f"\nDone in {elapsed/60:.1f} min. [cache-only] cache built; "
              f"real project.db events untouched (scratch had {new_count} cam-{args.camera} events).")
    else:
        conn = sqlite3.connect(str(db_path))
        new_count = conn.execute(
            "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (args.camera,),
        ).fetchone()[0]
        conn.close()
        print(f"\nDone in {elapsed/60:.1f} min. Regenerated {new_count} camera-{args.camera} events.")

    if args.baseline and not args.cache_only:
        print(f"\nSnapshotting baseline -> evaluations/{args.baseline}.json")
        subprocess.run([sys.executable, "scripts/per_movement_accuracy.py",
                        "--save", args.baseline], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
