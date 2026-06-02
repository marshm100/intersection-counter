"""B-batch production orchestrator: process a camera with the BoT+ReID regime-split
config and produce the FINAL merged event stream (docs/reid_project_plan_2026-06-01.md,
Phase B). This is the local-batch productionization of the validated offline pipeline:

  detections (cache) + ReID embeddings (sidecar) -> retrack BoT+ReID (throughs) +
  retrack BoT-SORT motion (turns) -> regime combine + volume-gated intra-turn merge
  -> final events (crossing-timestamped) -> optional apply into project.db.

Reuses 100% of the validated components (hybrid_prototype.retrack, build_reid_cache,
hybrid_ocbot.combine_regimes). ReID embedding runs on CPU (the Iris-Xe GPU gives no
speedup for this tiny model — see export_osnet_openvino.py finding); the sidecar is
built once per video and cached.

Default run produces a working final DB + measurement (Phase B verification). Pass
--apply ONLY after the engineer visual gate (Phase C) to write into project.db; it
backs up project.db first and swaps the camera's events + applies the bank atomically.

Usage:
  py scripts/process_camera_reid.py --camera 1 --bank evaluations/recal_cam1_odturns_ebr.json
  py scripts/process_camera_reid.py --camera 1 --bank ... --apply     # after visual gate
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import get_processing_mode_config
from backend.database import get_calibration_params
from backend.services.detection_cache import (
    DEFAULT_VARIANT, compute_video_content_hash, parquet_path)
from reprocess_camera import _load_camera_context
from hybrid_prototype import retrack
from hybrid_ocbot import combine_regimes
from build_reid_cache import sidecar_path
from reid_embedding_cache import ReidEmbeddingCache
from od_accuracy import manual_per_minute, our_per_minute, leg_idx, LEG_IDX, IDX_NAME
from groundtruth import VIDEO_START
from scratch import scratch_dir

PROJECT = "97a7849a"


def _measure(db, start_hms, minutes, camera_id=1):
    legmap = LEG_IDX if camera_id == 1 else leg_idx(camera_id)
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{start_hms}")
    start_sec = (t0 - VIDEO_START).total_seconds()
    minutes_list = [t0 + timedelta(minutes=i) for i in range(int(minutes))]
    m_od, m_mv, _ = manual_per_minute(camera_id)
    o_od, o_mv = our_per_minute(db, start_sec, start_sec + minutes * 60, legmap=legmap,
                                camera_id=camera_id)
    cells = set()
    for mn in minutes_list:
        cells |= set(m_mv.get(mn, {})) | set(o_mv.get(mn, {}))
    tman = tnet = tg = 0
    for cell in cells:
        man = sum(m_mv.get(mn, {}).get(cell, 0) for mn in minutes_list)
        ours = sum(o_mv.get(mn, {}).get(cell, 0) for mn in minutes_list)
        tman += man; tnet += abs(ours - man)
        tg += sum(abs(o_mv.get(mn, {}).get(cell, 0) - m_mv.get(mn, {}).get(cell, 0)) for mn in minutes_list)
    return tnet / tman * 100, tg / tman * 100


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--bank", default="evaluations/recal_cam1_odturns_ebr.json")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--reid-cache", default=None, help="embedding sidecar npz (default: auto-locate)")
    ap.add_argument("--workdir", default=None, help="scratch dir (default: system temp, NOT OneDrive)")
    ap.add_argument("--reuse-arms", action="store_true",
                    help="reuse existing arm DBs in workdir instead of retracking")
    ap.add_argument("--apply", action="store_true",
                    help="write final events + bank into project.db (backs up first). "
                         "Use ONLY after the engineer visual gate.")
    args = ap.parse_args()
    camera = args.camera
    proj_db = f"data/projects/{PROJECT}/project.db"

    conn = sqlite3.connect(proj_db); ctx = _load_camera_context(conn, camera); conn.close()
    video = ctx["video"]; fps = float(video["fps"])
    calib = get_calibration_params(PROJECT, ctx["intersection_id"])
    mode_cfg = get_processing_mode_config("balanced")
    sug = json.loads(Path(args.bank).read_text())

    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    s = int((t0 - VIDEO_START).total_seconds() * fps); e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"),
                                          total_frames=video["total_frames"])
    pq = parquet_path(PROJECT, camera, chash, DEFAULT_VARIANT)

    side = Path(args.reid_cache) if args.reid_cache else sidecar_path(pq)
    workdir = Path(args.workdir) if args.workdir else scratch_dir(PROJECT)
    workdir.mkdir(parents=True, exist_ok=True)
    arm_reid = workdir / f"prod_reid_cam{camera}.db"
    arm_motion = workdir / f"prod_motion_cam{camera}.db"
    final_db = workdir / f"prod_final_cam{camera}.db"

    if not args.reuse_arms:
        if not side.exists():
            print(f"ERROR: embedding sidecar missing: {side}\n"
                  f"  build it first: py scripts/build_reid_cache.py --start-hms {args.start_hms} --minutes {args.minutes}")
            return 2
        reid_kwargs = {"with_reid": True, "reid_embeddings": ReidEmbeddingCache(side)}
        print(f"[1/3] retrack BoT+ReID (throughs arm) -> {arm_reid}")
        retrack(arm_reid, "botsort", video, ctx, calib, mode_cfg, sug, s, e, pq, camera,
                tracker_kwargs=reid_kwargs)
        print(f"[2/3] retrack BoT-SORT motion (turns arm) -> {arm_motion}")
        retrack(arm_motion, "botsort", video, ctx, calib, mode_cfg, sug, s, e, pq, camera,
                tracker_kwargs=None)
    else:
        print("(reusing existing arm DBs)")

    print(f"[3/3] regime combine + intra-turn merge -> {final_db}")
    kept, dropped, n = combine_regimes(
        arm_reid, arm_motion, final_db, merge_turns=True, no_dedup=True,
        start_hms=args.start_hms, minutes=args.minutes, camera_id=camera)
    print(f"  throughs(ReID) kept={kept}  turns(motion, merged) inserted={n}")

    net, gross = _measure(final_db, args.start_hms, args.minutes, camera_id=camera)
    print(f"\nFINAL cam{camera}: net {net:.1f}%  per-min gross {gross:.1f}%")

    if args.apply:
        ts = VIDEO_START.strftime("%Y%m%d")  # deterministic; real ts stamped by caller if needed
        backup = Path(f"data/projects/{PROJECT}/backups/{ts}_pre_reid_apply_cam{camera}.db")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proj_db, backup)
        print(f"\n[apply] backed up project.db -> {backup}")
        # swap camera events: delete this camera's events, copy final_db's in
        c = sqlite3.connect(proj_db)
        cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)").fetchall() if r[1] != "event_id"]
        collist = ",".join(cols)
        before = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (camera,)).fetchone()[0]
        with c:
            c.execute("ATTACH DATABASE ? AS fin", (str(final_db),))
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (camera,))
            c.execute(f"INSERT INTO vehicle_events ({collist}) SELECT {collist} FROM fin.vehicle_events WHERE camera_id=?", (camera,))
            after = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (camera,)).fetchone()[0]
            # apply bank: leg reference_headings + intersection_paths
            for ul in sug.get("updated_legs", []):
                c.execute("UPDATE legs SET reference_heading=? WHERE leg_id=? AND camera_id=?",
                          (ul["reference_heading"], ul["leg_id"], camera))
            c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (camera,))
            now = datetime.now().isoformat()
            for p in sug.get("paths", []):
                if p.get("destination_leg_id") is None:
                    continue
                c.execute("INSERT OR REPLACE INTO intersection_paths (camera_id, origin_leg_id, destination_leg_id, polyline, movement_label, supporting_count, source, created_at) VALUES (?,?,?,?,?,?,?,?)",
                          (camera, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                           p["movement_label"], p.get("supporting_count", 0), p.get("source", "data-driven"), now))
        c.execute("DETACH DATABASE fin"); c.close()
        print(f"[apply] camera {camera} events {before} -> {after}; bank applied. Backup at {backup}")
    else:
        print(f"\n(not applied — final DB at {final_db}. Re-run with --apply after the visual gate.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
