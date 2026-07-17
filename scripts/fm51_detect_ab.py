"""FM51 held-out detection A/B (§3-D gate part 1 —
plan_detector_finetune_2026-07-16).

Old model vs fine-tuned model on FM51 footage NEITHER trained on (the
corridor-only training set held FM51 out entirely). Samples frames across
the AM hour and the PM window where the documented −12–20% miss lives, runs
both models per frame, and reports per-15-min detection presence, far-field
(top-third) detections, and the new model's articulated/long counts — with
Miovision's interval volumes printed alongside as the reference trend.
Frame-level presence is a RECALL PROXY (no tracking, no counting chain);
the full-chain comparison is gate part 3.

Usage:
  py scripts/fm51_detect_ab.py --new-weights runs/.../chunkN/weights/last.pt
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT = "0acb12c0"          # the FM51 dress-rehearsal project
CAMERA = 2                    # 405051 FM51-CORD4699 (the audited camera)
WINDOWS = [("AM", "07:00", "08:00"), ("PM", "16:30", "18:00")]


def _video():
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    v = conn.execute("SELECT path, fps, total_frames, recording_start_datetime "
                     "FROM videos WHERE camera_id=?", (CAMERA,)).fetchone()
    conn.close()
    return v


def _mio_intervals():
    """{interval datetime: total volume} from the FM51 Miovision XML (15-min)."""
    from audit_fm51 import load_miovision
    per_iv_total, _a, _c, _d, _e = load_miovision()
    return per_iv_total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new-weights", required=True)
    ap.add_argument("--old-weights", default="yolo26s.pt")
    ap.add_argument("--imgsz-new", type=int, default=640)
    ap.add_argument("--imgsz-old", type=int, default=960)
    ap.add_argument("--stride", type=int, default=50, help="sample every Nth frame")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--out", default="runs/finetune_v1/fm51_ab.json")
    args = ap.parse_args()

    from ultralytics import YOLO
    old = YOLO(args.old_weights)
    new = YOLO(args.new_weights)
    OLD_VEH = [2, 3, 5, 7]           # COCO vehicle classes

    path, fps, total_frames, rec_start = _video()
    t0 = datetime.fromisoformat(rec_start)
    cap = cv2.VideoCapture(path)
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    far_y = H / 3.0                  # top third = far field on this camera

    agg: dict = defaultdict(lambda: defaultdict(float))
    n_frames: dict = defaultdict(int)
    for wname, hs, he in WINDOWS:
        f_lo = int((datetime.fromisoformat(f"{t0.date()}T{hs}:00") - t0)
                   .total_seconds() * fps)
        f_hi = int((datetime.fromisoformat(f"{t0.date()}T{he}:00") - t0)
                   .total_seconds() * fps)
        for f in range(f_lo, min(f_hi, total_frames), args.stride):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, img = cap.read()
            if not ok:
                continue
            wc = t0 + timedelta(seconds=f / fps)
            iv = wc.replace(minute=(wc.minute // 15) * 15, second=0,
                            microsecond=0).isoformat()
            ro = old(img, conf=args.conf, imgsz=args.imgsz_old,
                     classes=OLD_VEH, verbose=False)[0]
            rn = new(img, conf=args.conf, imgsz=args.imgsz_new, verbose=False)[0]
            n_frames[iv] += 1
            agg[iv]["old_dets"] += len(ro.boxes)
            agg[iv]["new_dets"] += len(rn.boxes)
            for b in ro.boxes:
                if float(b.xyxy[0][3]) < far_y:
                    agg[iv]["old_far"] += 1
            for b in rn.boxes:
                if float(b.xyxy[0][3]) < far_y:
                    agg[iv]["new_far"] += 1
                c = int(b.cls[0])
                if c == 1:
                    agg[iv]["new_articulated"] += 1
                elif c == 2:
                    agg[iv]["new_long"] += 1
        print(f"[{wname}] sampled through {he}", flush=True)
    cap.release()

    mio = _mio_intervals()
    rows = []
    print(f"\n{'interval':17} {'frames':>6} {'old/f':>7} {'new/f':>7} "
          f"{'oldFar/f':>8} {'newFar/f':>8} {'newArt':>6} {'newLong':>7} {'mio15':>6}")
    for iv in sorted(agg):
        n = n_frames[iv]
        a = agg[iv]
        mio_v = mio.get(datetime.fromisoformat(iv), "")
        row = {"interval": iv, "frames": n,
               "old_per_frame": round(a["old_dets"] / n, 2),
               "new_per_frame": round(a["new_dets"] / n, 2),
               "old_far_pf": round(a["old_far"] / n, 3),
               "new_far_pf": round(a["new_far"] / n, 3),
               "new_articulated": int(a["new_articulated"]),
               "new_long": int(a["new_long"]), "mio": mio_v}
        rows.append(row)
        print(f"{iv[5:16]:17} {n:>6} {row['old_per_frame']:>7} "
              f"{row['new_per_frame']:>7} {row['old_far_pf']:>8} "
              f"{row['new_far_pf']:>8} {row['new_articulated']:>6} "
              f"{row['new_long']:>7} {str(mio_v):>6}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"new_weights": args.new_weights, "old_weights": args.old_weights,
         "stride": args.stride, "conf": args.conf, "rows": rows}, indent=1))
    print(f"\nwrote {args.out}\nFM51 AB DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
