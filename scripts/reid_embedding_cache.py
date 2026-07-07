"""Read-side provider for the ReID embedding sidecar (Stage 1,
docs/reid_project_plan_2026-06-01.md). Serves per-frame embeddings aligned to the
tracker's detection order, keyed by (frame, rounded bbox) — the bbox values come from
the SAME detection cache the embeddings were built from, so the rounded key matches.

Low-RAM by design: the big embeddings array stays MEMMAPPED on disk and only a
lightweight (frame,key)->row index lives in RAM (a 30-min window's 635 MB of f32
vectors would otherwise OOM an 8 GB box just to READ). Accepts the new memmap
DIRECTORY sidecar (build_reid_cache) and the legacy single .npz (cam1).

Passed to BotSortBackend as reid_embeddings; its update() calls embs_for(...)."""
from __future__ import annotations

from pathlib import Path

import numpy as np


class ReidEmbeddingCache:
    def __init__(self, sidecar: str | Path):
        p = Path(sidecar)
        if p.is_dir():                                   # memmap directory (streamed build)
            n = int((p / "count.txt").read_text())
            frames = np.load(p / "frames.npy")[:n]       # small (int32) — load fully
            bboxes = np.load(p / "bboxes.npy")[:n]       # small (f32 x4) — load fully
            self._embs = np.load(p / "embs.npy", mmap_mode="r")   # BIG (f16) — stays on disk
        else:                                            # legacy single .npz (cam1)
            d = np.load(p)
            frames, bboxes, self._embs = d["frames"], d["bboxes"], d["embs"]
            n = len(frames)
        self._dim = int(self._embs.shape[1]) if self._embs.size else 512
        self._idx: dict = {}                             # (frame, key) -> row, no vectors held
        for i in range(n):
            self._idx[(int(frames[i]), self._key(bboxes[i]))] = i

    @staticmethod
    def _key(bb) -> tuple:
        return (round(float(bb[0]), 1), round(float(bb[1]), 1),
                round(float(bb[2]), 1), round(float(bb[3]), 1))

    def embs_for(self, frame_number: int, detections: list) -> np.ndarray:
        out = np.zeros((len(detections), self._dim), dtype=np.float32)
        for i, det in enumerate(detections):
            r = self._idx.get((int(frame_number), self._key(det["bbox"])))
            if r is not None:
                out[i] = np.asarray(self._embs[r], dtype=np.float32)   # one row off the memmap
        return out
