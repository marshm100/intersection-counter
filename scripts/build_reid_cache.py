"""ReID embedding sidecar (Stage 1, docs/reid_project_plan_2026-06-01.md).

ReID needs real frames, which breaks the bbox-only detection-cache loop. So embed
every cached detection ONCE here (decode the video, crop each bbox, run osnet_x0_25),
and write a sidecar npz aligned to the detection cache. The ReID retrack then reads
these vectors instead of re-decoding — restoring the fast iteration loop.

Parity: we call boxmot's OWN `ReID(...).model.get_features(boxes, img)` — the exact
call BotSort makes internally when with_reid=True — so the cached vectors are
byte-identical to what an on-the-fly ReID run would compute. get_features is per-box
independent, so embedding all boxes then masking == embedding the high-conf subset.

Sidecar layout (npz): frames[N] int32, bboxes[N,4] float32 (x1,y1,x2,y2),
embs[N,512] float16. Lookup key at read time = (frame, rounded bbox).

Usage:  py scripts/build_reid_cache.py --start-hms 07:00:00 --minutes 30
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path)
from groundtruth import VIDEO_START


def sidecar_path(pq: Path) -> Path:
    return pq.with_name(pq.stem + ".reid.npz")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--weights", default="osnet_x0_25_msmt17.pt")
    args = ap.parse_args()

    conn = sqlite3.connect("data/projects/97a7849a/project.db")
    v = conn.execute("SELECT path,file_size_bytes,total_frames,fps FROM videos "
                     "WHERE camera_id=? ORDER BY sort_order LIMIT 1", (args.camera,)).fetchone()
    conn.close()
    vpath, fsize, total_frames, fps = v[0], v[1], v[2], float(v[3])
    ch, _ = compute_video_content_hash(vpath, file_size_bytes=fsize, total_frames=total_frames)
    pq = parquet_path("97a7849a", args.camera, ch, DEFAULT_VARIANT)
    out = sidecar_path(pq)

    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    f_lo = int((t0 - VIDEO_START).total_seconds() * fps)
    f_hi = f_lo + int(args.minutes * 60 * fps)

    # frame -> list of bbox (cache order)
    need = {}
    total_dets = 0
    for fidx, dets in DetectionCacheReader(pq).iter_frames():
        if fidx < f_lo or fidx >= f_hi:
            continue
        bbs = [d["bbox"] for d in dets]   # ALL detections (tracker sees all)
        if bbs:
            need[fidx] = bbs
            total_dets += len(bbs)
    print(f"window frames {f_lo}-{f_hi}: {len(need)} frames, {total_dets} detections to embed")

    from boxmot.reid.core.reid import ReID
    model = ReID(weights=args.weights, device=args.device).model

    cap = cv2.VideoCapture(vpath)
    cap.set(cv2.CAP_PROP_POS_FRAMES, min(need))
    frames_out, bboxes_out, embs_out = [], [], []
    hi = max(need)
    done = 0
    while need:
        ret, img = cap.read()
        if not ret:
            break
        actual = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if actual > hi:
            break
        bbs = need.pop(actual, None)
        if not bbs:
            continue
        boxes = np.asarray(bbs, dtype=np.float32)
        feats = np.asarray(model.get_features(boxes, img), dtype=np.float16)
        for bb, emb in zip(boxes, feats):
            frames_out.append(actual)
            bboxes_out.append(bb)
            embs_out.append(emb)
        done += 1
        if done % 2000 == 0:
            print(f"  embedded {done} frames...")
    cap.release()

    frames_arr = np.asarray(frames_out, dtype=np.int32)
    bboxes_arr = np.asarray(bboxes_out, dtype=np.float32)
    embs_arr = np.asarray(embs_out, dtype=np.float16)
    np.savez(out, frames=frames_arr, bboxes=bboxes_arr, embs=embs_arr)
    miss = total_dets - len(frames_arr)
    print(f"wrote {out}  ({len(frames_arr)} embeddings, dim {embs_arr.shape[1] if embs_arr.size else 0}, "
          f"{miss} detections missed/undeocded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
