"""Are overlapping detection pairs ONE vehicle (a detector double box) or TWO
(one car occluding another)? (2026-09-12, tracker input step)

For sampled frames, every pair of boxes overlapping above 0.45 IoU. Follow
both boxes through the raw detections for +-SPAN frames (each by its own
nearest box with the pair's common displacement): if at any frame the two
followed boxes overlap < 0.3 IoU, they are TWO vehicles that separated;
if they stay stacked (or one simply vanishes), ONE vehicle.
Reports the TWO-vehicle share by IoU band and class relation.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_dup_boxes.py PROJ CAM VARIANT
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import parquet_path  # noqa: E402

SPAN = 10


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def main() -> int:
    proj, cam, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
    t = pq.read_table(parquet_path(proj, cam, chash, variant)).to_pandas()
    by = {int(f): g[["bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "class_id"]].values for f, g in t.groupby("frame_idx")}
    frames = sorted(by)
    sample = frames[::25]
    res = Counter(); tot = Counter()

    def follow(box, f_from, f_to):
        """Chain `box` from frame f_from to f_to (step +-1) by nearest-centre box."""
        cur = np.asarray(box[:4], dtype=float)
        step = 1 if f_to > f_from else -1
        path = {}
        for f in range(f_from + step, f_to + step, step):
            g = by.get(f)
            if g is None or not len(g):
                continue
            c = (cur[:2] + cur[2:]) / 2
            cc = (g[:, :2] + g[:, 2:4]) / 2
            d = np.hypot(cc[:, 0] - c[0], cc[:, 1] - c[1])
            k = int(np.argmin(d))
            w = cur[2] - cur[0]
            if d[k] > 0.6 * max(w, 1.0):
                continue
            cur = g[k, :4].astype(float)
            path[f] = cur
        return path

    for f in sample:
        g = by[f]
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                v = iou(g[i], g[j])
                if v <= 0.45:
                    continue
                band = "0.45-0.6" if v <= 0.6 else ("0.6-0.8" if v <= 0.8 else ">0.8")
                rel = "same" if g[i][4] == g[j][4] else "cross"
                key = (rel, band)
                tot[key] += 1
                two = False
                for f_to in (f + SPAN, f - SPAN):
                    pi, pj = follow(g[i], f, f_to), follow(g[j], f, f_to)
                    for ff in set(pi) & set(pj):
                        if iou(pi[ff], pj[ff]) < 0.3:
                            two = True
                            break
                    if two:
                        break
                if two:
                    res[key] += 1
    print(f"{proj} cam{cam} {variant}: pairs on {len(sample)} frames; TWO-vehicle share (separate within +-{SPAN} frames):")
    for key in sorted(tot):
        print(f"   {key[0]:5} IoU {key[1]:8}: {tot[key]:6} pairs, two vehicles {res[key]:5} ({res[key] / max(1, tot[key]):.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
