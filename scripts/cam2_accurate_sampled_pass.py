"""One-off sampled accurate-profile detection pass for the Task-1 detector spike.

cam2 has no accurate_1280 cache; re-detecting the full 30-min window at 25 fps
would be ~7 h on CPU. Instead: every 25th frame (1 Hz) over 07:00-07:30
(frames 629950..674950), yolo26l (OpenVINO export, imgsz 1280, conf 0.08,
iou 0.45, vehicle classes) — the exact accurate-mode detector settings.
Output parquet mirrors the detection-cache schema so the zone analysis can
treat it like any cache. Miovision is NOT consumed here (dev spike, raw video
+ operator calibration only).
"""
import sqlite3
import sys, time
from pathlib import Path

import cv2
import pandas as pd
from ultralytics import YOLO

REPO = Path(__file__).resolve().parent.parent
VID = sqlite3.connect(str(REPO / "data/projects/97a7849a/project.db")).execute(
    "SELECT path FROM videos WHERE camera_id=2").fetchone()[0]
START, END, STEP = 629950, 674950, 25  # 07:00-07:30 @25fps, sampled at 1 Hz
OUT = (Path(sys.argv[1]) if len(sys.argv) > 1
       else REPO / "evaluations/cam2_accurate1280_sampled.parquet")

def main():
    m = YOLO(str(REPO / "yolo26l_openvino_model"), task="detect")
    cap = cv2.VideoCapture(VID)
    cap.set(cv2.CAP_PROP_POS_FRAMES, START)
    rows = {k: [] for k in ("frame_idx", "bbox_x1", "bbox_y1", "bbox_x2",
                            "bbox_y2", "confidence", "class_id")}
    t0 = time.time()
    n_frames = 0
    fi = START
    while fi < END:
        ok = cap.grab()
        if not ok:
            print(f"grab failed at {fi}", flush=True)
            break
        if (fi - START) % STEP == 0:
            ok, frame = cap.retrieve()
            if not ok:
                print(f"retrieve failed at {fi}", flush=True)
                break
            r = m.predict(frame, imgsz=1280, conf=0.08, iou=0.45,
                          classes=[2, 3, 5, 7], verbose=False)[0]
            for b in r.boxes:
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
                rows["frame_idx"].append(fi)
                rows["bbox_x1"].append(x1); rows["bbox_y1"].append(y1)
                rows["bbox_x2"].append(x2); rows["bbox_y2"].append(y2)
                rows["confidence"].append(float(b.conf[0]))
                rows["class_id"].append(int(b.cls[0]))
            n_frames += 1
            if n_frames % 100 == 0:
                el = time.time() - t0
                print(f"{n_frames}/1800 frames  {len(rows['frame_idx'])} dets"
                      f"  {el:.0f}s  eta {(1800 - n_frames) * el / n_frames:.0f}s",
                      flush=True)
        fi += 1
    cap.release()
    pd.DataFrame(rows).to_parquet(OUT)
    print(f"DONE {n_frames} frames  {len(rows['frame_idx'])} dets -> {OUT}", flush=True)

if __name__ == "__main__":
    sys.exit(main())
