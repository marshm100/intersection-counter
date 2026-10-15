"""ONE CAR ON TWO TRACKS vs TWO CARS SIDE BY SIDE - does the DETECTOR tell them apart?
(2026-10-15, operator: "fix double counting for all cameras", no camera-unique tooling.)
Box geometry cannot (research_near_twins: 7 double counts vs 20 real pairs at the same IoU /
distance). Here every touching counted pair on the labelled clips (research_near_twins.pairs)
is judged by the labels as before, and measured against the raw detector boxes over the
frames both tracks live:
  det_a / det_b  share of common frames the track's box is a detection (IoU >= DET_IOU)
  two_dets       share of common frames BOTH boxes are DISTINCT detections (two cars seen)
  shared         share of common frames both boxes' best detection is the SAME box
  conf_a / conf_b median confidence of the matched detections
  tags           the two counted events' decision paths (full / entry_only / exit_only ...)
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_double_det.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402
from research_near_twins import TOUCH_FRAC, pairs  # noqa: E402

DET_IOU = 0.5


def _iou(b, d):
    x1 = np.maximum(b[0], d[:, 0]); y1 = np.maximum(b[1], d[:, 1])
    x2 = np.minimum(b[2], d[:, 2]); y2 = np.minimum(b[3], d[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    return inter / np.maximum((b[2] - b[0]) * (b[3] - b[1]) + (d[:, 2] - d[:, 0]) * (d[:, 3] - d[:, 1]) - inter, 1e-6)


def _box(r):
    return np.array([r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2])


def measure(p, rows, det):
    a = rows[rows[:, 0] == p["a"]]; b = rows[rows[:, 0] == p["b"]]
    com, ia, ib = np.intersect1d(a[:, 1], b[:, 1], return_indices=True)
    da = db_ = two = shared = 0
    ca, cb = [], []
    for f, i, j in zip(com, ia, ib):
        d = det.get(int(f))
        if d is None or not len(d):
            continue
        ua, ub = _iou(_box(a[i]), d), _iou(_box(b[j]), d)
        ka, kb = int(np.argmax(ua)), int(np.argmax(ub))
        ha, hb = ua[ka] >= DET_IOU, ub[kb] >= DET_IOU
        da += ha; db_ += hb
        if ha:
            ca.append(d[ka, 4])
        if hb:
            cb.append(d[kb, 4])
        if ha and hb:
            if ka == kb:
                shared += 1
            else:
                two += 1
    n = max(len(com), 1)
    a0, a1, b0, b1 = a[0, 1], a[-1, 1], b[0, 1], b[-1, 1]
    if b0 < a0:
        a0, a1, b0, b1 = b0, b1, a0, a1
    life = dict(birth_gap=int(b0 - a0), death_gap=int(b1 - a1), nested=bool(b1 <= a1),
                area=float(np.median(b[:, 4] * b[:, 5]) / max(np.median(a[:, 4] * a[:, 5]), 1.0))
                if a[0, 1] <= b[0, 1] else float(np.median(a[:, 4] * a[:, 5]) / max(np.median(b[:, 4] * b[:, 5]), 1.0)))
    return dict(**life, det_a=da / n, det_b=db_ / n, two=two / n, shared=shared / n,
                conf_a=float(np.median(ca)) if ca else 0.0, conf_b=float(np.median(cb)) if cb else 0.0)


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    groups = defaultdict(list)
    for clip in list_clips(PROJ):
        labels = list_labels(PROJ, clip["clip_id"])
        if not labels:
            continue
        cam = clip["camera_id"]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        fps = float(fps)
        window = "study_" + clip["clip_id"].split("_")[1]
        db, rows = locate(stem, {}, cam, window, chash)
        if db is None:
            continue
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        byf = je.index_rows(rows, f_lo - 2, f_hi + 2)
        ein, eout = je._assign_clicks(labels, rows, byf, fps)
        owner = {}
        for side in (eout, ein):
            for lid, t in side.items():
                owner.setdefault(t, set()).add(lid)
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        d.close()
        from backend.services.mouth_from_motion import _load
        dc = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        tag = {e["tid"]: e["tag"] for e in _load(dc, cam)}
        dc.close()
        tbl = pq.read_table(parquet_path(PROJ, cam, chash, window),
                            filters=[("frame_idx", ">=", f_lo - 5), ("frame_idx", "<=", f_hi + 400)]).to_pandas()
        det = {int(f): g[["bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "confidence"]].to_numpy()
               for f, g in tbl.groupby("frame_idx")}
        for p in pairs(str(db), rows, cam):
            if p["touch"] < TOUCH_FRAC or not (f_lo <= p["fa"] <= f_hi):
                continue
            la, lb = owner.get(p["a"], set()), owner.get(p["b"], set())
            if la and lb and not (la & lb):
                k = "TWO"
            elif la or lb:
                k = "ONE"
            else:
                k = "unlabelled"
            m = measure(p, rows, det)
            groups[k].append(m)
            print(f"  {k:10} {clip['clip_id']:14} t{p['a']}+t{p['b']} box {p['w']:.0f}px "
                  f"det {m['det_a']:.2f}/{m['det_b']:.2f} two_dets {m['two']:.2f} shared {m['shared']:.2f} "
                  f"conf {m['conf_a']:.2f}/{m['conf_b']:.2f}  tags {tag.get(p['a'])} / {tag.get(p['b'])}  "
                  f"later born +{m['birth_gap']}f dies {m['death_gap']:+d}f nested {m['nested']} area {m['area']:.2f}")
    print()
    for k, ms in groups.items():
        print(f"{k:10} n={len(ms):3}  two_dets median {np.median([m['two'] for m in ms]):.2f}  "
              f"min-det median {np.median([min(m['det_a'], m['det_b']) for m in ms]):.2f}  "
              f"shared median {np.median([m['shared'] for m in ms]):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
