"""Articulated (semi-truck) re-classification — §3-D (2026-07-06).

A COCO 'truck' is re-bucketed from single-unit to articulated (FHWA 9) when its
LENGTH exceeds ARTICULATED_LEN_RATIO x the local car-size baseline — a view-
invariant size test (bbox aspect ratio fails at approach-angle cameras, where a
truck is near-square). Baseline and truck lengths both come from the run's own
DETECTION CACHE (blind, no ground truth). A post-processing pass over a completed
run's tracked vehicles.

Validated offline on FM51: ~95 articulated ~= Miovision's 102 at K=2.0. Pure size
test lives in classifier.is_articulated; this module does the cache + DB plumbing.
See memory project_articulated_classification_2026_07_06.
"""
from __future__ import annotations
import glob, json, shutil, sqlite3, tempfile
from collections import defaultdict
from pathlib import Path

from backend.config import (ARTICULATED_BAND_PX, ARTICULATED_LEN_RATIO,
                            ARTICULATED_MIN_CARS_PER_BAND)
from backend.database import get_db_path
from backend.services.classifier import build_car_length_baseline, is_articulated

_MATCH_RADIUS_PX = 90.0
_MIN_MATCHED_FRAMES = 2


def _find_cache_parquet(project_id: str, camera_id: int) -> Path | None:
    """Largest .parquet under detections/<camera>/ — the substantive run (a tiny
    preview variant may sit alongside the full one)."""
    root = get_db_path(project_id).parent / "detections" / str(camera_id)
    pqs = list(root.glob("*/*.parquet"))
    return max(pqs, key=lambda p: p.stat().st_size) if pqs else None


def _read_cache(pq_path: Path):
    """(frame_idx -> [(cx,cy,length) trucks], [(length,center_y) cars]). Copies out
    of the OneDrive path first — reading in place intermittently hits WinError 5."""
    import pyarrow.parquet as pq
    cols = ["frame_idx", "class_id", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2"]
    try:
        tbl = pq.read_table(str(pq_path), columns=cols)
    except (PermissionError, OSError):
        tmp = Path(tempfile.gettempdir()) / ("artic_" + pq_path.name)
        shutil.copy2(pq_path, tmp)
        try:
            tbl = pq.read_table(str(tmp), columns=cols)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    d = tbl.to_pydict()
    frame_trucks: dict = defaultdict(list)
    car_samples: list = []
    for i in range(len(d["frame_idx"])):
        w = d["bbox_x2"][i] - d["bbox_x1"][i]
        h = d["bbox_y2"][i] - d["bbox_y1"][i]
        if w <= 0 or h <= 0:
            continue
        cx = (d["bbox_x1"][i] + d["bbox_x2"][i]) / 2
        cy = (d["bbox_y1"][i] + d["bbox_y2"][i]) / 2
        L = max(w, h)
        cid = d["class_id"][i]
        if cid == 7:
            frame_trucks[d["frame_idx"][i]].append((cx, cy, L))
        elif cid == 2:
            car_samples.append((L, cy))
    return frame_trucks, car_samples


def _vehicle_length(traj, sf, ef, frame_trucks):
    """Max matched truck-detection length over a vehicle's frames + the center-y at
    that max (the vehicle's fullest-visible extent). Scans EVERY frame in the
    vehicle's range (not just the sampled trajectory points) so it links tracks the
    sparse-point match misses. None if too few matches."""
    n = len(traj)
    span = ef - sf
    if n < 2 or span <= 0:
        return None
    best_L = 0.0
    best_y = None
    hits = 0
    r2 = _MATCH_RADIUS_PX * _MATCH_RADIUS_PX
    # A long stuck/merged track would be slow to scan frame-by-frame; cap it.
    step = max(1, span // 4000)
    for f in range(sf, ef + 1, step):
        dets = frame_trucks.get(f)
        if not dets:
            continue
        k = min(n - 1, max(0, round((f - sf) / span * (n - 1))))
        tx, ty = traj[k]
        for (cx, cy, L) in dets:
            if (cx - tx) ** 2 + (cy - ty) ** 2 < r2:
                hits += 1
                if L > best_L:
                    best_L = L
                    best_y = cy
                break
    if hits < _MIN_MATCHED_FRAMES or best_y is None:
        return None
    return best_L, best_y


def reclassify_articulated(project_id: str, camera_id: int, *, apply: bool = False,
                           ratio: float | None = None, band_px: float | None = None,
                           min_cars: int | None = None) -> dict:
    """Re-bucket a camera's single-unit trucks to articulated by the view-invariant
    size test. Dry-run by default; apply=True writes vehicle_class/fhwa_class.

    Prefers each vehicle's STORED bbox_length/bbox_center_y (exact, from the tracker
    -> no linking, zero undecidable). Falls back to linking the detection cache for
    already-processed runs whose events predate the stored columns. Returns a
    counts dict."""
    ratio = ARTICULATED_LEN_RATIO if ratio is None else ratio
    band_px = ARTICULATED_BAND_PX if band_px is None else band_px
    min_cars = ARTICULATED_MIN_CARS_PER_BAND if min_cars is None else min_cars

    conn = sqlite3.connect(str(get_db_path(project_id)), timeout=10)
    # The stored-size columns may not exist on a project last written before the
    # §3-D migration (e.g. FM51) — degrade to cache-linking rather than error.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(vehicle_events)")}
    has_bbox = "bbox_length" in cols and "bbox_center_y" in cols
    if has_bbox:
        trucks = conn.execute(
            "SELECT rowid, bbox_length, bbox_center_y, trajectory_data, start_frame, frame_number "
            "FROM vehicle_events WHERE camera_id=? AND vehicle_class='single_unit_truck' "
            "AND COALESCE(rejected,0)=0", (camera_id,)).fetchall()
        stored_cars = conn.execute(
            "SELECT bbox_length, bbox_center_y FROM vehicle_events WHERE camera_id=? "
            "AND vehicle_class='car' AND bbox_length IS NOT NULL AND bbox_center_y IS NOT NULL "
            "AND COALESCE(rejected,0)=0", (camera_id,)).fetchall()
    else:
        trucks = [(rid, None, None, tj, sf, ef) for rid, tj, sf, ef in conn.execute(
            "SELECT rowid, trajectory_data, start_frame, frame_number FROM vehicle_events "
            "WHERE camera_id=? AND vehicle_class='single_unit_truck' AND COALESCE(rejected,0)=0",
            (camera_id,)).fetchall()]
        stored_cars = []

    # Baseline: prefer stored car sizes; else the detection cache's car detections.
    frame_trucks = None
    if len(stored_cars) >= min_cars:
        baseline = build_car_length_baseline(stored_cars, band_px, min_cars)
        source = "stored"
    else:
        pqp = _find_cache_parquet(project_id, camera_id)
        if pqp is None:
            conn.close()
            return {"error": "no stored car sizes and no detection cache",
                    "candidates": len(trucks), "articulated": 0}
        frame_trucks, car_samples = _read_cache(pqp)
        baseline = build_car_length_baseline(car_samples, band_px, min_cars)
        source = "cache"

    artic_ids: list = []
    n_single = 0
    n_undecidable = 0
    n_linked = 0
    for rid, blen, bcy, tj, sf, ef in trucks:
        if blen is not None and bcy is not None:
            length, cy = blen, bcy                       # exact stored size
        else:
            if frame_trucks is None:                     # need the cache to link
                pqp = _find_cache_parquet(project_id, camera_id)
                frame_trucks = _read_cache(pqp)[0] if pqp else {}
            if not tj or sf is None or ef is None or ef <= sf:
                n_undecidable += 1
                continue
            vl = _vehicle_length(json.loads(tj), sf, ef, frame_trucks)
            if vl is None:
                n_undecidable += 1
                continue
            length, cy = vl
            n_linked += 1
        a = is_articulated(length, cy, baseline, ratio=ratio, band_px=band_px)
        if a is None:
            n_undecidable += 1
        elif a:
            artic_ids.append(rid)
        else:
            n_single += 1

    result = {"candidates": len(trucks), "articulated": len(artic_ids),
              "single_unit": n_single, "undecidable": n_undecidable,
              "baseline_bands": len(baseline), "ratio": ratio,
              "baseline_source": source, "cache_linked": n_linked, "applied": False}
    if apply and artic_ids:
        conn.executemany(
            "UPDATE vehicle_events SET vehicle_class='multi_unit_truck', fhwa_class=9 WHERE rowid=?",
            [(i,) for i in artic_ids])
        conn.commit()
        result["applied"] = True
    conn.close()
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Re-classify single-unit trucks as articulated by size")
    ap.add_argument("--project", required=True)
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--ratio", type=float, default=None)
    ap.add_argument("--apply", action="store_true", help="write to the DB (default: dry-run)")
    a = ap.parse_args()
    print(reclassify_articulated(a.project, a.camera, apply=a.apply, ratio=a.ratio))
