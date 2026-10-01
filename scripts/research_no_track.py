"""Item 1 (2026-10-01): are the journey labels' no_track vehicles real tracker gaps?

For every labelled vehicle the arm scores no_track, and each side (entry / exit) with no
track assigned, look under the operator's click (back tyre, +-2 frames, padded box):
  TRACK   a dump track box is there (the matcher's miss, not the tracker's)
  DET     no track box, but a raw detection is (the tracker never made / kept a track)
  NONE    no track box and no detection (the detector missed the car)
and, for DET/NONE, whether a track box covers the click within +-0.5 s (TIMING).
Usage: .venv\Scripts\python.exe -X utf8 scripts/research_no_track.py STEM[:prefixes]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_journeys as ej  # noqa: E402
from backend.services import journey_eval as je  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402

PAD = 1 + 2 * je.BOX_PAD


def covered(boxes: np.ndarray, x: float, y: float) -> np.ndarray:
    """boxes: [cx, cy, w, h] rows -> mask of boxes whose padded extent holds (x, y)."""
    if not len(boxes):
        return np.zeros(0, bool)
    return ((np.abs(x - boxes[:, 0]) <= boxes[:, 2] / 2 * PAD)
            & (np.abs(y - boxes[:, 1]) <= boxes[:, 3] / 2 * PAD))


def main() -> int:
    stem, prefixes = ej.parse(sys.argv[1])
    res = ej.run_arm(stem, prefixes)
    con = sqlite3.connect(f"file:data/projects/{ej.PROJ}/project.db?mode=ro", uri=True)
    tally = Counter()
    for clip in list_clips(ej.PROJ):
        cid = clip["clip_id"]
        if cid not in res:
            continue
        cam = clip["camera_id"]
        window = "study_" + cid.split("_")[1]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        _, rows = ej.locate(stem.split("|")[0], prefixes, cam, window, chash)
        det = pd.read_parquet(parquet_path(ej.PROJ, cam, chash, window))
        f0, f1 = clip["start_frame"] - int(fps), clip["end_frame"] + int(fps)
        det = det[(det.frame_idx >= f0) & (det.frame_idx <= f1)]
        dby = {f: g for f, g in det.groupby("frame_idx")}
        rows = rows[(rows[:, 1] >= f0) & (rows[:, 1] <= f1)]
        rby = {}
        for r in rows:
            rby.setdefault(int(r[1]), []).append(r)
        labels = {lb["label_id"]: lb for lb in list_labels(ej.PROJ, cid)}
        for v in res[cid]["per_vehicle"]:
            if v["outcome"] != "no_track":
                continue
            lb = labels[v["label_id"]]
            for side in ("entry", "exit"):
                f, x, y = lb[f"{side}_frame"], lb[f"{side}_x"], lb[f"{side}_y"]
                k = 2
                trk = any(covered(np.array([[r[2], r[3], r[4], r[5]] for r in rby.get(f + d, [])]),
                                  x, y).any() for d in range(-k, k + 1) if rby.get(f + d))
                confs = []
                for d in range(-k, k + 1):
                    g = dby.get(f + d)
                    if g is None:
                        continue
                    b = np.c_[(g.bbox_x1 + g.bbox_x2) / 2, (g.bbox_y1 + g.bbox_y2) / 2,
                              g.bbox_x2 - g.bbox_x1, g.bbox_y2 - g.bbox_y1]
                    m = covered(b, x, y)
                    confs += g.confidence.values[m].tolist()
                w = int(0.5 * fps)
                near_t = any(covered(np.array([[r[2], r[3], r[4], r[5]] for r in rby.get(f + d, [])]),
                                     x, y).any() for d in range(-w, w + 1) if rby.get(f + d))
                kind = "TRACK" if trk else ("DET" if confs else "NONE")
                tag = kind + ("+timing" if kind != "TRACK" and near_t else "")
                tally[(cam, side, tag)] += 1
                print(f"{cid} label {v['label_id']:4} {side:5} {tag:12} "
                      f"det conf max {max(confs):.2f}" if confs else
                      f"{cid} label {v['label_id']:4} {side:5} {tag:12}")
    print("\nTALLY (camera, side, kind):")
    for k, n in sorted(tally.items()):
        print(f"  cam{k[0]} {k[1]:5} {k[2]:12} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
