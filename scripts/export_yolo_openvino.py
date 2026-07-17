"""Pre-export a YOLO .pt -> OpenVINO IR for the Intel iGPU, OUT of the pipeline
hot path.

The detector (backend/services/detector.py) deliberately does NOT export inside
a processing run anymore: a heavy in-pipeline export at low free-RAM once stalled
a build and was misread as a 'GPU stall'. Export is an explicit, one-time step
you run here; the detector then only *loads* the result on the Intel GPU.

The export dir keeps ultralytics' '<stem>_openvino_model' suffix (that's how the
detector auto-detects the OpenVINO format), and a '.imgsz' sidecar records the
imgsz baked in at export so the detector can verify a load matches the mode.

Usage:
  py scripts/export_yolo_openvino.py                                  # both modes' models
  py scripts/export_yolo_openvino.py --model yolo26s.pt --imgsz 960   # one model
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def export_one(model_path: str, imgsz: int, force: bool = False) -> Path:
    """Export model_path -> OpenVINO IR (FP16) at imgsz; write the .imgsz marker.
    Skips if an export at the same imgsz already exists (unless force)."""
    from ultralytics import YOLO

    ov_dir = Path(model_path).with_suffix("").as_posix() + "_openvino_model"
    marker = Path(ov_dir) / ".imgsz"
    cur = marker.read_text().strip() if marker.exists() else None
    if not force and Path(ov_dir).exists() and cur == str(imgsz):
        print(f"[skip] {ov_dir} already at imgsz={imgsz}")
        return Path(ov_dir)

    print(f"[export] {model_path} -> {ov_dir} (imgsz={imgsz}, FP16) ...", flush=True)
    YOLO(model_path).export(format="openvino", imgsz=imgsz, half=True)
    marker.write_text(str(imgsz))
    print(f"[done] {ov_dir}  (.imgsz={imgsz})")
    return Path(ov_dir)


def main() -> int:
    from backend.config import get_processing_mode_config

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="YOLO .pt (default: both balanced+accurate models)")
    ap.add_argument("--imgsz", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="re-export even if present")
    args = ap.parse_args()

    if args.model:
        imgsz = args.imgsz or get_processing_mode_config("accurate")["yolo_imgsz"]
        export_one(args.model, imgsz, force=args.force)
        return 0

    # Default: export both modes' (model, imgsz) pairs so any build is ready.
    seen: set[tuple[str, int]] = set()
    for mode in ("balanced", "accurate"):
        cfg = get_processing_mode_config(mode)
        key = (cfg["yolo_model"], int(cfg["yolo_imgsz"]))
        if key in seen:
            continue
        seen.add(key)
        export_one(cfg["yolo_model"], int(cfg["yolo_imgsz"]), force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
