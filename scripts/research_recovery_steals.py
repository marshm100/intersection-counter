"""Which position recoveries are STEALS? (2026-09-12, arm d18 diagnosis)

Runs the recovering tracker over a window's detection cache in-process
(same recipe as run_pass1 for a default-recipe camera: no NMS, buffer 1.0,
activation 0.25, match 0.8) with the recovery log on, then labels every
recovery against the BASE dump (the library tracker's tracks) as pseudo-
truth: the recovered detection is a STEAL when it overlaps (IoU >= 0.5) a
base track other than the one the recovering track overlapped on its
previous frame AND both base tracks were alive at the same time (two
vehicles). Reports the steal share by track state, lost age, cost and
direction relative to the track's motion.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_recovery_steals.py PROJ CAM BASE_VARIANT
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config as cfg  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.tracker import ByteTrackBackend  # noqa: E402

STEAL = "STEAL (two vehicles alive together)"


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def main() -> int:
    proj, cam, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    pqp = parquet_path(proj, cam, chash, variant)
    meta = json.load(open(pqp.with_suffix(".meta.json")))
    f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
    t = pq.read_table(pqp).to_pandas()
    t = t[(t.frame_idx >= f0) & (t.frame_idx <= f1)]
    by = {f: g for f, g in t.groupby("frame_idx")}

    cfg.TRACKER_POSITION_RECOVERY = True
    be = ByteTrackBackend(track_activation_threshold=0.25, lost_track_buffer=150,
                          minimum_matching_threshold=0.8, frame_rate=int(fps))
    be.byte_track.recovery_log = []
    pr_by: dict = defaultdict(dict)   # frame -> tid -> box
    n_tracks = set()
    for f in range(f0, f1 + 1):
        g = by.get(f)
        dets = [] if g is None else [
            {"bbox": [float(a), float(b), float(c), float(d)], "confidence": float(s), "class_id": int(k)}
            for a, b, c, d, s, k in zip(g.bbox_x1.values, g.bbox_y1.values, g.bbox_x2.values,
                                        g.bbox_y2.values, g.confidence.values, g.class_id.values)]
        for r in be.update(dets, f):
            pr_by[f][r["track_id"]] = tuple(r["bbox"])
            n_tracks.add(r["track_id"])
    log = be.byte_track.recovery_log
    print(f"{proj} cam{cam} {variant}: {len(log)} recoveries over {f1 - f0 + 1} frames; "
          f"tracks {len(n_tracks)} (base dump: {len(np.unique(load_dump(tracks_dir(pqp))[:, 0]))})")

    base = np.asarray(load_dump(tracks_dir(pqp)))
    base = base[np.argsort(base[:, 1], kind="stable")]
    uf, s_ = np.unique(base[:, 1], return_index=True); e_ = np.append(s_[1:], len(base))
    bidx = dict(zip(uf.astype(int), zip(s_, e_)))
    bs = base[np.lexsort((base[:, 1], base[:, 0]))]
    ut, st_ = np.unique(bs[:, 0], return_index=True); en_ = np.append(st_[1:], len(bs))
    blife = {int(t_): (int(bs[a_, 1]), int(bs[b_ - 1, 1])) for t_, a_, b_ in zip(ut, st_, en_)}

    def base_track_at(f, box):
        ab = bidx.get(f)
        if ab is None:
            return None
        best = (0.0, None)
        for r in base[ab[0]:ab[1]]:
            bb = (r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2)
            v = iou(box, bb)
            if v > best[0]:
                best = (v, int(r[0]))
        return best[1] if best[0] >= 0.5 else None

    lab = Counter()
    by_state, by_age, by_cost, by_dir, by_iou = (defaultdict(Counter) for _ in range(5))
    for (f_int, tid, was_lost, age, cost, pred, det, score) in log:
        f = f0 + f_int - 1          # the library's frame_id is internal (1..N); dumps use absolute frames
        prev = None
        for k in range(1, 8):
            b = pr_by.get(f - k, {}).get(tid)
            if b is not None:
                prev = (b, f - k); break
        b_now = base_track_at(f, det)
        b_prev = base_track_at(prev[1], prev[0]) if prev else None
        if b_now is None or b_prev is None:
            label = "unknown"
        elif b_now == b_prev:
            label = "same vehicle"
        else:
            l1, l2 = blife[b_now], blife[b_prev]
            label = STEAL if (l1[0] <= l2[1] and l2[0] <= l1[1]) else "same vehicle (base fragments)"
        lab[label] += 1
        by_state["lost" if was_lost else "tracked"][label] += 1
        by_age[min(age, 6)][label] += 1
        by_cost[round(min(cost, 0.89) // 0.15 * 0.15, 2)][label] += 1
        v = iou(pred, det)
        by_iou["0 (no overlap)" if v <= 0 else ("(0, 0.1]" if v <= 0.1 else ("(0.1, 0.2]" if v <= 0.2 else "> 0.2"))][label] += 1
        if prev:
            pc = ((prev[0][0] + prev[0][2]) / 2, (prev[0][1] + prev[0][3]) / 2)
            cc = ((pred[0] + pred[2]) / 2, (pred[1] + pred[3]) / 2)
            dc = ((det[0] + det[2]) / 2, (det[1] + det[3]) / 2)
            dot = (cc[0] - pc[0]) * (dc[0] - cc[0]) + (cc[1] - pc[1]) * (dc[1] - cc[1])
            by_dir["forward" if dot > 0 else ("backward" if dot < 0 else "still")][label] += 1
    print("labels:", dict(lab))

    def show(title, table, keys=None):
        print(title)
        for k in (keys or sorted(table)):
            c = table[k]; n = sum(c.values()); st = c.get(STEAL, 0)
            same = c.get("same vehicle", 0) + c.get("same vehicle (base fragments)", 0)
            print(f"   {str(k):>8}: n={n:5}  steal {st:4} ({st / max(1, n):.0%})  same {same:4}  unknown {c.get('unknown', 0):4}")

    show("by track state:", by_state, ["tracked", "lost"])
    show("by frames since last seen (6 = 6+):", by_age)
    show("by cost (box widths, bucket start):", by_cost)
    show("by direction of the jump vs the track's motion:", by_dir, ["forward", "backward", "still"])
    show("by IoU(predicted box, recovered box):", by_iou, ["0 (no overlap)", "(0, 0.1]", "(0.1, 0.2]", "> 0.2"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
