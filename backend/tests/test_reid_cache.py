"""Round-trip tests for the low-RAM ReID embedding sidecar (memmap directory format).

The big embeddings array must stay memmapped and only a (frame,key)->row index lives
in RAM — a 30-min window's f32 vectors would otherwise OOM an 8 GB box just to read.
These build a tiny sidecar by hand (no video/model) and check the reader.
"""
import sys
from pathlib import Path

import numpy as np
from numpy.lib.format import open_memmap

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from reid_embedding_cache import ReidEmbeddingCache


def _write(d: Path, frames, bboxes, embs, count=None):
    d.mkdir(parents=True, exist_ok=True)
    n = len(frames)
    fr = open_memmap(d / "frames.npy", mode="w+", dtype=np.int32, shape=(n,))
    bb = open_memmap(d / "bboxes.npy", mode="w+", dtype=np.float32, shape=(n, 4))
    em = open_memmap(d / "embs.npy", mode="w+", dtype=np.float16, shape=(n, embs.shape[1]))
    fr[:] = frames; bb[:] = bboxes; em[:] = embs
    fr.flush(); bb.flush(); em.flush()
    (d / "count.txt").write_text(str(n if count is None else count))


def test_roundtrip_matches_and_misses(tmp_path):
    frames = np.array([10, 10, 11], dtype=np.int32)
    bboxes = np.array([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]], dtype=np.float32)
    embs = np.random.RandomState(0).rand(3, 512).astype(np.float16)
    _write(tmp_path / "x.reid", frames, bboxes, embs)

    c = ReidEmbeddingCache(tmp_path / "x.reid")
    out = c.embs_for(10, [{"bbox": [1.0, 2.0, 3.0, 4.0]}, {"bbox": [5.0, 6.0, 7.0, 8.0]}])
    assert out.shape == (2, 512) and out.dtype == np.float32
    assert np.allclose(out[0], embs[0].astype(np.float32), atol=1e-3)
    assert np.allclose(out[1], embs[1].astype(np.float32), atol=1e-3)

    # non-matching bbox -> zeros; wrong frame -> zeros
    assert np.count_nonzero(c.embs_for(10, [{"bbox": [99, 99, 99, 99]}])) == 0
    assert np.count_nonzero(c.embs_for(999, [{"bbox": [1, 2, 3, 4]}])) == 0


def test_count_truncates_trailing_zeros(tmp_path):
    # array sized 5 but only 2 valid rows (count=2) — the zero rows must not be indexed
    d = tmp_path / "y.reid"; d.mkdir()
    fr = open_memmap(d / "frames.npy", mode="w+", dtype=np.int32, shape=(5,))
    bb = open_memmap(d / "bboxes.npy", mode="w+", dtype=np.float32, shape=(5, 4))
    em = open_memmap(d / "embs.npy", mode="w+", dtype=np.float16, shape=(5, 512))
    fr[0], fr[1] = 7, 7
    bb[0], bb[1] = [1, 1, 1, 1], [2, 2, 2, 2]
    em[0], em[1] = 0.5, 0.25
    for m in (fr, bb, em):
        m.flush()
    (d / "count.txt").write_text("2")

    c = ReidEmbeddingCache(d)
    assert len(c._idx) == 2
    assert np.allclose(c.embs_for(7, [{"bbox": [1, 1, 1, 1]}])[0], 0.5, atol=1e-3)
