"""The car verifier: "does this box show the same vehicle?" (plan_basis STAGE 1, 2026-10-10).

osnet_x1_0 (boxmot backbone) fine-tuned on our own footage, label-free (scripts/train_vehicle_verifier.py).
Input: a square crop around the detector box (10% margin, padded black at the frame edge) resized to
SIZE x SIZE. Output: an L2-normalised 512-d embedding; same car = small cosine distance.
Research and offline use only until a tracker arm ships; nothing in production imports it yet.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

SIZE = 128
MARGIN = 1.1
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
OSNET_START = Path(".venv/Lib/site-packages/models/osnet_x1_0_msmt17.pt")


def square_crop(img: np.ndarray, box, size: int = SIZE) -> np.ndarray:
    """uint8 BGR size x size crop centred on the box, side = MARGIN x its longer edge."""
    x1, y1, x2, y2 = (float(v) for v in box)
    H, W = img.shape[:2]
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    s = max(x2 - x1, y2 - y1, 2.0) * MARGIN / 2
    xa, ya, xb, yb = int(np.floor(cx - s)), int(np.floor(cy - s)), int(np.ceil(cx + s)), int(np.ceil(cy + s))
    pad = np.zeros((yb - ya, xb - xa, 3), dtype=np.uint8)
    sx, sy, ex, ey = max(xa, 0), max(ya, 0), min(xb, W), min(yb, H)
    if ex > sx and ey > sy:
        pad[sy - ya:ey - ya, sx - xa:ex - xa] = img[sy:ey, sx:ex]
    return cv2.resize(pad, (size, size), interpolation=cv2.INTER_AREA if pad.shape[0] > size else cv2.INTER_CUBIC)


def build_backbone(start: Path | None = OSNET_START):
    from boxmot.reid.backbones.osnet import osnet_x1_0
    m = osnet_x1_0(num_classes=1, pretrained=False, loss="triplet")
    if start is not None and Path(start).exists():
        import torch
        sd = torch.load(str(start), map_location="cpu", weights_only=False)
        sd = sd.get("state_dict", sd)
        sd = {k.replace("module.", ""): v for k, v in sd.items() if not k.startswith(("classifier", "module.classifier"))}
        m.load_state_dict(sd, strict=False)
    return m


def to_tensor(crops: np.ndarray):
    """(N, S, S, 3) uint8 BGR -> normalised float tensor (N, 3, S, S)."""
    import torch
    x = crops[..., ::-1].astype(np.float32) / 255.0
    x = (x - MEAN) / STD
    return torch.from_numpy(np.ascontiguousarray(x.transpose(0, 3, 1, 2)))


def embed_tensor(model, x):
    """Features (not logits) whatever the train/eval mode: the backbone's pooled 512-d vector."""
    import torch.nn.functional as F
    f = model.featuremaps(x)
    v = model.global_avgpool(f).view(f.size(0), -1)
    if model.fc is not None:
        v = model.fc(v)
    return F.normalize(v, dim=1)


class Verifier:
    def __init__(self, weights: str | Path, device: str = "cuda:0"):
        import torch
        self.device = device
        self.m = build_backbone(None)
        sd = torch.load(str(weights), map_location="cpu", weights_only=False)
        self.m.load_state_dict(sd, strict=False)
        self.m.to(device).eval().half()

    def features(self, boxes: np.ndarray, img: np.ndarray) -> np.ndarray:
        import torch
        if not len(boxes):
            return np.zeros((0, 512), dtype=np.float32)
        crops = np.stack([square_crop(img, b) for b in boxes])
        with torch.no_grad():
            v = embed_tensor(self.m, to_tensor(crops).to(self.device).half())
        return v.float().cpu().numpy()
