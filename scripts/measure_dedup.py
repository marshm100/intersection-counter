"""Measure the achievable ceiling of a per-vehicle DEDUP pass on OC-SORT output.

Visual gate (screenshots/sb_duplicates_zoom_7am.png) confirmed OC-SORT assigns
2 track-IDs to one westbound vehicle (boxes at 0-29px sep on a ~30px car). This
retracks the 30-min cache WITH the turn-inclusive bank into a temp DB, then merges
duplicate vehicle_events (transitive union-find) and recounts — so we see, on the
REAL pipeline output, how close dedup gets SB-through to manual 424 and the total
to 1211, and whether it over-merges (undercounts other cells).

Merge edge between two events of the SAME movement when EITHER:
  (overlap)   their [start_frame, frame_number] ranges overlap >= ovl frames AND
              the two trajectories are near-identical curves (median nearest-point
              distance <= sep px) -> simultaneous duplicate ID.
  (sequential) A ends <= B starts + gap frames AND A's tail ~ B's head (<= join px)
              -> an ID-switch continuation.

Usage:  py scripts/measure_dedup.py --minutes 30
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import groundtruth
from backend.config import get_processing_mode_config
from backend.database import get_calibration_params, list_trims
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path,
)
from backend.services.pipeline import ProcessingPipeline
from reprocess_camera import _load_camera_context
import per_movement_accuracy as pma
from test_recal_effect import list_paths_for_camera_tmp

WATCH = [(22, "thru"), (23, "thru"), (23, "left"), (22, "left"), (23, "right")]


def _curve_dist(a, b):
    """Median nearest-point distance (symmetric) between two polylines."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    if len(a) == 0 or len(b) == 0:
        return 1e9
    def med_nn(p, q):
        return float(np.median([min(np.hypot(*(q - pt).T)) for pt in p]))
    return max(med_nn(a, b), med_nn(b, a))


def dedup_events(events, sep=20.0, ovl=5, gap=45, join=55.0):
    """events: list of dicts {id, mv, s, e, traj}. Returns set of ids to DELETE
    (all but the longest in each merged group)."""
    n = len(events)
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    for i in range(n):
        ei = events[i]
        for j in range(i + 1, n):
            ej = events[j]
            if ei["mv"] != ej["mv"]:
                continue
            ov = min(ei["e"], ej["e"]) - max(ei["s"], ej["s"])
            if ov >= ovl:
                if _curve_dist(ei["traj"], ej["traj"]) <= sep:
                    union(i, j); continue
            # sequential (order-agnostic)
            for a, b in ((ei, ej), (ej, ei)):
                g = b["s"] - a["e"]
                if 0 <= g <= gap and a["traj"] and b["traj"]:
                    d = math.hypot(a["traj"][-1][0]-b["traj"][0][0], a["traj"][-1][1]-b["traj"][0][1])
                    if d <= join:
                        union(i, j); break
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    to_delete = set()
    for members in groups.values():
        if len(members) <= 1:
            continue
        keep = max(members, key=lambda m: events[m]["e"] - events[m]["s"])
        for m in members:
            if m != keep:
                to_delete.add(events[m]["id"])
    return to_delete


def retrack(tdb, video, ctx, calib, mode_cfg, sug, s, e, pq, camera):
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
            c.execute("INSERT INTO intersection_paths (camera_id, origin_leg_id, destination_leg_id, polyline, movement_label, supporting_count, source, created_at) "
                      "VALUES (?,?,?,?,?,?, 'data-driven', ?)",
                      (camera, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                       p["movement_label"], p.get("supporting_count", 0), now))
        c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (camera,))
    c.close()
    c = sqlite3.connect(str(tdb)); rctx = _load_camera_context(c, camera); c.close()
    paths = list_paths_for_camera_tmp(tdb, camera)
    pipe = ProcessingPipeline(
        project_id="97a7849a", db_path=str(tdb), video_path=video["path"],
        legs=rctx["legs"], fps=float(video["fps"]), video_start_time=video["recording_start_datetime"],
        video_id=video["video_id"], yolo_model=mode_cfg["yolo_model"], yolo_imgsz=mode_cfg["yolo_imgsz"],
        yolo_confidence=mode_cfg["yolo_confidence"], detection_skip=mode_cfg["detection_skip"],
        tracker_match_threshold=mode_cfg.get("tracker_match_threshold"),
        tracker_activation_threshold=0.25, calibration_params=calib, paths=paths, tracker_backend="ocsort")
    pipe._v3_camera_id = camera
    pipe._v3_trim_id = (list_trims("97a7849a", ctx["intersection_id"]) or [{"trim_id": None}])[0]["trim_id"]
    pipe.process_cached(DetectionCacheReader(pq), s, e, detection_skip=mode_cfg["detection_skip"])


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

    tmpdir = Path(tempfile.mkdtemp(prefix="dedup_"))
    try:
        tdb = tmpdir / "recal.db"
        retrack(tdb, video, ctx, calib, mode_cfg, sug, s, e, pq, camera)
        hdr = f"{'config':<28} {'agg_err':>8} {'total':>6}  " + "  ".join(f"L{l}{m[:3]}" for l, m in WATCH)
        print(f"window {args.start_hms}+{args.minutes}min\n"); print(hdr); print("-"*len(hdr))
        a0, t0c, cm0 = agg(tdb)
        print(f"{'baseline (no dedup)':<28} {a0:>7.1f}% {t0c:>6}  " + "  ".join(f"{cm0.get(c,{}).get('ours',0):>5}" for c in WATCH))

        c = sqlite3.connect(str(tdb))
        rows = c.execute("SELECT event_id, movement, start_frame, frame_number, trajectory_data FROM vehicle_events WHERE camera_id=?", (camera,)).fetchall()
        c.close()
        base_events = []
        for eid, mv, sf, ef, tj in rows:
            try:
                traj = json.loads(tj) if tj else []
            except Exception:
                traj = []
            base_events.append({"id": eid, "mv": mv, "s": sf if sf is not None else ef,
                                "e": ef if ef is not None else sf, "traj": traj})

        for label, kw in [("dedup sep20/gap45", dict(sep=20, gap=45, join=55)),
                          ("dedup sep25/gap60", dict(sep=25, gap=60, join=65)),
                          ("dedup sep30/gap90", dict(sep=30, gap=90, join=75))]:
            td = dedup_events(base_events, **kw)
            # apply to a fresh copy of the temp DB counts: mark rejected, recount
            c = sqlite3.connect(str(tdb))
            c.execute("UPDATE vehicle_events SET rejected=0 WHERE camera_id=?", (camera,))
            if td:
                c.executemany("UPDATE vehicle_events SET rejected=1 WHERE event_id=?", [(i,) for i in td])
            c.commit(); c.close()
            a1, t1, cm1 = agg(tdb)
            print(f"{label:<28} {a1:>7.1f}% {t1:>6}  " + "  ".join(f"{cm1.get(c,{}).get('ours',0):>5}" for c in WATCH)
                  + f"   (-{len(td)} events)")
        c = sqlite3.connect(str(tdb)); c.execute("UPDATE vehicle_events SET rejected=0 WHERE camera_id=?", (camera,)); c.commit(); c.close()
        man = "  ".join(f"{cm0.get(c,{}).get('manual',0):>5.0f}" for c in WATCH)
        print(f"{'(manual)':<28} {'':>8} {1211:>6}  {man}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
