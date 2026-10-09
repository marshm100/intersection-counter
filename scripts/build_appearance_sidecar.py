"""Appearance sidecar for the track QC loop (plan ok-plan-it-out-wobbly-rose, Phase 0a, 2026-10-09).

Every row of a detection-cache parquet gets what the car LOOKS like, once, so that the
QC check (and later the loop) runs from cache with no video decode:
  emb  [N, 512] float16  osnet_x0_25 (boxmot ReID.get_features, the probe's call), L2-normalised
  col  [N, 27]  float16  colour_desc of probe_theft_appearance.py: Lab mean + 3 x 8-bin
                         histograms over the central 60% of the box (NaN when too small)
Row i of each array = parquet row i (the cache is written in frame order, detector order
within a frame), so the parquet row number is the detection's id. Memmapped into
<parquet stem>.app/, resumable (progress.txt = frames finished, in order).

Usage: .venv/Scripts/python.exe -X utf8 scripts/build_appearance_sidecar.py PROJ CAM VARIANT [--resume]
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq
from numpy.lib.format import open_memmap

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import parquet_path  # noqa: E402

EMB_DIM = 512
CENTRE = 0.6
BINS = 8


def sidecar_dir(pqp: Path) -> Path:
    return pqp.with_name(pqp.stem + ".app")


def load_rows(pqp: Path) -> tuple[np.ndarray, np.ndarray]:
    t = pq.read_table(pqp, columns=["frame_idx", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2"])
    fr = t.column("frame_idx").to_numpy().astype(np.int64)
    bb = np.stack([t.column(c).to_numpy() for c in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2")],
                  axis=1).astype(np.float32)
    if len(fr) and (np.diff(fr) < 0).any():
        raise SystemExit("parquet not in frame order: row number is not a stable detection id")
    return fr, bb


def colour_rows(lab: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """colour_desc for every box of one frame; lab = whole frame in Lab (float32)."""
    H, W = lab.shape[:2]
    out = np.full((len(boxes), 3 + 3 * BINS), np.nan, dtype=np.float32)
    lo = np.array([0.0, -128.0, -128.0]); span = np.array([100.0, 256.0, 256.0])
    for k, (x1, y1, x2, y2) in enumerate(boxes):
        mx, my = (x2 - x1) * (1 - CENTRE) / 2, (y2 - y1) * (1 - CENTRE) / 2
        xa, ya = int(max(0, np.floor(x1 + mx))), int(max(0, np.floor(y1 + my)))
        xb, yb = int(min(W, np.ceil(x2 - mx))), int(min(H, np.ceil(y2 - my)))
        if xb - xa < 2 or yb - ya < 2:
            continue
        px = lab[ya:yb, xa:xb].reshape(-1, 3)
        out[k, :3] = px.mean(axis=0)
        q = np.clip(((px - lo) / span * BINS).astype(np.int64), 0, BINS - 1)
        for c in range(3):
            out[k, 3 + c * BINS:3 + (c + 1) * BINS] = np.bincount(q[:, c], minlength=BINS) / len(px)
    return out


def main() -> int:
    proj, cam, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    resume = "--resume" in sys.argv
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, chash = con.execute("SELECT path, content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
    con.close()
    pqp = parquet_path(proj, cam, chash, variant)
    out = sidecar_dir(pqp)
    fr, bb = load_rows(pqp)
    N = len(fr)
    frames, starts = np.unique(fr, return_index=True)
    ends = np.append(starts[1:], N)
    print(f"{pqp.name}: {N} rows, {len(frames)} frames {frames[0]}-{frames[-1]} -> {out}", flush=True)

    out.mkdir(parents=True, exist_ok=True)
    done = 0
    if resume and (out / "progress.txt").exists():
        done = int((out / "progress.txt").read_text())
        em = open_memmap(out / "emb.npy", mode="r+")
        co = open_memmap(out / "col.npy", mode="r+")
        if em.shape != (N, EMB_DIM):
            raise SystemExit("--resume: sidecar shape does not match the parquet; rebuild fresh")
        print(f"resuming after {done} frames", flush=True)
    else:
        em = open_memmap(out / "emb.npy", mode="w+", dtype=np.float16, shape=(N, EMB_DIM))
        co = open_memmap(out / "col.npy", mode="w+", dtype=np.float16, shape=(N, 3 + 3 * BINS))
        co[:] = np.nan

    from boxmot.reid.core.reid import ReID
    model = ReID(weights="osnet_x0_25_msmt17.pt", device="cuda:0").model

    cap = cv2.VideoCapture(vpath)
    k = done
    f = int(frames[k]) if k < len(frames) else None
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    cur = f
    t0 = time.time()
    while k < len(frames):
        target = int(frames[k])
        while cur < target:
            if not cap.grab():
                raise SystemExit(f"decode ended at frame {cur}")
            cur += 1
        ok, img = cap.read()
        if not ok:
            raise SystemExit(f"decode failed at frame {cur}")
        cur += 1
        a, b = int(starts[k]), int(ends[k])
        h, w = img.shape[:2]
        boxes = np.clip(bb[a:b], 0, [w - 1, h - 1, w - 1, h - 1]).astype(np.float32)
        okb = (boxes[:, 2] - boxes[:, 0] >= 4) & (boxes[:, 3] - boxes[:, 1] >= 4)
        if okb.any():
            ft = np.asarray(model.get_features(boxes[okb], img), dtype=np.float32)
            ft /= np.maximum(np.linalg.norm(ft, axis=1, keepdims=True), 1e-9)
            blk = np.zeros((b - a, EMB_DIM), dtype=np.float16)
            blk[okb] = ft
            em[a:b] = blk
        lab = cv2.cvtColor(img.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
        co[a:b] = colour_rows(lab, boxes)
        k += 1
        if k % 2000 == 0 or k == len(frames):
            em.flush(); co.flush()
            (out / "progress.txt").write_text(str(k))
            el = time.time() - t0
            rate = (k - done) / max(el, 1e-9)
            print(f"  {k}/{len(frames)} frames, {rate:.0f} f/s, eta {(len(frames) - k) / max(rate, 1e-9) / 60:.0f} min",
                  flush=True)
    cap.release()
    (out / "count.txt").write_text(str(N))
    print(f"wrote {out} ({N} rows)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
