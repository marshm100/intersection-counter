"""Retrack cam2 (BoT-SORT motion) on its detection cache WITH the derived bank
(recal_cam2.json), then optionally swap the result into project.db. Sharpens cam2
turn attribution over the bank-less bytetrack baseline. (Phase D deadline build —
BoT-motion only; the full BoT+ReID upgrade is a future-session task.)

Usage:
  py scripts/apply_cam2_bank.py --bank evaluations/recal_cam2.json            # measure
  py scripts/apply_cam2_bank.py --bank evaluations/recal_cam2.json --apply     # + write to project.db
"""
from __future__ import annotations
import argparse, json, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import get_processing_mode_config
from backend.database import get_calibration_params
from backend.services.detection_cache import (
    DEFAULT_VARIANT, compute_video_content_hash, parquet_path)
from reprocess_camera import _load_camera_context
from hybrid_prototype import retrack
from groundtruth import VIDEO_START

PROJECT = "97a7849a"
CAMERA = 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default="evaluations/recal_cam2.json")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--out-db", default=f"data/projects/{PROJECT}/_hybrid_tmp/cam2_bank.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    proj_db = f"data/projects/{PROJECT}/project.db"
    conn = sqlite3.connect(proj_db); ctx = _load_camera_context(conn, CAMERA); conn.close()
    video = ctx["video"]; fps = float(video["fps"])
    calib = get_calibration_params(PROJECT, ctx["intersection_id"])
    mode_cfg = get_processing_mode_config("balanced")
    sug = json.loads(Path(args.bank).read_text())
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    s = int((t0 - VIDEO_START).total_seconds() * fps); e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"),
                                          total_frames=video["total_frames"])
    pq = parquet_path(PROJECT, CAMERA, chash, DEFAULT_VARIANT)
    out_db = Path(args.out_db)
    print(f"retrack BoT-motion cam2 with bank ({len(sug.get('paths',[]))} paths) -> {out_db}")
    retrack(out_db, "botsort", video, ctx, calib, mode_cfg, sug, s, e, pq, CAMERA, tracker_kwargs=None)

    if args.apply:
        ts = VIDEO_START.strftime("%Y%m%d")
        backup = Path(f"data/projects/{PROJECT}/backups/{ts}_pre_cam2_bank.db")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proj_db, backup)
        c = sqlite3.connect(proj_db)
        cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)").fetchall() if r[1] != "event_id"]
        cl = ",".join(cols)
        with c:
            c.execute("ATTACH DATABASE ? AS src", (str(out_db),))
            before = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (CAMERA,)).fetchone()[0]
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (CAMERA,))
            c.execute(f"INSERT INTO vehicle_events ({cl}) SELECT {cl} FROM src.vehicle_events WHERE camera_id=?", (CAMERA,))
            after = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (CAMERA,)).fetchone()[0]
            # apply bank paths to project.db
            c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (CAMERA,))
            now = datetime.now().isoformat()
            for p in sug.get("paths", []):
                c.execute("INSERT OR REPLACE INTO intersection_paths (camera_id,origin_leg_id,destination_leg_id,polyline,movement_label,supporting_count,source,created_at) VALUES (?,?,?,?,?,?,?,?)",
                          (CAMERA, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                           p["movement_label"], p.get("supporting_count", 0), p.get("source", "data-driven"), now))
        c.execute("DETACH DATABASE src"); c.close()
        print(f"[apply] cam2 events {before} -> {after}; bank paths applied. Backup {backup}")
    else:
        print(f"(not applied — {out_db}). Measure with: py scripts/measure_cam2.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
