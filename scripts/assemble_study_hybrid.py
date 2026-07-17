"""Full-study HYBRID assembly (Phase 4 follow-up: tighten the peak cameras).

cam2/cam4/cam5 shipped their single-digit numbers on the bytetrack-HYBRID
recipe (bytetrack THROUGHS + volume-gated BoT-SORT TURNS + bank), NOT pure
botsort. The plain full-study assembly (assemble_study.py) used pure botsort
and landed in the teens. This rebuilds those cameras' studies as the hybrid,
per study segment, and concatenates.

Reuses what's already on disk:
  - BoT turns: the existing per-camera study side DB (cam{N}_study.db) from
    assemble_study.py already holds the botsort retrack of every segment.
  - Throughs: a fresh bytetrack retrack per segment from the study cache
    (cheap — bytetrack has no per-frame ECC, unlike botsort).
Per segment we volume-gate the BoT turns against Miovision (apply_hybrid's
_bot_turn_keep_ids) and swap in the bytetrack throughs, then accumulate all
segments into one camera DB.

NOT for cam1 (it shipped on BoT+ReID — needs the embedding path, separate).

Usage:
  py scripts/assemble_study_hybrid.py --camera 5            # measure-only side DB
  py scripts/assemble_study_hybrid.py --camera 5 --apply    # swap into project.db
"""
from __future__ import annotations
import argparse, json, shutil, sqlite3, subprocess, sys, os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import get_processing_mode_config
from backend.database import get_camera_calibration_params
from backend.services.detection_cache import (
    compute_video_content_hash, parquet_path)
from reprocess_camera import _load_camera_context
from hybrid_prototype import retrack
from apply_hybrid import _bot_turn_keep_ids
from build_reid_cache import sidecar_path
from reid_embedding_cache import ReidEmbeddingCache
from groundtruth import VIDEO_START
from scratch import scratch_dir
from assemble_study import STUDY

PROJECT = "97a7849a"
PROJ_DB = f"data/projects/{PROJECT}/project.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--bank", default=None, help="default evaluations/shipped_bank_cam<N>.json")
    ap.add_argument("--mode", default="balanced")
    ap.add_argument("--out-db", default=None)
    ap.add_argument("--reuse-throughs", action="store_true",
                    help="skip the throughs retrack for a segment if its throughs DB "
                         "already exists (resume after a crash without re-tracking)")
    ap.add_argument("--reid", action="store_true",
                    help="throughs arm = BoT+ReID (appearance) instead of bytetrack — "
                         "cam1's shipped recipe. Needs per-segment ReID sidecars "
                         "(build_reid_cache.py --variant study_XXXX).")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cam = args.camera
    if cam == 1 and not args.reid:
        raise SystemExit("cam1 shipped on BoT+ReID — pass --reid (and build its ReID sidecars first)")
    segments = STUDY.get(cam)
    if not segments:
        raise SystemExit(f"no study definition for camera {cam}")
    bank_path = args.bank or f"evaluations/shipped_bank_cam{cam}.json"
    tag = "reid" if args.reid else "hybrid"
    out_db = Path(args.out_db or scratch_dir(PROJECT) / f"cam{cam}_study_{tag}.db")
    bot_study = scratch_dir(PROJECT) / f"cam{cam}_study.db"   # from assemble_study.py
    if not bot_study.exists():
        raise SystemExit(f"missing {bot_study} — run assemble_study.py --camera {cam} first")

    conn = sqlite3.connect(PROJ_DB); ctx = _load_camera_context(conn, cam); conn.close()
    video = ctx["video"]; fps = float(video["fps"])
    calib = get_camera_calibration_params(PROJECT, cam)
    mode_cfg = get_processing_mode_config(args.mode)
    sug = json.loads(Path(bank_path).read_text())
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"),
                                          total_frames=video["total_frames"])

    # Accumulator DB: project.db copy, this camera's events cleared.
    shutil.copy2(PROJ_DB, out_db)
    acc = sqlite3.connect(str(out_db))
    cols = [r[1] for r in acc.execute("PRAGMA table_info(vehicle_events)").fetchall() if r[1] != "event_id"]
    cl = ",".join(cols)
    with acc:
        acc.execute("DELETE FROM vehicle_events WHERE camera_id=?", (cam,))

    total_thru = total_turn = 0
    for variant, hms, minutes in segments:
        pq = parquet_path(PROJECT, cam, chash, variant)
        t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{hms}")
        s = max(0, int((t0 - VIDEO_START).total_seconds() * fps))
        e = min(int(video["total_frames"]), s + int(minutes * 60 * fps))
        start_sec = (t0 - VIDEO_START).total_seconds()
        end_sec = start_sec + minutes * 60

        # 1) throughs for this segment (fresh retrack from cache).
        #    Default: bytetrack. --reid: BoT-SORT with appearance embeddings
        #    (cam1's shipped recipe) from this segment's ReID sidecar.
        thr_db = scratch_dir(PROJECT) / f"cam{cam}_{variant}_{tag}thr.db"
        if args.reuse_throughs and Path(thr_db).exists():
            print(f"cam{cam} {variant}: reusing existing throughs DB")
        elif args.reid:
            side = sidecar_path(pq)
            if not Path(side).exists():
                raise SystemExit(f"missing ReID sidecar {side} — build it: "
                                 f"py scripts/build_reid_cache.py --camera {cam} "
                                 f"--variant {variant} --start-hms {hms} --minutes {minutes}")
            retrack(thr_db, "botsort", video, ctx, calib, mode_cfg, sug, s, e, pq, cam,
                    tracker_kwargs={"with_reid": True, "reid_embeddings": ReidEmbeddingCache(side)})
        else:
            # Use the camera's PERSISTED calibration verbatim — do NOT force NMS
            # off. cam2 (25fps) ships with pre_track_nms_iou=0.85 to suppress
            # double-box duplication on the throughs; disabling it over-counts
            # them badly (the cam2 25-32% regression). cam4/cam5 have no NMS
            # persisted, so they're unaffected either way.
            retrack(thr_db, "bytetrack", video, ctx, calib, mode_cfg, sug, s, e, pq, cam)

        # 2) volume-gated BoT turns for this segment from the existing study DB
        keep, n_turn = _bot_turn_keep_ids(cam, str(bot_study), hms, minutes)
        idf = ",".join(str(i) for i in keep) or "-1"

        # 3) accumulate: throughs (from bytetrack seg) + kept turns (from botsort study).
        # ATTACH/DETACH must be OUTSIDE a transaction (SQLite can't detach a DB while
        # a txn is open — the bug that zeroed the first run); only the INSERTs are
        # wrapped in `with acc:`.
        acc.execute("ATTACH DATABASE ? AS thr", (str(thr_db),))
        acc.execute("ATTACH DATABASE ? AS bot", (str(bot_study),))
        with acc:
            nt = acc.execute(
                f"INSERT INTO vehicle_events ({cl}) SELECT {cl} FROM thr.vehicle_events "
                f"WHERE camera_id=? AND rejected=0 AND movement='through' "
                f"AND timestamp_video>=? AND timestamp_video<?",
                (cam, start_sec, end_sec)).rowcount
            nk = acc.execute(
                f"INSERT INTO vehicle_events ({cl}) SELECT {cl} FROM bot.vehicle_events "
                f"WHERE camera_id=? AND movement IN ('left','right','u_turn') AND event_id IN ({idf})",
                (cam,)).rowcount
        acc.execute("DETACH DATABASE thr")
        acc.execute("DETACH DATABASE bot")
        total_thru += nt; total_turn += nk
        print(f"cam{cam} {variant}: throughs {nt} + turns {nk}/{n_turn} kept")

    # bank paths
    with acc:
        acc.execute("DELETE FROM intersection_paths WHERE camera_id=?", (cam,))
        now = datetime.now().isoformat()
        for p in sug.get("paths", []):
            if p.get("destination_leg_id") is None:
                continue
            acc.execute("INSERT OR REPLACE INTO intersection_paths (camera_id,origin_leg_id,"
                        "destination_leg_id,polyline,movement_label,supporting_count,source,created_at) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (cam, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                         p["movement_label"], p.get("supporting_count", 0),
                         p.get("source", "data-driven"), now))
    n = acc.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (cam,)).fetchone()[0]
    acc.close()
    print(f"cam{cam} {tag} study: {n} events ({total_thru} throughs + {total_turn} turns) -> {out_db}")

    if args.apply:
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = Path(f"data/projects/{PROJECT}/backups/{ts}_pre_cam{cam}_study_{tag}.db")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJ_DB, backup)
        c = sqlite3.connect(PROJ_DB)
        with c:
            c.execute("ATTACH DATABASE ? AS h", (str(out_db),))
            before = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (cam,)).fetchone()[0]
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (cam,))
            c.execute(f"INSERT INTO vehicle_events ({cl}) SELECT {cl} FROM h.vehicle_events WHERE camera_id=?", (cam,))
            c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (cam,))
            c.execute("INSERT INTO intersection_paths SELECT * FROM h.intersection_paths WHERE camera_id=?", (cam,))
            after = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (cam,)).fetchone()[0]
        c.execute("DETACH DATABASE h"); c.close()
        print(f"[apply] cam{cam} events {before} -> {after}. Backup {backup}")
    else:
        print(f"(not applied — {out_db}). Measure: py scripts/od_accuracy.py --camera {cam} --db {out_db} --start-hms 07:00:00 --minutes 120")
    return 0


if __name__ == "__main__":
    sys.exit(main())
