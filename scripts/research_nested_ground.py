"""ONE CAR'S SECOND BOX, OR A CAR QUEUED BEHIND? (2026-10-15, operator choice "1": fix the cars the tracker had the
information for). dt2 (retire the younger twin + no birth for a box nested in a held box) cut breaks / swaps on every
camera's chains but lost labelled cam2 cars queued behind a leader, whose box is nested in the leader's too.
Physical test: two boxes of ONE car touch the road at the same place (same bottom edge); a car BEHIND touches it
further back (its bottom edge higher in the image). For every pair of tracks on the labelled clips whose boxes meet
dt2's trigger (containment of the smaller >= 0.9 and IoU >= 0.4 in >= 3 frames), judged by the labels:
  ONE    the same labelled car rides both (entered on one id, left on the other)
  TWO    each id carries a different labelled car
  UNCL   one id claimed by no labelled car
Measures at the trigger frames (medians): bottom gap = (bottom of the outer box - bottom of the nested box) / outer
height (0 = same ground contact; > 0 = nested box ends higher, i.e. further away); top gap likewise; width ratio.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_nested_ground.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402

CONTAIN, IOU, NFR = 0.9, 0.4, 3


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
        db, rows = locate(stem, {}, cam, "study_" + clip["clip_id"].split("_")[1], chash)
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        byf = je.index_rows(rows, f_lo - je.SEARCH_FRAMES, f_hi + je.SEARCH_FRAMES)
        dups = je.duplicate_labels(labels, fps, byf)
        labs = [lb for lb in labels if lb["label_id"] not in dups
                and lb.get("entry_frame") is not None and lb.get("exit_frame") is not None]
        ein, eout = je._assign_clicks(labs, rows, byf, fps)
        owner = defaultdict(set)
        for side in (ein, eout):
            for lid, t in side.items():
                owner[t].add(lid)
        sub = rows[(rows[:, 1] >= f_lo) & (rows[:, 1] <= f_hi)]
        hits = defaultdict(list)          # (outer, inner) -> [(bottom gap, top gap, width ratio)]
        fr = sub[:, 1].astype(np.int64)
        order = np.argsort(fr, kind="stable")
        uf, s0 = np.unique(fr[order], return_index=True)
        e0 = np.append(s0[1:], len(order))
        for a_, b_ in zip(s0, e0):
            R = sub[order[a_:b_]]
            if len(R) < 2:
                continue
            x1, y1 = R[:, 2] - R[:, 4] / 2, R[:, 3] - R[:, 5] / 2
            x2, y2 = R[:, 2] + R[:, 4] / 2, R[:, 3] + R[:, 5] / 2
            iw = np.clip(np.minimum(x2[:, None], x2[None]) - np.maximum(x1[:, None], x1[None]), 0, None)
            ih = np.clip(np.minimum(y2[:, None], y2[None]) - np.maximum(y1[:, None], y1[None]), 0, None)
            inter = iw * ih
            area = R[:, 4] * R[:, 5]
            iou = inter / np.maximum(area[:, None] + area[None] - inter, 1e-6)
            cont = inter / np.maximum(area[None], 1e-6)       # share of column box inside row box
            ii, jj = np.where((cont >= CONTAIN) & (iou >= IOU) & (area[:, None] >= area[None]))
            for i, j in zip(ii, jj):
                if i == j:
                    continue
                h = max(R[i, 5], 1.0)
                hits[(int(R[i, 0]), int(R[j, 0]))].append(((y2[i] - y2[j]) / h, (y1[j] - y1[i]) / h,
                                                           R[j, 4] / max(R[i, 4], 1.0)))
        for (o, n), v in hits.items():
            if len(v) < NFR:
                continue
            lo_, ln = owner.get(o, set()), owner.get(n, set())
            if lo_ & ln:
                k = "ONE"
            elif lo_ and ln:
                k = "TWO"
            else:
                k = "UNCL"
            v = np.array(v)
            m = np.median(v, axis=0)
            groups[k].append(m)
            if k != "UNCL":
                print(f"  {k:4} {clip['clip_id']:14} outer t{o} nested t{n}  frames {len(v):3}  bottom gap {m[0]:+.2f}  "
                      f"top gap {m[1]:+.2f}  width {m[2]:.2f}  labels {sorted(lo_)}/{sorted(ln)}")
    print()
    for k, ms in groups.items():
        ms = np.array(ms)
        print(f"{k:4} n={len(ms):4}  bottom gap q10/50/90 {np.percentile(ms[:, 0], 10):+.2f} / "
              f"{np.median(ms[:, 0]):+.2f} / {np.percentile(ms[:, 0], 90):+.2f}   top gap median {np.median(ms[:, 1]):+.2f}"
              f"   width median {np.median(ms[:, 2]):.2f}")
        for th in (0.05, 0.1, 0.15, 0.2):
            print(f"      bottom gap <= {th:.2f}: {int((ms[:, 0] <= th).sum())} of {len(ms)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
