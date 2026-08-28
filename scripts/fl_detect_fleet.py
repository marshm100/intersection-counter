"""G-FP-2 fleet re-detect: cams 1/4/5 study windows under the shipped
counted_path recipe (yolo26l@1280, conf floor 0.10, CUDA) -> fl_study_*
cache variants. Scratch-only; resumable (existing variants skipped).

Usage:  py -X utf8 scripts/fl_detect_fleet.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT = "97a7849a"
VEHICLE_CLASSES = {2, 3, 5, 7}
JOBS = [(1, "study_0700", 251980, 323980), (1, "study_1600", 575980, 647980),
        (4, "study_0700", 251980, 323980), (4, "study_1100", 395980, 467980),
        (4, "study_1600", 575980, 647980),
        (5, "study_0700", 251980, 323980), (5, "study_1100", 395980, 467980),
        (5, "study_1600", 575980, 647980)]


def main() -> int:
    import cv2
    import pyarrow as pa
    import pyarrow.parquet as pq_mod
    from backend.services.detection_cache import cache_exists, parquet_path
    from ultralytics import YOLO

    con = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    vids = {c: (p, h) for c, p, h in con.execute(
        "SELECT camera_id, path, content_hash FROM videos "
        "WHERE camera_id IN (1,4,5)")}
    con.close()
    model = YOLO("yolo26l.pt", task="detect")
    for cam, W, f_lo, f_hi in JOBS:
        vpath, chash = vids[cam]
        pq = Path(parquet_path(PROJECT, cam, chash, f"fl_{W}"))
        if cache_exists(pq):
            print(f"[cam{cam} {W}] exists, skip", flush=True)
            continue
        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        cols = {k: [] for k in ("frame_idx", "bbox_x1", "bbox_y1", "bbox_x2",
                                "bbox_y2", "confidence", "class_id")}
        n = 0
        t0 = time.perf_counter()
        for f in range(f_lo, f_hi):
            ok, img = cap.read()
            if not ok:
                break
            r = model(img, conf=0.10, imgsz=1280, verbose=False, device=0)[0]
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
        cap.release()
        wall = time.perf_counter() - t0
        schema = pa.schema([("frame_idx", pa.uint32()), ("bbox_x1", pa.float32()),
                            ("bbox_y1", pa.float32()), ("bbox_x2", pa.float32()),
                            ("bbox_y2", pa.float32()), ("confidence", pa.float32()),
                            ("class_id", pa.uint8())])
        pq.parent.mkdir(parents=True, exist_ok=True)
        pq_mod.write_table(pa.table(cols, schema=schema), str(pq))
        pq.with_suffix(".meta.json").write_text(json.dumps(
            {"camera_id": cam, "content_hash": chash,
             "method": "blake2b-128m-v1", "model": "yolo26l.pt",
             "imgsz": 1280, "confidence": 0.10, "detection_skip": 1,
             "windows": [[f_lo, f_hi]], "total_detections": n,
             "wall_seconds": round(wall, 1),
             "derived_from": "G-FP-2 fleet re-detect (counted_path recipe)"},
            indent=2))
        print(f"[cam{cam} {W}] {n} dets in {wall/60:.0f} min "
              f"({(f_hi-f_lo)/wall:.1f} fps)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
