"""Phase D spike: export YOLO->OpenVINO and benchmark CPU (PyTorch) vs Iris-Xe GPU.

Gets a REAL speedup number before wiring an OpenVINO detector backend. Times
single-image inference (batch=1, the pipeline's regime) at the balanced imgsz.

Usage:  py scripts/bench_openvino.py --model yolo26s.pt --imgsz 960 --n 80
"""
from __future__ import annotations
import argparse, time
from pathlib import Path
import numpy as np


def _fps(model, img, imgsz, device, n, warmup=5):
    for _ in range(warmup):
        model.predict(img, imgsz=imgsz, device=device, verbose=False)
    t = time.perf_counter()
    for _ in range(n):
        model.predict(img, imgsz=imgsz, device=device, verbose=False)
    dt = time.perf_counter() - t
    return n / dt, dt / n * 1000  # fps, ms/frame


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo26s.pt")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--n", type=int, default=80)
    args = ap.parse_args()
    from ultralytics import YOLO
    img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

    print(f"[CPU / PyTorch] {args.model} @ {args.imgsz}")
    m = YOLO(args.model)
    cpu_fps, cpu_ms = _fps(m, img, args.imgsz, "cpu", args.n)
    print(f"  CPU: {cpu_fps:.2f} fps  ({cpu_ms:.0f} ms/frame)")

    # export to OpenVINO (FP16) once
    ov_dir = Path(args.model).with_suffix("").as_posix() + "_openvino_model"
    if not Path(ov_dir).exists():
        print(f"[export] {args.model} -> {ov_dir} (FP16)...")
        YOLO(args.model).export(format="openvino", imgsz=args.imgsz, half=True)
    ov = YOLO(ov_dir, task="detect")

    for dev in ("intel:gpu", "intel:cpu"):
        try:
            fps, ms = _fps(ov, img, args.imgsz, dev, args.n)
            label = "Iris-Xe GPU" if "gpu" in dev else "OpenVINO CPU"
            speedup = fps / cpu_fps
            print(f"  [{label}] device={dev}: {fps:.2f} fps  ({ms:.0f} ms/frame)  speedup vs PyTorch-CPU = {speedup:.2f}x")
        except Exception as e:
            print(f"  [{dev}] FAILED: {type(e).__name__}: {str(e)[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
