"""Measure the per-regime / HYBRID tracker ceiling (measurement-only prototype).

Hypothesis (scripts/diagnose_sb_*.py, dedup_ceiling.py): ByteTrack gets THROUGHS
right (IoU-continuity, no fragmentation on straight arterials; SB-thru 425≈manual
424) but fragments TURNS; OC-SORT recovers TURNS (2x; NB-left 97≈96) but
over-counts throughs (631 vs 424 via ID-switches). So: attribute THROUGHS from
ByteTrack + TURNS from OC-SORT, discard OC-SORT's throughs entirely (over-count
gone by construction) and ByteTrack's turn-stubs.

Reuses the pipeline's EXACT attribution by retracking each backend (with the turn
bank) into its own temp DB, then combining at the event level:
  combined = {ByteTrack events: movement==thru}  +  {OC-SORT events: movement in turns}
  minus ByteTrack-throughs that overlap an OC-SORT turn (a turning vehicle whose
  through-stub ByteTrack misread) so the same vehicle isn't double-counted.

Reports agg_err + all watch cells vs the OC-SORT-only baseline.
Usage:  py scripts/hybrid_prototype.py --minutes 30
"""
from __future__ import annotations

import argparse, json, math, shutil, sqlite3, sys, tempfile
from datetime import datetime
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import groundtruth
from backend.config import get_processing_mode_config
from backend.database import get_calibration_params, list_trims
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path)
from backend.services.pipeline import ProcessingPipeline
from reprocess_camera import _load_camera_context
import per_movement_accuracy as pma
from test_recal_effect import list_paths_for_camera_tmp

WATCH = [(22, "thru"), (23, "thru"), (23, "left"), (22, "left"), (23, "right")]
TURNS = {"left", "right", "uturn", "u_turn"}


def retrack(tdb, backend, video, ctx, calib, mode_cfg, sug, s, e, pq, camera,
            tracker_kwargs=None):
    shutil.copy2(Path("data/projects/97a7849a/project.db"), tdb)
    c = sqlite3.connect(str(tdb))
    with c:
        for ul in sug.get("updated_legs", []):
            c.execute("UPDATE legs SET reference_heading=? WHERE leg_id=? AND camera_id=?",
                      (ul["reference_heading"], ul["leg_id"], camera))
        c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (camera,))
        now = datetime.now().isoformat()
        for p in sug.get("paths", []):
            if p.get("destination_leg_id") is None:
                continue
            # OR REPLACE: a duplicate (origin,dest) in the bank must not abort the
            # txn and silently fall back to stale paths (that bug masked a 114% run).
            c.execute("INSERT OR REPLACE INTO intersection_paths (camera_id, origin_leg_id, destination_leg_id, polyline, movement_label, supporting_count, source, created_at) "
                      "VALUES (?,?,?,?,?,?, 'data-driven', ?)",
                      (camera, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                       p["movement_label"], p.get("supporting_count", 0), now))
        c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (camera,))
    c.close()
    c = sqlite3.connect(str(tdb)); rctx = _load_camera_context(c, camera); c.close()
    paths = list_paths_for_camera_tmp(tdb, camera)
    pipe = ProcessingPipeline(
        project_id="97a7849a", db_path=str(tdb), video_path=video["path"], legs=rctx["legs"],
        fps=float(video["fps"]), video_start_time=video["recording_start_datetime"], video_id=video["video_id"],
        yolo_model=mode_cfg["yolo_model"], yolo_imgsz=mode_cfg["yolo_imgsz"], yolo_confidence=mode_cfg["yolo_confidence"],
        detection_skip=mode_cfg["detection_skip"], tracker_match_threshold=mode_cfg.get("tracker_match_threshold"),
        tracker_activation_threshold=0.25, calibration_params=calib, paths=paths, tracker_backend=backend,
        tracker_kwargs=tracker_kwargs)
    pipe._v3_camera_id = camera
    pipe._v3_trim_id = (list_trims("97a7849a", ctx["intersection_id"]) or [{"trim_id": None}])[0]["trim_id"]
    pipe.process_cached(DetectionCacheReader(pq), s, e, detection_skip=mode_cfg["detection_skip"])


def load_events(tdb, camera):
    c = sqlite3.connect(str(tdb))
    rows = c.execute("SELECT event_id, movement, origin_leg_id, destination_leg_id, start_frame, frame_number, "
                     "timestamp_video, trajectory_data FROM vehicle_events WHERE camera_id=? AND rejected=0", (camera,)).fetchall()
    c.close()
    out = []
    for eid, mv, ol, dl, sf, ef, ts, tj in rows:
        try: traj = json.loads(tj) if tj else []
        except Exception: traj = []
        out.append({"id": eid, "mv": mv, "ol": ol, "dl": dl, "s": sf if sf is not None else ef,
                    "e": ef if ef is not None else sf, "ts": ts, "traj": traj})
    return out


def agg(tdb):
    orig = groundtruth.PROJECT_DB
    groundtruth.PROJECT_DB = tdb
    pma.db_processed_window = groundtruth.db_processed_window
    pma.fetch_our_counts = groundtruth.fetch_our_counts
    try:
        manual = groundtruth.parse_manual_csv()
        a = pma.aggregate_full_sweep(manual, groundtruth.db_processed_window())
        cells = pma.build_cells(a); metric = pma.compute_metric(cells)
        cm = {(c["leg_id"], c["movement"]): c for c in cells}
        return metric["agg_err_pct"], metric["total_ours"], cm
    finally:
        groundtruth.PROJECT_DB = orig


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--suggestion", default="evaluations/recal_cam1_nbleftonly.json")
    ap.add_argument("--turn-dedup-px", type=float, default=40.0)
    ap.add_argument("--reuse", action="store_true", help="reuse cached retracked DBs in data/projects/97a7849a/_hybrid_tmp")
    args = ap.parse_args()
    camera = 1
    conn = sqlite3.connect("data/projects/97a7849a/project.db"); ctx = _load_camera_context(conn, camera); conn.close()
    video = ctx["video"]; fps = float(video["fps"])
    calib = get_calibration_params("97a7849a", ctx["intersection_id"]); mode_cfg = get_processing_mode_config("balanced")
    sug = json.loads(Path(args.suggestion).read_text())
    rec_start = datetime.fromisoformat(video["recording_start_datetime"])
    t0 = datetime.fromisoformat(f"{rec_start.date().isoformat()}T{args.start_hms}")
    s = int((t0 - rec_start).total_seconds() * fps); e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"),
                                          total_frames=video["total_frames"])
    pq = parquet_path("97a7849a", camera, chash, DEFAULT_VARIANT)

    td = Path("data/projects/97a7849a/_hybrid_tmp"); td.mkdir(exist_ok=True)
    try:
        bt, oc = td / "bt.db", td / "oc.db"
        if not (args.reuse and bt.exists() and oc.exists()):
            retrack(bt, "bytetrack", video, ctx, calib, mode_cfg, sug, s, e, pq, camera)
            retrack(oc, "ocsort", video, ctx, calib, mode_cfg, sug, s, e, pq, camera)
        else:
            print("(reusing cached retracked DBs)")
        hdr = f"{'config':<30} {'agg_err':>8} {'total':>6}  " + "  ".join(f"L{l}{m[:3]}" for l, m in WATCH)
        print(f"window {args.start_hms}+{args.minutes}min\n"); print(hdr); print("-"*len(hdr))
        for name, dbp in (("ByteTrack-only", bt), ("OC-SORT-only", oc)):
            a0, t0c, cm = agg(dbp)
            print(f"{name:<30} {a0:>7.1f}% {t0c:>6}  " + "  ".join(f"{cm.get(c,{}).get('ours',0):>5}" for c in WATCH))

        # full column list (minus event_id) for robust cross-DB copy
        cc = sqlite3.connect(str(oc))
        cols = [r[1] for r in cc.execute("PRAGMA table_info(vehicle_events)").fetchall() if r[1] != "event_id"]
        cc.close()
        collist = ",".join(cols)

        def run_variant(label, oc_reject_sql, bt_take_sql):
            """oc_reject_sql: WHERE clause for OC events to DROP (rejected=1).
            bt_take_sql: WHERE clause for BT events to COPY in (rejected forced 0)."""
            c = sqlite3.connect(str(oc))
            c.execute("ATTACH DATABASE ? AS btdb", (str(bt),))
            c.execute("UPDATE vehicle_events SET rejected=0 WHERE camera_id=?", (camera,))
            c.execute("DELETE FROM vehicle_events WHERE camera_id=? AND vehicle_track_id=-999", (camera,))
            c.execute(f"UPDATE vehicle_events SET rejected=1 WHERE camera_id=? AND ({oc_reject_sql})", (camera,))
            # copy matching BT rows in as fresh rows (event_id auto), tag track_id=-999
            sel = collist.replace("vehicle_track_id", "-999 AS vehicle_track_id").replace("rejected", "0 AS rejected")
            n = c.execute(f"INSERT INTO vehicle_events ({collist}) SELECT {sel} FROM btdb.vehicle_events "
                          f"WHERE camera_id=? AND ({bt_take_sql})", (camera,)).rowcount
            c.commit(); c.execute("DETACH DATABASE btdb"); c.close()
            a1, t1, cm1 = agg(oc)
            print(f"{label:<30} {a1:>7.1f}% {t1:>6}  " + "  ".join(f"{cm1.get(cw,{}).get('ours',0):>5}" for cw in WATCH)
                  + f"   (+{n} BT)")

        turns_sql = "movement IN ('left','right','uturn','u_turn')"
        # Variant A: ByteTrack for ALL throughs, OC-SORT for turns
        run_variant("HYBRID A: BT-thru + OC-turn", f"NOT ({turns_sql})", f"NOT ({turns_sql})")
        # Variant B: swap ONLY SB-through (L22 through) to ByteTrack; rest stays OC-SORT
        run_variant("HYBRID B: BT SB-thru swap", "origin_leg_id=22 AND movement='through'",
                    "origin_leg_id=22 AND movement='through'")
        # Variant C: BT for both arterial throughs (L22+L23), OC for turns+rest
        run_variant("HYBRID C: BT both-thru swap", "movement='through'", "movement='through'")

        c = sqlite3.connect(str(oc)); c.execute("UPDATE vehicle_events SET rejected=0 WHERE camera_id=? AND vehicle_track_id!=-999", (camera,)); c.commit(); c.close()
        _, _, cm0 = agg(oc)
        print(f"{'(manual)':<30} {'':>8} {1211:>6}  " + "  ".join(f"{cm0.get(cw,{}).get('manual',0):>5.0f}" for cw in WATCH))
    finally:
        pass  # keep cached DBs in _hybrid_tmp for --reuse
    return 0


if __name__ == "__main__":
    sys.exit(main())
