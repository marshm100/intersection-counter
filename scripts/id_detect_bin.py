"""Identity-stack Pillar C1 — the recall probe (one 15-min bin, CUDA).

The R0 verdict: the volume deficit is detection-dark — no identity or
evidence fix can recover vehicles the detector never saw. Before any
full re-detect spend, measure what stronger recipes actually find in
the WORST deficit bin (cam2 16:15, SB short ~270): detect the single
bin under candidate recipes, then the detector_zone_recall comparison
against the production study cache (same bin, common frames) at conf
0.10 / 0.25, plus the novel-detection rate (accurate dets with no
production det within 25 px — vehicles production does not see AT
ALL). The CUDA detect rate is recorded per recipe -> the full
re-detect cost estimate is measured, not guessed.

Scratch-only: writes cache VARIANTS (id_<recipe>) beside the study
caches; production caches and DB untouched (the C2 decision + G-ID-1
gate own any promotion).

Usage:
  py -X utf8 scripts/id_detect_bin.py                 # all three recipes
  py -X utf8 scripts/id_detect_bin.py --recipes l1280 # subset
  py -X utf8 scripts/id_detect_bin.py --measure-only  # table from existing caches
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

PROJECT = "97a7849a"
CAMERA = 2
BIN = (1462450, 1484950)          # 16:15-16:30 video frames (25 fps)
CONF_FLOOR = 0.08                 # below both cut points; superset cache
VEHICLE_CLASSES = {2, 3, 5, 7}    # the study-cache class set (COCO)
RECIPES = {
    "l1280": ("yolo26l.pt", 1280),
    "l960": ("yolo26l.pt", 960),
    "s1280": ("yolo26s.pt", 1280),
}


def _video():
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    conn.row_factory = sqlite3.Row
    v = dict(conn.execute(
        "SELECT * FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (CAMERA,)).fetchone())
    conn.close()
    return v


def detect(recipe: str, v: dict, chash: str) -> Path:
    import cv2
    import pyarrow as pa
    import pyarrow.parquet as pq_mod
    from backend.services.detection_cache import cache_exists, parquet_path
    from ultralytics import YOLO

    weights, imgsz = RECIPES[recipe]
    pq = Path(parquet_path(PROJECT, CAMERA, chash, f"id_{recipe}"))
    if cache_exists(pq):
        print(f"[{recipe}] cache exists, skip", flush=True)
        return pq
    model = YOLO(weights, task="detect")
    f_lo, f_hi = BIN
    cap = cv2.VideoCapture(v["path"])
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
    cols = {k: [] for k in ("frame_idx", "bbox_x1", "bbox_y1", "bbox_x2",
                            "bbox_y2", "confidence", "class_id")}
    n = 0
    t0 = time.perf_counter()
    for f in range(f_lo, f_hi):
        ok, img = cap.read()
        if not ok:
            break
        r = model(img, conf=CONF_FLOOR, imgsz=imgsz, verbose=False,
                  device=0)[0]
        for b in r.boxes:
            cid = int(b.cls[0])
            if cid not in VEHICLE_CLASSES:
                continue
            x1, y1, x2, y2 = (float(x) for x in b.xyxy[0])
            cols["frame_idx"].append(f)
            cols["bbox_x1"].append(x1); cols["bbox_y1"].append(y1)
            cols["bbox_x2"].append(x2); cols["bbox_y2"].append(y2)
            cols["confidence"].append(float(b.conf[0]))
            cols["class_id"].append(cid)
            n += 1
        if (f - f_lo) % 4500 == 0:
            el = time.perf_counter() - t0
            print(f"[{recipe}] frame {f - f_lo}/{f_hi - f_lo} ({n} dets, "
                  f"{(f - f_lo + 1) / el:.1f} fps)", flush=True)
    cap.release()
    wall = time.perf_counter() - t0
    schema = pa.schema([("frame_idx", pa.uint32()), ("bbox_x1", pa.float32()),
                        ("bbox_y1", pa.float32()), ("bbox_x2", pa.float32()),
                        ("bbox_y2", pa.float32()), ("confidence", pa.float32()),
                        ("class_id", pa.uint8())])
    pq.parent.mkdir(parents=True, exist_ok=True)
    pq_mod.write_table(pa.table(cols, schema=schema), str(pq))
    pq.with_suffix(".meta.json").write_text(json.dumps(
        {"method": "id_stack_c1_probe", "model": weights, "imgsz": imgsz,
         "confidence": CONF_FLOOR, "device": "cuda",
         "detection_skip": 1, "windows": [list(BIN)],
         "total_detections": n, "wall_seconds": round(wall, 1),
         "detect_fps": round((BIN[1] - BIN[0]) / wall, 2),
         "classes": sorted(VEHICLE_CLASSES)}, indent=2))
    print(f"[{recipe}] wrote {n} dets in {wall:.0f}s "
          f"({(BIN[1] - BIN[0]) / wall:.1f} fps CUDA)", flush=True)
    return pq


def measure(recipes: list[str], chash: str) -> None:
    from detector_zone_recall import (ZONES, load_curves, novel_per_frame,
                                      summarize)
    from backend.services.detection_cache import parquet_path

    f_lo, f_hi = BIN
    study = pd.read_parquet(parquet_path(PROJECT, CAMERA, chash, "study_1600"))
    study = study[(study.frame_idx >= f_lo) & (study.frame_idx < f_hi)]
    n_frames = f_hi - f_lo
    print(f"\n=== C1 recall probe, cam2 bin 16:15-16:30 "
          f"({n_frames} frames; radius 30px; production = yolo26s@960 c0.10)")
    for role in ("failing", "control"):
        name, kind, ids = ZONES[CAMERA][role]
        curves = load_curves(CAMERA, kind, ids)
        rows = [summarize("production_s960", study, curves, 30.0, n_frames)]
        novel = {}
        for rec in recipes:
            pq = Path(parquet_path(PROJECT, CAMERA, chash, f"id_{rec}"))
            acc = pd.read_parquet(pq)
            meta = json.loads(pq.with_suffix(".meta.json").read_text())
            r = summarize(f"id_{rec}", acc, curves, 30.0, n_frames)
            r["fps"] = meta.get("detect_fps")
            rows.append(r)
            novel[rec] = novel_per_frame(acc, study, curves, 30.0, n_frames)
        print(f"\n  [{role.upper()}] {name}")
        print(f"    {'recipe':<16}{'dets/f >=.10':>13}{'>=.25':>9}"
              f"{'entry >=.10':>13}{'>=.25':>9}{'CUDA fps':>10}")
        for r in rows:
            print(f"    {r['tag']:<16}{r['per_frame_0.1']:>13.3f}"
                  f"{r['per_frame_0.25']:>9.3f}{r['entry_pf_0.1']:>13.3f}"
                  f"{r['entry_pf_0.25']:>9.3f}"
                  f"{r.get('fps') or '':>10}")
        for rec, (npf, nfrac) in novel.items():
            print(f"    id_{rec}: NOVEL >=0.25 in-zone dets "
                  f"{npf:.3f}/frame = {nfrac * 100:.1f}% of its in-zone dets")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipes", default="l1280,l960,s1280")
    ap.add_argument("--measure-only", action="store_true")
    args = ap.parse_args()
    recipes = [r.strip() for r in args.recipes.split(",") if r.strip()]
    for r in recipes:
        if r not in RECIPES:
            raise SystemExit(f"unknown recipe {r}")
    v = _video()
    chash = v["content_hash"]
    if not args.measure_only:
        for r in recipes:
            detect(r, v, chash)
    measure(recipes, chash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
