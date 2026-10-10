"""Training crops for the car verifier (plan_basis STAGE 1, 2026-10-10). Label-free.

One fleet window per call. 1-s blocks every BLOCK_EVERY_S seconds, skipping every journey-label clip (dev and
held-out) +- EXCLUDE_MARGIN_S. Inside a block, each production-dump track gives at most one TRACKLET: its
longest stretch whose detector boxes (dump rows joined to the parquet) follow each other at IoU >= STEP_IOU,
frame gaps <= 2, and never overlap or abut another detector box in that frame (a truck's cab and trailer boxes
touch; two cars that touch could swap). Up to N_CROPS crops per tracklet, evenly spaced. Two tracklets of one
block are two different vehicles (they are separate boxes in the same frames).
Writes data/verifier/v1/<cam>_<variant>.crops.npy (N, SIZE, SIZE, 3) uint8 BGR and .meta.npz
(tracklet, block, frame, width). Usage:
  .venv/Scripts/python.exe -X utf8 scripts/build_verifier_pairs.py PROJ CAM VARIANT
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.vehicle_verifier import SIZE, square_crop  # noqa: E402
from research_thefts import iou_mat  # noqa: E402
from research_track_qc import join_rows  # noqa: E402

BLOCK_EVERY_S = 5.0
EXCLUDE_MARGIN_S = 30.0
STEP_IOU = 0.3
ABUT = 0.05           # boxes closer than this x the smaller width (or overlapping) are ambiguous
MIN_LEN = 5
N_CROPS = 4
MIN_W = 10.0
OUT = Path("data/verifier/v1")


def ambiguous(B: np.ndarray) -> np.ndarray:
    """Per box: does it overlap or nearly touch another box of the frame?"""
    n = len(B)
    if n < 2:
        return np.zeros(n, dtype=bool)
    w = (B[:, 2] - B[:, 0])
    g = ABUT * np.minimum(w[:, None], w[None, :])
    gx = np.maximum(B[:, None, 0], B[None, :, 0]) - np.minimum(B[:, None, 2], B[None, :, 2])
    gy = np.maximum(B[:, None, 1], B[None, :, 1]) - np.minimum(B[:, None, 3], B[None, :, 3])
    near = (gx < g) & (gy < g)
    np.fill_diagonal(near, False)
    return near.any(axis=1)


def main() -> int:
    proj, cam, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    excl = [(s - EXCLUDE_MARGIN_S * f_, e + EXCLUDE_MARGIN_S * f_) for s, e, f_ in
            con.execute("SELECT start_frame, end_frame, fps FROM journey_clips WHERE camera_id=?", (cam,))]
    pqp = parquet_path(proj, cam, chash, variant)
    rows = np.array(load_dump(tracks_dir(pqp)), dtype=np.float64, copy=True)
    join, bb = join_rows(rows, pqp)
    import pyarrow.parquet as pq
    pfr = pq.read_table(pqp, columns=["frame_idx"]).column("frame_idx").to_numpy().astype(np.int64)
    pf, ps = np.unique(pfr, return_index=True)
    pe = np.append(ps[1:], len(pfr))
    p_of = {int(f): (int(a), int(b)) for f, a, b in zip(pf, ps, pe)}
    f0, f1 = int(rows[:, 1].min()), int(rows[:, 1].max())
    blen, bstep = int(round(fps)), int(round(BLOCK_EVERY_S * fps))
    keep = join >= 0
    rows, join = rows[keep], join[keep]
    order = np.argsort(rows[:, 1], kind="stable")
    rows, join = rows[order], join[order]
    rf = rows[:, 1].astype(np.int64)

    picks = []      # (frame, parquet row, tracklet, block, width)
    n_trk = 0
    amb_cache: dict[int, np.ndarray] = {}
    for bi, s in enumerate(range(f0, f1 - blen, bstep)):
        e = s + blen
        if any(not (e < a or s > b) for a, b in excl):
            continue
        lo, hi = np.searchsorted(rf, s), np.searchsorted(rf, e)
        by_t = defaultdict(list)
        for i in range(lo, hi):
            by_t[int(rows[i, 0])].append((int(rf[i]), int(join[i])))
        for tid, seq in by_t.items():
            best, cur = [], []
            for f, j in seq:
                a, b = p_of[f]
                if f not in amb_cache:
                    amb_cache[f] = ambiguous(bb[a:b])
                ok = (not amb_cache[f][j - a]) and (bb[j, 2] - bb[j, 0]) >= MIN_W
                if ok and cur:
                    pf_, pj = cur[-1]
                    ok_step = f - pf_ <= 2 and iou_mat(bb[pj][None], bb[j][None])[0, 0] >= STEP_IOU
                    if not ok_step:
                        cur = []
                if ok:
                    cur.append((f, j))
                    if len(cur) > len(best):
                        best = list(cur)
                else:
                    cur = []
            if len(best) >= MIN_LEN:
                for k in np.unique(np.linspace(0, len(best) - 1, N_CROPS).round().astype(int)):
                    f, j = best[k]
                    picks.append((f, j, n_trk, bi, float(bb[j, 2] - bb[j, 0])))
                n_trk += 1
        amb_cache = {f: v for f, v in amb_cache.items() if f >= s}
    print(f"cam{cam} {variant}: {n_trk} tracklets, {len(picks)} crops", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    stem = OUT / f"cam{cam}_{variant}"
    picks.sort()
    from numpy.lib.format import open_memmap
    crops = open_memmap(str(stem) + ".crops.npy", mode="w+", dtype=np.uint8, shape=(len(picks), SIZE, SIZE, 3))
    need = defaultdict(list)
    for k, (f, j, *_rest) in enumerate(picks):
        need[f].append((k, j))
    cap = cv2.VideoCapture(vpath)
    lo, hi = min(need), max(need)
    cap.set(cv2.CAP_PROP_POS_FRAMES, lo)
    t0 = time.time()
    for f in range(lo, hi + 1):
        if f not in need:
            if not cap.grab():
                raise SystemExit(f"decode ended at {f}")
            continue
        ok, img = cap.read()
        if not ok:
            raise SystemExit(f"decode failed at {f}")
        for k, j in need[f]:
            crops[k] = square_crop(img, bb[j])
    cap.release()
    crops.flush()
    p = np.asarray(picks, dtype=np.float64)
    np.savez(str(stem) + ".meta.npz", frame=p[:, 0].astype(np.int64), row=p[:, 1].astype(np.int64),
             tracklet=p[:, 2].astype(np.int64), block=p[:, 3].astype(np.int64), width=p[:, 4],
             cam=np.full(len(p), cam), variant=variant)
    print(f"  wrote {stem}.crops.npy ({len(picks)}) in {time.time() - t0:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
