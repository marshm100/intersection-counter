r"""Item 4 (2026-10-01): which detector-head setting loses cam3's dawn cars?

Arm d2 (end2end off + class-agnostic NMS iou 0.6 + FP16) won cam1 per vehicle but lost
~20 faint dawn cars on cam3 (no box under the click). This runs each setting ALONE on the
frames where the operator clicked (journey labels), a fresh model per setting (the predictor
caches its arguments), and reports per setting: clicks with a box under them (padded box,
+-1 frame), and duplicate pairs a frame (IoU > 0.8, any class).
Usage: .venv/Scripts\python.exe -X utf8 scripts/probe_detector_settings.py CLIP [CLIP ...]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import YOLO_CONFIDENCE_THRESHOLD, YOLO_IMGSZ, YOLO_IOU_THRESHOLD, YOLO_MODEL  # noqa: E402
from backend.services.journey_labels import list_labels  # noqa: E402

PROJ = "97a7849a"
CLASSES = [2, 3, 5, 7]
SETTINGS = {
    "ft2-s 640 (cam3 prod)": {"iou": YOLO_IOU_THRESHOLD, "_model": "yolo26s_ft2.pt", "imgsz": 640,
                              "_classes": [0, 1, 2, 3]},           # finetune_v2 class map
    "ft2-s 640 o2m+agn 0.6": {"end2end": False, "agnostic_nms": True, "iou": 0.6,
                              "_model": "yolo26s_ft2.pt", "imgsz": 640, "_classes": [0, 1, 2, 3]},
    "pl1 1280 o2m+agn 0.6":  {"end2end": False, "agnostic_nms": True, "iou": 0.6,
                              "_model": "models/yolo26s_pl1.pt", "imgsz": 1280,
                              "_classes": [0, 1, 2, 3]},       # step 3, pseudo-labelled
    "s 960 (cam4/5 prod)":   {"iou": YOLO_IOU_THRESHOLD, "_model": "yolo26s.pt", "imgsz": 960},
    "s 960 o2m+agn 0.6":     {"end2end": False, "agnostic_nms": True, "iou": 0.6,
                              "_model": "yolo26s.pt", "imgsz": 960},
    "base (l 1280)":         {"iou": YOLO_IOU_THRESHOLD},
    "fp16 only":             {"iou": YOLO_IOU_THRESHOLD, "half": True},
    "o2m+agnostic 0.6 (d2)": {"end2end": False, "agnostic_nms": True, "iou": 0.6},
    "o2m+class-aware 0.6":   {"end2end": False, "agnostic_nms": False, "iou": 0.6},
    "o2m+agnostic 0.8":      {"end2end": False, "agnostic_nms": True, "iou": 0.8},
}


def iou_pairs(b: np.ndarray, thr: float = 0.8) -> int:
    n = 0
    for i in range(len(b)):
        for j in range(i + 1, len(b)):
            x1, y1 = max(b[i, 0], b[j, 0]), max(b[i, 1], b[j, 1])
            x2, y2 = min(b[i, 2], b[j, 2]), min(b[i, 3], b[j, 3])
            inter = max(0, x2 - x1) * max(0, y2 - y1)
            a = (b[i, 2] - b[i, 0]) * (b[i, 3] - b[i, 1]) + (b[j, 2] - b[j, 0]) * (b[j, 3] - b[j, 1])
            if inter / max(a - inter, 1e-6) > thr:
                n += 1
    return n


def main() -> int:
    from ultralytics import YOLO
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    for clip in [a for a in sys.argv[1:] if not a.startswith("--")]:
        labels = list_labels(PROJ, clip)
        vid = labels[0]["video_id"]
        path, = con.execute("SELECT path FROM videos WHERE video_id=?", (vid,)).fetchone()
        clicks = [(lb[f"{s}_frame"], lb[f"{s}_x"], lb[f"{s}_y"]) for lb in labels
                  for s in ("entry", "exit") if lb.get(f"{s}_frame") is not None]
        frames: dict = {}
        cap = cv2.VideoCapture(path)
        for f in sorted({int(f) + d for f, _, _ in clicks for d in (-1, 0, 1)}):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, img = cap.read()
            if ok:
                frames[f] = img
        print(f"\n{clip}: {len(clicks)} clicks, {len(frames)} frames")
        only = [a for a in sys.argv[1:] if a.startswith("--only=")]
        for name, kw in SETTINGS.items():
            if only and only[0][7:] not in name:
                continue
            kw = dict(kw)
            model = YOLO(kw.pop("_model", YOLO_MODEL))
            imgsz = kw.pop("imgsz", YOLO_IMGSZ)
            classes = kw.pop("_classes", CLASSES)
            boxes: dict = {}
            confs: dict = {}
            keys = sorted(frames)
            for i in range(0, len(keys), 16):
                batch = keys[i:i + 16]
                res = model([frames[k] for k in batch], conf=YOLO_CONFIDENCE_THRESHOLD,
                             imgsz=imgsz, classes=classes, verbose=False, **kw)
                for k, r in zip(batch, res):
                    boxes[k] = (r.boxes.xyxy.cpu().numpy() if r.boxes is not None else np.zeros((0, 4)))
                    confs[k] = (r.boxes.conf.cpu().numpy() if r.boxes is not None else np.zeros(0))
            hit = hit35 = 0
            for f, x, y in clicks:
                ok = ok35 = False
                for d in (-1, 0, 1):
                    b = boxes.get(int(f) + d, np.zeros((0, 4)))
                    if len(b):
                        cx, cy = (b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2
                        w, h = b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]
                        m = (np.abs(x - cx) <= w * 0.75) & (np.abs(y - cy) <= h * 0.75)
                        ok |= bool(m.any())
                        ok35 |= bool((m & (confs[int(f) + d] >= 0.35)).any())
                hit += ok
                hit35 += ok35
            dups = np.mean([iou_pairs(b) for b in boxes.values()])
            print(f"  {name:24} clicks with a box {hit:4}/{len(clicks)} (conf>=0.35: {hit35:4})   "
                  f"dup pairs/frame {dups:.2f}   boxes/frame {np.mean([len(b) for b in boxes.values()]):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
