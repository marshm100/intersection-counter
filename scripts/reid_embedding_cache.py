"""Read-side provider for the ReID embedding sidecar (Stage 1,
docs/reid_project_plan_2026-06-01.md). Loads the npz written by build_reid_cache.py
and serves per-frame embeddings aligned to the tracker's detection order, keyed by
(frame, rounded bbox) — the bbox values come from the SAME detection cache the
embeddings were built from, so the rounded key matches exactly.

Passed to BotSortBackend as reid_embeddings; its update() calls embs_for(...)."""
from __future__ import annotations

from pathlib import Path

import numpy as np


class ReidEmbeddingCache:
    def __init__(self, npz_path: str | Path):
        d = np.load(npz_path)
        frames = d["frames"]
        bboxes = d["bboxes"]
        embs = d["embs"].astype(np.float32)
        self._dim = int(embs.shape[1]) if embs.size else 512
        self._map: dict = {}
        for f, bb, e in zip(frames, bboxes, embs):
            self._map[(int(f), self._key(bb))] = e

    @staticmethod
    def _key(bb) -> tuple:
        return (round(float(bb[0]), 1), round(float(bb[1]), 1),
                round(float(bb[2]), 1), round(float(bb[3]), 1))

    def embs_for(self, frame_number: int, detections: list) -> np.ndarray:
        out = np.zeros((len(detections), self._dim), dtype=np.float32)
        for i, det in enumerate(detections):
            e = self._map.get((int(frame_number), self._key(det["bbox"])))
            if e is not None:
                out[i] = e
        return out
