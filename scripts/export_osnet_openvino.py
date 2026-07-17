"""Export osnet_x0_25 ReID to OpenVINO IR so embeddings can run on the Iris-Xe
iGPU (Phase B, docs/reid_project_plan_2026-06-01.md). boxmot's OpenVINO ReID
backend compiles for CPU only; we export the IR here and run it on 'GPU' ourselves
in build_reid_cache.py. Embedding parity vs the pytorch model is checked separately.

Converts the torch nn.Module DIRECTLY via openvino.convert_model (no onnx dep, no
uv-based boxmot exporter). Dynamic batch so the IR accepts any per-frame det count.

Usage:  py scripts/export_osnet_openvino.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import torch
import openvino as ov

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from boxmot.reid.core.reid import ReID, WEIGHTS


def main() -> int:
    weights = Path(WEIGHTS) / "osnet_x0_25_msmt17.pt"
    net = ReID(weights=str(weights), device="cpu").model.model  # torch nn.Module
    net.eval().float()
    im = torch.zeros(1, 3, 256, 128)   # osnet input HxW = 256x128

    out_dir = weights.parent / f"{weights.stem}_openvino_model"
    out_dir.mkdir(parents=True, exist_ok=True)
    xml_path = out_dir / f"{weights.stem}.xml"

    ov_model = ov.convert_model(net, example_input=im, input=[[-1, 3, 256, 128]])
    ov.save_model(ov_model, str(xml_path), compress_to_fp16=False)
    print("OpenVINO IR:", xml_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
