"""Pipeline-V2 B1b — endpoint EXTENSION of the production dump
(day-5 verdict: keep BoT-SORT association; add only the low-conf
endpoint recovery it lacks).

For every production track START and END, walk backward/forward through
the RAW cached detection stream (conf >= LOW 0.10) using the same
box-scale+velocity gate, consuming only FREE detections (not within
CLAIM_PX of any dump row on that frame — no stealing from neighbors).
An extension is kept only if it has >= MIN_EXT_HITS real detections and
moves >= one box diagonal (anti-noise-latch). Track ids UNCHANGED —
pure elongation; association quality untouched.

Output: v2c_<variant> dump -> same harness (census, pass-2, score).

Constants ledger (structural): LOW=0.10, MISS_RUN=0.6 s, EXT_CAP=8 s,
MIN_EXT_HITS=4, CLAIM_PX=3, GATE = 0.7*diag + 0.6*|v|*dt (shared).

Usage:
  py -X utf8 scripts/v2_extend_dump.py --camera 2 --variant study_0700 --cache study_0700
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
import pyarrow.parquet as pq                           # noqa: E402
from backend.services import two_pass as TP            # noqa: E402

LOW = 0.10
MISS_RUN_S = 0.6
EXT_CAP_S = 8.0
MIN_EXT_HITS = 4
CLAIM_PX = 3.0
GATE_DIAG = 0.7
GATE_VEL = 0.6
KIN = 8


def read_cache_window(project, camera, cache, f_lo, f_hi):
    cache_pq = Path(str(TP._camera_parquet(project, camera, cache)) + ".parquet")
    if not cache_pq.exists():
        cache_pq = TP._camera_parquet(project, camera, cache).with_suffix(".parquet")
    pf = pq.ParquetFile(str(cache_pq))
    cols = [c.name for c in pf.schema_arrow]
    cls_col = next((c for c in cols if "class" in c), None)
    parts = []
    for b in pf.iter_batches(columns=["frame_idx", "bbox_x1", "bbox_y1",
                                      "bbox_x2", "bbox_y2", "confidence"]
                             + ([cls_col] if cls_col else [])):
        d = b.to_pydict()
        fr = np.asarray(d["frame_idx"], np.int64)
        m = (fr >= f_lo) & (fr < f_hi)
        if not m.any():
            continue
        x1 = np.asarray(d["bbox_x1"], np.float32)[m]
        y1 = np.asarray(d["bbox_y1"], np.float32)[m]
        x2 = np.asarray(d["bbox_x2"], np.float32)[m]
        y2 = np.asarray(d["bbox_y2"], np.float32)[m]
        cf = np.asarray(d["confidence"], np.float32)[m]
        cl = (np.asarray(d[cls_col], np.float32)[m] if cls_col
              else np.full(int(m.sum()), 2, np.float32))
        parts.append(np.stack([fr[m].astype(np.float32),
                               (x1 + x2) / 2, (y1 + y2) / 2,
                               x2 - x1, y2 - y1, cf, cl], 1))
    dets = np.concatenate(parts)
    dets = dets[dets[:, 5] >= LOW]
    dets = dets[np.argsort(dets[:, 0], kind="stable")]
    uf, us = np.unique(dets[:, 0].astype(np.int64), return_index=True)
    ue = np.append(us[1:], len(dets))
    return dets, dict(zip(uf.tolist(), zip(us.tolist(), ue.tolist())))


def endpoint_state(tr, fps, head):
    k = min(KIN, len(tr))
    seg = tr[:k] if head else tr[-k:]
    f, x, y = seg[:, 1], seg[:, 2], seg[:, 3]
    if len(f) < 2 or f[-1] == f[0]:
        v = (0.0, 0.0)
    else:
        tt = (f - f[0])
        den = ((tt - tt.mean()) ** 2).sum() or 1e-9
        v = (float(((tt - tt.mean()) * (x - x.mean())).sum() / den),
             float(((tt - tt.mean()) * (y - y.mean())).sum() / den))
    row = tr[0] if head else tr[-1]
    return row, v


def extend(row0, v, dets, frame_of, claimed, fps, direction):
    """Walk from an endpoint; returns extension rows (list of 8-col)."""
    f = int(row0[1])
    cx, cy, w, h = float(row0[2]), float(row0[3]), float(row0[4]), float(row0[5])
    vx, vy = v[0] * direction, v[1] * direction
    ext, miss, hits = [], 0, 0
    tid = float(row0[0])
    cap = int(EXT_CAP_S * fps)
    miss_cap = int(MISS_RUN_S * fps)
    for step in range(1, cap):
        f2 = f + step * direction
        se = frame_of.get(f2)
        cx, cy = cx + vx, cy + vy
        if se is None:
            miss += 1
            if miss > miss_cap:
                break
            continue
        s, e = se
        cand = dets[s:e]
        free = ~claimed_mask(cand, claimed.get(f2))
        cand = cand[free]
        if not len(cand):
            miss += 1
            if miss > miss_cap:
                break
            continue
        gate = GATE_DIAG * float(np.hypot(w, h)) + GATE_VEL * float(
            np.hypot(vx, vy)) * (miss + 1)
        d = np.hypot(cand[:, 1] - cx, cand[:, 2] - cy)
        j = int(np.argmin(d))
        if d[j] > max(gate, 6.0):
            miss += 1
            if miss > miss_cap:
                break
            continue
        det = cand[j]
        nvx, nvy = (float(det[1]) - (cx - vx)) / (miss + 1), (
            float(det[2]) - (cy - vy)) / (miss + 1)
        vx, vy = 0.5 * nvx + 0.5 * vx, 0.5 * nvy + 0.5 * vy
        cx, cy, w, h = float(det[1]), float(det[2]), float(det[3]), float(det[4])
        ext.append((tid, float(f2), cx, cy, w, h, float(det[5]), float(det[6])))
        hits += 1
        miss = 0
    if hits < MIN_EXT_HITS:
        return []
    disp = np.hypot(ext[-1][2] - float(row0[2]), ext[-1][3] - float(row0[3]))
    if disp < float(np.hypot(row0[4], row0[5])):
        return []
    return ext


def claimed_mask(cand, claimed_xy):
    if claimed_xy is None or not len(claimed_xy):
        return np.zeros(len(cand), bool)
    D = np.hypot(cand[:, 1][:, None] - claimed_xy[None, :, 0],
                 cand[:, 2][:, None] - claimed_xy[None, :, 1])
    return (D.min(axis=1) <= CLAIM_PX)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--directions", default="both",
                    choices=["both", "fwd", "bwd"])
    args = ap.parse_args()
    t0 = time.time()

    tdir = TP.tracks_dir(TP._camera_parquet(args.project, args.camera,
                                            args.variant))
    meta = json.loads((tdir / "meta.json").read_text())
    f_lo, f_hi = meta["frames"]
    fps = {1: 10.0, 2: 25.0, 3: 10.0, 4: 10.0, 5: 10.0}[args.camera]
    n = int((tdir / "count.txt").read_text())
    rows = np.asarray(np.load(tdir / "rows.npy", mmap_mode="r")[:n])
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows = rows[order]
    tids, starts = np.unique(rows[:, 0], return_index=True)
    ends = np.append(starts[1:], len(rows))

    dets, frame_of = read_cache_window(args.project, args.camera, args.cache,
                                       f_lo, f_hi)
    # per-frame claimed positions from the dump
    claimed: dict[int, np.ndarray] = {}
    fr_i = rows[:, 1].astype(np.int64)
    ord_f = np.argsort(fr_i, kind="stable")
    fr_s = fr_i[ord_f]
    uf, us = np.unique(fr_s, return_index=True)
    ue = np.append(us[1:], len(fr_s))
    for fval, s, e in zip(uf.tolist(), us.tolist(), ue.tolist()):
        idx = ord_f[s:e]
        claimed[fval] = rows[idx][:, 2:4].astype(np.float32)

    ext_rows = []
    n_ext = 0
    for s, e in zip(starts, ends):
        tr = rows[s:e]
        eh, et = [], []
        if args.directions in ("both", "bwd"):
            row_h, v_h = endpoint_state(tr, fps, head=True)
            eh = extend(row_h, v_h, dets, frame_of, claimed, fps, -1)
        if args.directions in ("both", "fwd"):
            row_t, v_t = endpoint_state(tr, fps, head=False)
            et = extend(row_t, v_t, dets, frame_of, claimed, fps, +1)
        if eh:
            ext_rows.extend(eh)
            n_ext += 1
        if et:
            ext_rows.extend(et)
            n_ext += 1

    out = np.concatenate([rows, np.array(ext_rows, dtype=np.float32)]) \
        if ext_rows else rows
    out = out[np.lexsort((out[:, 0], out[:, 1]))].astype(np.float32)
    new_variant = f"v2c_{args.variant}"
    dst = TP.tracks_dir(TP._camera_parquet(args.project, args.camera,
                                           new_variant))
    dst.mkdir(parents=True, exist_ok=True)
    meta2 = dict(meta)
    meta2["variant"] = new_variant
    meta2["complete"] = True
    meta2["v2c_extension"] = {
        "cache": args.cache, "low": LOW, "ext_cap_s": EXT_CAP_S,
        "min_ext_hits": MIN_EXT_HITS, "extended_endpoints": n_ext,
        "ext_rows": len(ext_rows)}
    np.save(dst / "rows.npy", out)
    (dst / "count.txt").write_text(str(len(out)))
    (dst / "meta.json").write_text(json.dumps(meta2))
    print(f"[extend] cam{args.camera} {args.variant} -> {new_variant}: "
          f"{len(tids)} tracks, {n_ext} endpoints extended "
          f"(+{len(ext_rows)} rows) -> {dst} ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
