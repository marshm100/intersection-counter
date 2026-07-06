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
from backend.services.classifier import build_car_length_baseline, is_articulated

_MATCH_RADIUS_PX = 60.0
_MIN_MATCHED_FRAMES = 3


def _find_cache_parquet(project_id: str, camera_id: int) -> Path | None:
    """Largest .parquet under detections/<camera>/ — the substantive run (a tiny
    preview variant may sit alongside the full one)."""
    root = Path("data/projects") / project_id / "detections" / str(camera_id)
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
    that max (the vehicle's fullest-visible extent). None if too few matches."""
    n = len(traj)
    if n < 2:
        return None
    best_L = 0.0
    best_y = None
    hits = 0
    r2 = _MATCH_RADIUS_PX * _MATCH_RADIUS_PX
    for k, (x, y) in enumerate(traj):
        fi = int(round(sf + k * (ef - sf) / (n - 1)))
        for (cx, cy, L) in frame_trucks.get(fi, ()):
            if (cx - x) ** 2 + (cy - y) ** 2 < r2:
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
    Returns a counts dict."""
    ratio = ARTICULATED_LEN_RATIO if ratio is None else ratio
    band_px = ARTICULATED_BAND_PX if band_px is None else band_px
    min_cars = ARTICULATED_MIN_CARS_PER_BAND if min_cars is None else min_cars

    pqp = _find_cache_parquet(project_id, camera_id)
    if pqp is None:
        return {"error": "no detection cache", "candidates": 0, "articulated": 0}
    frame_trucks, car_samples = _read_cache(pqp)
    baseline = build_car_length_baseline(car_samples, band_px, min_cars)

    conn = sqlite3.connect(f"data/projects/{project_id}/project.db", timeout=10)
    rows = conn.execute(
        "SELECT rowid, trajectory_data, start_frame, frame_number FROM vehicle_events "
        "WHERE camera_id=? AND vehicle_class='single_unit_truck' AND COALESCE(rejected,0)=0",
        (camera_id,)).fetchall()
    artic_ids: list = []
    n_single = 0
    n_undecidable = 0
    for rid, tj, sf, ef in rows:
        if not tj or sf is None or ef is None or ef <= sf:
            n_undecidable += 1
            continue
        vl = _vehicle_length(json.loads(tj), sf, ef, frame_trucks)
        if vl is None:
            n_undecidable += 1
            continue
        a = is_articulated(vl[0], vl[1], baseline, ratio=ratio, band_px=band_px)
        if a is None:
            n_undecidable += 1
        elif a:
            artic_ids.append(rid)
        else:
            n_single += 1

    result = {"candidates": len(rows), "articulated": len(artic_ids),
              "single_unit": n_single, "undecidable": n_undecidable,
              "baseline_bands": len(baseline), "ratio": ratio, "applied": False}
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
