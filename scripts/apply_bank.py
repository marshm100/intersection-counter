"""Retrack ANY corridor camera (BoT-SORT motion) on its detection cache WITH a
derived bank (recal_cam<N>.json), then optionally swap the result into
project.db. Camera-parameterized generalization of apply_cam2_bank.py.
(BoT-motion only; the full BoT+ReID upgrade is the cam1-quality path.)

Usage:
  py scripts/apply_bank.py --camera 3                       # measure (writes a side DB)
  py scripts/apply_bank.py --camera 3 --apply               # + write to project.db (backup first)
"""
from __future__ import annotations
import argparse, json, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import get_processing_mode_config
from backend.database import get_camera_calibration_params
from backend.services.detection_cache import (
    DEFAULT_VARIANT, compute_video_content_hash, parquet_path)
from reprocess_camera import _load_camera_context
from hybrid_prototype import retrack
from groundtruth import VIDEO_START
from scratch import scratch_dir

PROJECT = "97a7849a"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--bank", default=None, help="default evaluations/recal_cam<N>.json")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--out-db", default=None)
    ap.add_argument("--mode", default="balanced")
    ap.add_argument("--backend", default="botsort", help="tracker backend: botsort (turns) or bytetrack (throughs)")
    ap.add_argument("--variant", default=None, help="detection-cache variant (default DEFAULT_VARIANT); "
                    "set to retrack over a non-default cache e.g. accurate_1280_skip1")
    ap.add_argument("--tracker-kwargs", default=None, help="JSON dict of extra tracker kwargs "
                    "(e.g. '{\"track_buffer\": 50}') for param sweeps")
    ap.add_argument("--match-thresh", type=float, default=None,
                    help="override tracker match_thresh for THIS run only (knob sweep; no project.db write)")
    ap.add_argument("--nms-iou", default=None,
                    help="override pre-track NMS IoU for THIS run only: a float or 'off' (knob sweep; no project.db write)")
    # Phase 1 knobs (docs/implementation_plan_architecture_2026-06-11.md)
    ap.add_argument("--activation", type=float, default=None,
                    help="override tracker activation/track_high threshold (birth gate, 1.1)")
    ap.add_argument("--new-track-thresh", type=float, default=None,
                    help="botsort new_track_thresh (its separate birth gate, 1.1); merged into tracker kwargs")
    ap.add_argument("--bbox-buffer", type=float, default=None,
                    help="buffered-IoU box inflation scale at the tracking input (1.3), e.g. 1.3")
    ap.add_argument("--tq-filter", action="store_true",
                    help="enable the finalize-time track-quality gate (pairs with a loosened birth gate, 1.1)")
    ap.add_argument("--stitch", action="store_true",
                    help="enable inline ID-switch stitching (coasting-track remap, 1.5)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cam = args.camera
    bank = args.bank or f"evaluations/recal_cam{cam}.json"
    out_db = Path(args.out_db or scratch_dir(PROJECT) / f"cam{cam}_bank.db")
    out_db.parent.mkdir(parents=True, exist_ok=True)

    proj_db = f"data/projects/{PROJECT}/project.db"
    conn = sqlite3.connect(proj_db); ctx = _load_camera_context(conn, cam); conn.close()
    video = ctx["video"]; fps = float(video["fps"])
    calib = get_camera_calibration_params(PROJECT, cam)
    # Per-run knob overrides for sweeps — injected into the calib dict so they
    # flow through the normal per-camera precedence (calib override > mode arg)
    # WITHOUT mutating project.db. None/absent = use the persisted per-camera value.
    if args.match_thresh is not None:
        calib["tracker_match_threshold"] = args.match_thresh
    if args.nms_iou is not None:
        calib["pre_track_nms_iou"] = None if args.nms_iou == "off" else float(args.nms_iou)
    if args.activation is not None:
        calib["tracker_activation_threshold"] = args.activation
    if args.bbox_buffer is not None:
        calib["bbox_buffer_scale"] = args.bbox_buffer
    if args.tq_filter:
        calib["track_quality_filter"] = 1
    if args.stitch:
        calib["track_stitch"] = 1
    mode_cfg = get_processing_mode_config(args.mode)
    sug = json.loads(Path(bank).read_text())
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    s = int((t0 - VIDEO_START).total_seconds() * fps); e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"),
                                          total_frames=video["total_frames"])
    pq = parquet_path(PROJECT, cam, chash, args.variant or DEFAULT_VARIANT)
    tk = json.loads(args.tracker_kwargs) if args.tracker_kwargs else None
    if args.new_track_thresh is not None:
        tk = {**(tk or {}), "new_track_thresh": args.new_track_thresh}
    print(f"retrack {args.backend} cam{cam} (variant={args.variant or DEFAULT_VARIANT}) "
          f"with bank ({len(sug.get('paths',[]))} paths) -> {out_db}")
    retrack(out_db, args.backend, video, ctx, calib, mode_cfg, sug, s, e, pq, cam, tracker_kwargs=tk)

    if args.apply:
        ts = VIDEO_START.strftime("%Y%m%d")
        backup = Path(f"data/projects/{PROJECT}/backups/{ts}_pre_cam{cam}_bank.db")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proj_db, backup)
        c = sqlite3.connect(proj_db)
        cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)").fetchall() if r[1] != "event_id"]
        cl = ",".join(cols)
        with c:
            c.execute("ATTACH DATABASE ? AS src", (str(out_db),))
            before = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (cam,)).fetchone()[0]
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (cam,))
            c.execute(f"INSERT INTO vehicle_events ({cl}) SELECT {cl} FROM src.vehicle_events WHERE camera_id=?", (cam,))
            after = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (cam,)).fetchone()[0]
            c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (cam,))
            now = datetime.now().isoformat()
            for p in sug.get("paths", []):
                c.execute("INSERT OR REPLACE INTO intersection_paths (camera_id,origin_leg_id,destination_leg_id,polyline,movement_label,supporting_count,source,created_at) VALUES (?,?,?,?,?,?,?,?)",
                          (cam, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                           p["movement_label"], p.get("supporting_count", 0), p.get("source", "data-driven"), now))
        c.execute("DETACH DATABASE src"); c.close()
        print(f"[apply] cam{cam} events {before} -> {after}; bank paths applied. Backup {backup}")
    else:
        print(f"(not applied — {out_db}). Measure with: py scripts/od_accuracy.py --camera {cam} --db {out_db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
