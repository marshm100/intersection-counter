"""Pipeline-V2 B1 — tubelet-stabilized track source (alternative pass-1).

Reads RAW cached detections for a window (DetectionCache parquet, conf
floor ~0.08 already cached) and builds tracks with an offline-friendly
recipe aimed at FAR-BAND TEMPORAL STABILITY (the week-1 verdict's binding
constraint):

  1. High-conf backbone association (activation 0.25 = the production
     birth gate, unchanged) by predicted-center distance with a
     box-scale + velocity-scaled gate; greedy mutual-nearest per frame.
  2. BYTE-style low-conf CONTINUATION (0.10-0.25): may extend existing
     tracks, never births — the far-band flicker fix.
  3. Miss-coasting up to T_MISS seconds (linear prediction).
  4. Offline post-pass per tubelet: N-of-M confirmation (>=4 real hits,
     >=0.8 s span), gap interpolation (conf 0), tubelet mean-top-half
     rescore floor (0.25), coordinate smoothing (window 3).

Output: a v2b_<variant> pass-1 dump (format 2) measured through the
same harness (production pass-2 in scratch; dev score; blind held-outs).

Constants ledger (structural, production-anchored, NOT per-camera):
ACT=0.25 (production activation), LOW=0.10, T_MISS=1.0 s, MIN_HITS=8,
MIN_SPAN=1.5 s, RESCORE_FLOOR=0.30 (day-5 debris tightening), GATE = 0.7*box_diag + 0.6*|v|*dt.

Usage:
  py -X utf8 scripts/v2_tubelet.py --camera 2 --variant study_0700 \
      --cache balanced_960_skip1
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

ACT = 0.25
LOW = 0.10
T_MISS_S = 1.0
MIN_HITS = 8
MIN_SPAN_S = 1.5
RESCORE_FLOOR = 0.30
GATE_DIAG = 0.7
GATE_VEL = 0.6
V_EMA = 0.5

WINDOW_FRAMES = {"study_0700": None, "study_1100": None, "study_1600": None}


def window_frames(project: str, camera: int, variant: str):
    """Frame range from the EXISTING production dump's meta (bit-identical
    windows to the control — no new window math)."""
    tdir = TP.tracks_dir(TP._camera_parquet(project, camera, variant))
    meta = json.loads((tdir / "meta.json").read_text())
    return meta["frames"], meta


class Track:
    __slots__ = ("tid", "rows", "last_f", "cx", "cy", "w", "h",
                 "vx", "vy", "hits", "cls")

    def __init__(self, tid, f, cx, cy, w, h, conf, cls):
        self.tid = tid
        self.rows = [(f, cx, cy, w, h, conf, cls)]
        self.last_f = f
        self.cx, self.cy, self.w, self.h = cx, cy, w, h
        self.vx = self.vy = 0.0
        self.hits = 1
        self.cls = cls

    def predict(self, f):
        dt = f - self.last_f
        return self.cx + self.vx * dt, self.cy + self.vy * dt

    def update(self, f, cx, cy, w, h, conf, cls):
        dt = max(1.0, f - self.last_f)
        nvx, nvy = (cx - self.cx) / dt, (cy - self.cy) / dt
        self.vx = V_EMA * nvx + (1 - V_EMA) * self.vx
        self.vy = V_EMA * nvy + (1 - V_EMA) * self.vy
        self.cx, self.cy, self.w, self.h = cx, cy, w, h
        self.last_f = f
        self.hits += 1
        self.rows.append((f, cx, cy, w, h, conf, cls))


def match(tracks, dets, f):
    """Greedy mutual-nearest: dets (k,6)=cx,cy,w,h,conf,cls. Returns
    (assignments {ti->di}, unmatched_dets set)."""
    if not tracks or not len(dets):
        return {}, set(range(len(dets)))
    P = np.array([t.predict(f) for t in tracks])
    G = np.array([GATE_DIAG * np.hypot(t.w, t.h)
                  + GATE_VEL * np.hypot(t.vx, t.vy) * (f - t.last_f)
                  for t in tracks])
    D = np.hypot(P[:, 0][:, None] - dets[None, :, 0],
                 P[:, 1][:, None] - dets[None, :, 1])
    C = D / np.maximum(G, 4.0)[:, None]
    C[C > 1.0] = np.inf
    assign, used_d = {}, set()
    order = np.dstack(np.unravel_index(np.argsort(C, axis=None), C.shape))[0]
    for ti, di in order:
        ti, di = int(ti), int(di)
        if not np.isfinite(C[ti, di]):
            break
        if ti in assign or di in used_d:
            continue
        assign[ti] = di
        used_d.add(di)
    return assign, set(range(len(dets))) - used_d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--cache", default="balanced_960_skip1")
    args = ap.parse_args()
    t0 = time.time()

    (f_lo, f_hi), src_meta = window_frames(args.project, args.camera,
                                           args.variant)
    fps = {1: 10.0, 2: 25.0, 3: 10.0, 4: 10.0, 5: 10.0}[args.camera]

    cache_pq = (TP._camera_parquet(args.project, args.camera, args.cache)
                .with_suffix(".parquet"))
    if not cache_pq.exists():
        base = TP._camera_parquet(args.project, args.camera, args.cache)
        cache_pq = Path(str(base) + ".parquet")
    pf = pq.ParquetFile(str(cache_pq))
    cols = [c.name for c in pf.schema_arrow]
    cls_col = next((c for c in cols if "class" in c), None)

    # stream row groups, keep only the window
    fr_l, x1_l, y1_l, x2_l, y2_l, cf_l, cl_l = ([] for _ in range(7))
    for b in pf.iter_batches(columns=["frame_idx", "bbox_x1", "bbox_y1",
                                      "bbox_x2", "bbox_y2", "confidence"]
                             + ([cls_col] if cls_col else [])):
        d = b.to_pydict()
        fr = np.asarray(d["frame_idx"], dtype=np.int64)
        m = (fr >= f_lo) & (fr < f_hi)
        if not m.any():
            continue
        fr_l.append(fr[m])
        x1_l.append(np.asarray(d["bbox_x1"], np.float32)[m])
        y1_l.append(np.asarray(d["bbox_y1"], np.float32)[m])
        x2_l.append(np.asarray(d["bbox_x2"], np.float32)[m])
        y2_l.append(np.asarray(d["bbox_y2"], np.float32)[m])
        cf_l.append(np.asarray(d["confidence"], np.float32)[m])
        cl_l.append(np.asarray(d[cls_col], np.float32)[m] if cls_col
                    else np.full(int(m.sum()), 2, np.float32))
    fr = np.concatenate(fr_l)
    cx = (np.concatenate(x1_l) + np.concatenate(x2_l)) / 2
    cy = (np.concatenate(y1_l) + np.concatenate(y2_l)) / 2
    bw = np.concatenate(x2_l) - np.concatenate(x1_l)
    bh = np.concatenate(y2_l) - np.concatenate(y1_l)
    cf = np.concatenate(cf_l)
    cl = np.concatenate(cl_l)
    order = np.argsort(fr, kind="stable")
    fr, cx, cy, bw, bh, cf, cl = (a[order] for a in (fr, cx, cy, bw, bh, cf, cl))
    print(f"[tubelet] cam{args.camera} {args.variant}: {len(fr)} dets in "
          f"window [{f_lo},{f_hi}) from {cache_pq.name} ({time.time()-t0:.0f}s)")

    uniq_f, f_start = np.unique(fr, return_index=True)
    f_end = np.append(f_start[1:], len(fr))
    frame_of = dict(zip(uniq_f.tolist(), zip(f_start.tolist(), f_end.tolist())))

    live: list[Track] = []
    done: list[Track] = []
    next_id = 1
    miss_cap = T_MISS_S * fps
    for f in range(int(f_lo), int(f_hi)):
        se = frame_of.get(f)
        if se is None:
            dets = np.empty((0, 6), np.float32)
        else:
            s, e = se
            dets = np.stack([cx[s:e], cy[s:e], bw[s:e], bh[s:e],
                             cf[s:e], cl[s:e]], 1)
        hi = dets[dets[:, 4] >= ACT]
        lo = dets[(dets[:, 4] >= LOW) & (dets[:, 4] < ACT)]
        assign, un_hi = match(live, hi, f)
        for ti, di in assign.items():
            d = hi[di]
            live[ti].update(f, float(d[0]), float(d[1]), float(d[2]),
                            float(d[3]), float(d[4]), float(d[5]))
        rem = [i for i in range(len(live)) if i not in assign]
        rem_tracks = [live[i] for i in rem]
        assign2, _ = match(rem_tracks, lo, f)
        for k, di in assign2.items():
            d = lo[di]
            rem_tracks[k].update(f, float(d[0]), float(d[1]), float(d[2]),
                                 float(d[3]), float(d[4]), float(d[5]))
        keep = []
        for tr in live:
            if f - tr.last_f > miss_cap:
                done.append(tr)
            else:
                keep.append(tr)
        live = keep
        for di in un_hi:
            d = hi[di]
            live.append(Track(next_id, f, float(d[0]), float(d[1]),
                              float(d[2]), float(d[3]), float(d[4]),
                              float(d[5])))
            next_id += 1
    done.extend(live)

    # offline post-pass
    out_rows = []
    kept = 0
    for tr in done:
        rows = np.array(tr.rows, dtype=np.float64)
        span = (rows[-1, 0] - rows[0, 0]) / fps
        if tr.hits < MIN_HITS or span < MIN_SPAN_S:
            continue
        confs = np.sort(rows[:, 5])[::-1]
        if float(confs[: max(1, len(confs) // 2)].mean()) < RESCORE_FLOOR:
            continue
        kept += 1
        cls_maj = float(np.bincount(rows[:, 6].astype(int)).argmax())
        # interpolate gaps
        full_f = np.arange(rows[0, 0], rows[-1, 0] + 1)
        interp = np.zeros((len(full_f), 8), np.float32)
        interp[:, 0] = tr.tid
        interp[:, 1] = full_f
        for c_idx, col in ((2, 1), (3, 2), (4, 3), (5, 4)):
            interp[:, c_idx] = np.interp(full_f, rows[:, 0], rows[:, col])
        conf_map = dict(zip(rows[:, 0].astype(int).tolist(),
                            rows[:, 5].tolist()))
        interp[:, 6] = [conf_map.get(int(f2), 0.0) for f2 in full_f]
        interp[:, 7] = cls_maj
        # smooth centers (window 3)
        if len(interp) >= 3:
            for c_idx in (2, 3):
                sm = np.convolve(interp[:, c_idx], np.ones(3) / 3, "same")
                sm[0], sm[-1] = interp[0, c_idx], interp[-1, c_idx]
                interp[:, c_idx] = sm
        out_rows.append(interp)

    rows_out = np.concatenate(out_rows)
    rows_out = rows_out[np.lexsort((rows_out[:, 0], rows_out[:, 1]))]
    new_variant = f"v2b_{args.variant}"
    dst = TP.tracks_dir(TP._camera_parquet(args.project, args.camera,
                                           new_variant))
    dst.mkdir(parents=True, exist_ok=True)
    meta = {"format": 2,
            "cols": ["track_id", "frame", "cx", "cy", "bw", "bh", "conf",
                     "class_id"],
            "backend": "v2b_tubelet", "camera": args.camera,
            "variant": new_variant, "frames": [int(f_lo), int(f_hi)],
            "complete": True,
            "v2b": {"cache": args.cache, "act": ACT, "low": LOW,
                    "t_miss_s": T_MISS_S, "min_hits": MIN_HITS,
                    "min_span_s": MIN_SPAN_S,
                    "rescore_floor": RESCORE_FLOOR,
                    "tracks_kept": kept, "tracks_raw": len(done)}}
    np.save(dst / "rows.npy", rows_out)
    (dst / "count.txt").write_text(str(len(rows_out)))
    (dst / "meta.json").write_text(json.dumps(meta))
    print(f"[tubelet] tracks raw={len(done)} kept={kept} rows={len(rows_out)} "
          f"-> {dst} ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
