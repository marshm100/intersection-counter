"""Identity-stack C2 — the full three-window re-detect (operator go
2026-08-26: yolo26l@1280).

Writes id_study_<W> cache variants (the C1 winner recipe, CUDA, conf
floor 0.08 superset, vehicle classes {2,3,5,7}) beside the production
study caches. Scratch-only; production caches, dumps, and DB untouched.
Resumable: a window whose cache already exists is skipped, so a crashed
run relaunches safely.

Usage:
  py -X utf8 scripts/id_detect_full.py              # all three windows
  py -X utf8 scripts/id_detect_full.py --windows study_1600
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from id_detect_bin import CONF_FLOOR, VEHICLE_CLASSES, _video

WEIGHTS, IMGSZ = "yolo26l.pt", 1280        # the C1 winner
WINDOWS = {
    "study_0700": (629950, 809950),
    "study_1100": (989950, 1169950),
    "study_1600": (1439950, 1619950),
}
PROJECT, CAMERA = "97a7849a", 2


def detect_window(win: str, v: dict, chash: str) -> None:
    import cv2
    import pyarrow as pa
    import pyarrow.parquet as pq_mod
    from backend.services.detection_cache import cache_exists, parquet_path
    from ultralytics import YOLO

    f_lo, f_hi = WINDOWS[win]
    pq = Path(parquet_path(PROJECT, CAMERA, chash, f"id_{win}"))
    if cache_exists(pq):
        print(f"[{win}] cache exists, skip", flush=True)
        return
    model = YOLO(WEIGHTS, task="detect")
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
        r = model(img, conf=CONF_FLOOR, imgsz=IMGSZ, verbose=False,
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
        if (f - f_lo) % 22500 == 0:
            el = time.perf_counter() - t0
            print(f"[{win}] frame {f - f_lo}/{f_hi - f_lo} ({n} dets, "
                  f"{(f - f_lo + 1) / el:.1f} fps)", flush=True)
    cap.release()
    wall = time.perf_counter() - t0
    schema = pa.schema([("frame_idx", pa.uint32()), ("bbox_x1", pa.float32()),
                        ("bbox_y1", pa.float32()), ("bbox_x2", pa.float32()),
                        ("bbox_y2", pa.float32()), ("confidence", pa.float32()),
                        ("class_id", pa.uint8())])
    pq_mod.write_table(pa.table(cols, schema=schema), str(pq))
    pq.with_suffix(".meta.json").write_text(json.dumps(
        {"method": "id_stack_c2", "model": WEIGHTS, "imgsz": IMGSZ,
         "confidence": CONF_FLOOR, "device": "cuda", "detection_skip": 1,
         "windows": [[f_lo, f_hi]], "total_detections": n,
         "wall_seconds": round(wall, 1),
         "detect_fps": round((f_hi - f_lo) / wall, 2),
         "classes": sorted(VEHICLE_CLASSES)}, indent=2))
    print(f"[{win}] wrote {n} dets in {wall / 3600:.2f} h "
          f"({(f_hi - f_lo) / wall:.1f} fps CUDA)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default="study_0700,study_1100,study_1600")
    args = ap.parse_args()
    wins = [w.strip() for w in args.windows.split(",") if w.strip()]
    for w in wins:
        if w not in WINDOWS:
            raise SystemExit(f"unknown window {w}")
    v = _video()
    for w in wins:
        detect_window(w, v, v["content_hash"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
