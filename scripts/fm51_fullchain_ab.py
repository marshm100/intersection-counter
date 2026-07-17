"""FM51 held-out FULL-CHAIN gate (§3-D gate part 3 —
plan_detector_finetune_2026-07-16).

Runs the fine-tuned detector over the audited FM51 study windows (AM 07-09,
PM 16-18), writes the detections as a cache VARIANT, tracks them with the
production pass-1 machinery, replays through the rehearsal project's applied
bank (the production counting chain, flags at production defaults), and
scores per-15-min interval counts against (a) the OLD chain's shipped events
already in the project DB and (b) Miovision. Class mapping for the chain:
vehicle->car(2), articulated/long->truck(7) so downstream classification
behaves identically for both sides; the model's native articulated class is
a post-gate integration.

Usage:
  py scripts/fm51_fullchain_ab.py            # all stages, resumable
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT = "0acb12c0"
CAMERA = 2
WEIGHTS = "runs/detect/runs/finetune_v1/chunk6/weights/last_openvino_model"
CONF = 0.10                        # the balanced profile's production floor
CLASS_MAP = {0: 2, 1: 7, 2: 7}     # vehicle->car, articulated/long->truck
WINDOWS = [("ftv1_am", "07:00", "09:00"), ("ftv1_pm", "16:00", "18:00")]
SCRATCH = Path(r"C:\Users\onkar\AppData\Local\Temp\ic_scratch_fm51")


def _video():
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    conn.row_factory = sqlite3.Row
    v = dict(conn.execute(
        "SELECT * FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (CAMERA,)).fetchone())
    conn.close()
    return v


def stage_a_detect(v, chash):
    """Write the fine-tuned model's detections as a cache variant per window."""
    import cv2
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq_mod
    from backend.services.detection_cache import parquet_path, cache_exists
    from ultralytics import YOLO

    model = None
    fps = float(v["fps"])
    t0 = datetime.fromisoformat(v["recording_start_datetime"])
    for variant, hs, he in WINDOWS:
        pq = Path(parquet_path(PROJECT, CAMERA, chash, variant))
        if cache_exists(pq):
            print(f"[A] {variant}: cache exists, skip", flush=True)
            continue
        if model is None:
            model = YOLO(WEIGHTS, task="detect")
        f_lo = int((datetime.fromisoformat(f"{t0.date()}T{hs}:00") - t0)
                   .total_seconds() * fps)
        f_hi = int((datetime.fromisoformat(f"{t0.date()}T{he}:00") - t0)
                   .total_seconds() * fps)
        cap = cv2.VideoCapture(v["path"])
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        cols = {k: [] for k in ("frame_idx", "bbox_x1", "bbox_y1", "bbox_x2",
                                "bbox_y2", "confidence", "class_id")}
        n = 0
        for f in range(f_lo, f_hi):
            ok, img = cap.read()
            if not ok:
                break
            r = model(img, conf=CONF, imgsz=640, verbose=False,
                      device="intel:gpu")[0]
            for b in r.boxes:
                x1, y1, x2, y2 = (float(x) for x in b.xyxy[0])
                cols["frame_idx"].append(f)
                cols["bbox_x1"].append(x1); cols["bbox_y1"].append(y1)
                cols["bbox_x2"].append(x2); cols["bbox_y2"].append(y2)
                cols["confidence"].append(float(b.conf[0]))
                cols["class_id"].append(CLASS_MAP.get(int(b.cls[0]), 2))
                n += 1
            if (f - f_lo) % 9000 == 0:
                print(f"[A] {variant}: frame {f - f_lo}/{f_hi - f_lo} "
                      f"({n} dets)", flush=True)
        cap.release()
        schema = pa.schema([("frame_idx", pa.uint32()), ("bbox_x1", pa.float32()),
                            ("bbox_y1", pa.float32()), ("bbox_x2", pa.float32()),
                            ("bbox_y2", pa.float32()), ("confidence", pa.float32()),
                            ("class_id", pa.uint8())])
        pq.parent.mkdir(parents=True, exist_ok=True)
        pq_mod.write_table(pa.table(cols, schema=schema), str(pq))
        pq.with_suffix(".meta.json").write_text(json.dumps(
            {"method": "finetune_ab", "total_detections": n,
             "model": WEIGHTS, "imgsz": 640, "conf": CONF,
             "frames": [f_lo, f_hi], "class_map": {str(k): vv for k, vv in
                                                   CLASS_MAP.items()}}, indent=2))
        print(f"[A] {variant}: wrote {n} detections", flush=True)


def stage_b_track(v, chash):
    from backend.services.two_pass import run_pass1
    fps = float(v["fps"])
    t0 = datetime.fromisoformat(v["recording_start_datetime"])
    for variant, hs, he in WINDOWS:
        f_lo = int((datetime.fromisoformat(f"{t0.date()}T{hs}:00") - t0)
                   .total_seconds() * fps)
        f_hi = int((datetime.fromisoformat(f"{t0.date()}T{he}:00") - t0)
                   .total_seconds() * fps)
        res = run_pass1(PROJECT, CAMERA, variant=variant,
                        start_frame=f_lo, end_frame=f_hi, resume=True)
        print(f"[B] {variant}: pass-1 {res.get('status', res)}", flush=True)


def stage_c_replay():
    from backend.services.pass2_replay import replay_camera
    SCRATCH.mkdir(parents=True, exist_ok=True)
    outs = {}
    for variant, _hs, _he in WINDOWS:
        out = SCRATCH / f"fullchain_{variant}.db"
        stats = replay_camera(PROJECT, CAMERA, variant=variant, out_db=out)
        print(f"[C] {variant}: events {stats['events']}", flush=True)
        outs[variant] = out
    return outs


def _events_per_interval(db, t0):
    conn = sqlite3.connect(db)
    per = defaultdict(int)
    for (ts,) in conn.execute(
            "SELECT timestamp_video FROM vehicle_events WHERE camera_id=? "
            "AND COALESCE(rejected,0)=0", (CAMERA,)):
        wc = t0 + timedelta(seconds=float(ts))
        per[wc.replace(minute=(wc.minute // 15) * 15, second=0,
                       microsecond=0)] += 1
    conn.close()
    return per


def stage_d_score(outs, v):
    from audit_fm51 import load_miovision
    mio, _a, _c, _d, _e = load_miovision()
    t0 = datetime.fromisoformat(v["recording_start_datetime"])
    old = _events_per_interval(f"data/projects/{PROJECT}/project.db", t0)
    new = defaultdict(int)
    for out in outs.values():
        for k, n in _events_per_interval(out, t0).items():
            new[k] += n
    print(f"\n{'interval':17} {'mio':>5} {'old':>5} {'new':>5} "
          f"{'oldErr%':>8} {'newErr%':>8}")
    so = sn = sm = 0
    rows = []
    for iv in sorted(mio):
        m, o, nn = mio[iv], old.get(iv, 0), new.get(iv, 0)
        sm += m; so += o; sn += nn
        eo = 100.0 * (o - m) / m if m else 0.0
        en = 100.0 * (nn - m) / m if m else 0.0
        rows.append({"interval": iv.isoformat(), "mio": m, "old": o,
                     "new": nn, "old_err_pct": round(eo, 1),
                     "new_err_pct": round(en, 1)})
        print(f"{iv.isoformat()[5:16]:17} {m:>5} {o:>5} {nn:>5} "
              f"{eo:>7.1f}% {en:>7.1f}%")
    print(f"{'TOTAL':17} {sm:>5} {so:>5} {sn:>5} "
          f"{100.0 * (so - sm) / sm:>7.1f}% {100.0 * (sn - sm) / sm:>7.1f}%")
    outp = Path("runs/finetune_v1/fm51_fullchain.json")
    outp.write_text(json.dumps({"rows": rows, "totals": {
        "mio": sm, "old": so, "new": sn}}, indent=1))
    print(f"wrote {outp}\nFULLCHAIN DONE", flush=True)


def main() -> int:
    from backend.services.detection_cache import compute_video_content_hash
    v = _video()
    chash, _ = compute_video_content_hash(
        v["path"], file_size_bytes=v["file_size_bytes"],
        total_frames=v["total_frames"])
    stage_a_detect(v, chash)
    stage_b_track(v, chash)
    outs = stage_c_replay()
    stage_d_score(outs, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
