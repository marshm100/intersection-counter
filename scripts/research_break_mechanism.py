"""WHY THE SECOND ID IS BORN (2026-10-15, after research_inside_box). For every labelled car the
tracker breaks inside the box (SWAP / HANDOFF: the car's exit id is born while its entry id is still
alive), at the exit id's BIRTH frame, from the raw detector boxes and the two tracks' boxes:
  DUP-DET   the two ids sit on two detector boxes that overlap each other (IoU >= DUP_IOU): the
            detector drew the car twice and the tracker gave the second box a new id
  RIDE      the ids' boxes overlap (IoU >= 0.1) and stay together for the next frames
  JUMP      the entry id's box is elsewhere (IoU < 0.1 with the new id): it had already left this
            car - for a neighbour (theft) - and the car was re-born under a new id
also: the detection IoU between the two, how many detections touch the car, the entry id's
confidence-matched detection, and the box sizes.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_break_mechanism.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402

DUP_IOU = 0.3


def box(r):
    return np.array([r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2])


def iou1(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    return i / max((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i, 1e-6)


def best_det(d, b):
    if d is None or not len(d):
        return None, 0.0
    v = [iou1(b, x[:4]) for x in d]
    k = int(np.argmax(v))
    return d[k], v[k]


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    kinds = Counter()
    for clip in list_clips(PROJ):
        labels = list_labels(PROJ, clip["clip_id"])
        if not labels:
            continue
        cam = clip["camera_id"]
        window = "study_" + clip["clip_id"].split("_")[1]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        fps = float(fps)
        db, rows = locate(stem, {}, cam, window, chash)
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        byf = je.index_rows(rows, f_lo - je.SEARCH_FRAMES, f_hi + je.SEARCH_FRAMES)
        dups = je.duplicate_labels(labels, fps, byf)
        labs = [lb for lb in labels if lb["label_id"] not in dups
                and lb.get("entry_frame") is not None and lb.get("exit_frame") is not None]
        ein, eout = je._assign_clicks(labs, rows, byf, fps)
        tbl = pq.read_table(parquet_path(PROJ, cam, chash, window),
                            filters=[("frame_idx", ">=", f_lo - 400), ("frame_idx", "<=", f_hi + 400)]).to_pandas()
        det = {int(f): g[["bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "confidence"]].to_numpy()
               for f, g in tbl.groupby("frame_idx")}
        for lb in labs:
            tin, tout = ein.get(lb["label_id"]), eout.get(lb["label_id"])
            if tin is None or tout is None or tin == tout:
                continue
            a, b = rows[rows[:, 0] == tin], rows[rows[:, 0] == tout]
            bf = int(b[0, 1])
            if bf > a[-1, 1]:
                continue                                  # a gap, not two ids at once
            ra = a[a[:, 1] == bf]
            if not len(ra):
                ia = int(np.argmin(np.abs(a[:, 1] - bf)))
                ra = a[ia:ia + 1]
            ba, bb = box(ra[0]), box(b[0])
            ab = iou1(ba, bb)
            da, va = best_det(det.get(bf), ba)
            dbx, vb = best_det(det.get(bf), bb)
            same = da is not None and dbx is not None and np.allclose(da, dbx)
            dd = iou1(da[:4], dbx[:4]) if (da is not None and dbx is not None and not same) else (1.0 if same else 0.0)
            # do they ride together over the next frames?
            com = np.intersect1d(a[:, 1], b[:, 1])
            com = com[(com >= bf) & (com <= bf + 10)]
            ride = np.mean([iou1(box(a[a[:, 1] == f][0]), box(b[b[:, 1] == f][0])) >= 0.1 for f in com]) if len(com) else 0.0
            if ab < 0.1:
                k = "JUMP"
            elif not same and dd >= DUP_IOU:
                k = "DUP-DET"
            elif same:
                k = "ONE DET, TWO IDS"
            else:
                k = "RIDE (distinct dets)"
            # JUMP: the exit id was born on ANOTHER car and took this one over later. Where the two
            # ids meet (closest approach over their common life) - how much the two cars' boxes
            # overlap there, and whether the detector still draws two boxes
            meet = ""
            if k == "JUMP":
                cf, ia_, ib_ = np.intersect1d(a[:, 1], b[:, 1], return_indices=True)
                if len(cf):
                    dist = np.hypot(a[ia_, 2] - b[ib_, 2], a[ia_, 3] - b[ib_, 3]) / np.maximum(a[ia_, 4], 1)
                    j = int(np.argmin(dist))
                    mf = int(cf[j])
                    occ = iou1(box(a[ia_[j]]), box(b[ib_[j]]))
                    near = det.get(mf)
                    ndet = 0 if near is None else sum(iou1(box(a[ia_[j]]), x[:4]) > 0.1 or iou1(box(b[ib_[j]]), x[:4]) > 0.1
                                                     for x in near)
                    k = "SWAP AT OCCLUSION" if occ >= 0.3 else ("SWAP SIDE BY SIDE" if dist[j] < 1.5 else "SWAP APART")
                    meet = f"  meet f{mf} dist {dist[j]:.2f}w IoU {occ:.2f} dets {ndet}"
                else:
                    k = "JUMP (never together)"
            kinds[k] += 1
            print(f"cam{cam} {clip['clip_id']:14} label {lb['label_id']:4} t{tin}->t{tout} birth f{bf}  "
                  f"id-box IoU {ab:.2f}  det-det IoU {dd:.2f} (match {va:.2f}/{vb:.2f})  ride {ride:.0%}  "
                  f"w {ra[0][4]:.0f}/{b[0][4]:.0f}  conf {0 if dbx is None else dbx[4]:.2f}  -> {k}{meet}")
    print()
    for k, n in kinds.most_common():
        print(f"  {n:3}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
