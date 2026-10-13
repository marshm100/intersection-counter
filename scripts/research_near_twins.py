"""NEAR-MISS TWINS (2026-10-13, the cam2 red car t655 / t686): two COUNTED tracks that ride one
vehicle - boxes overlapping in nearly every common frame, centres close - but whose median IoU
falls under the coexisting-twin rule's TWIN_IOU_MIN because the boxes are small and jitter.
Both get counted. For every window of an arm: the pairs the rule rejects only on IoU, by the
size of the boxes, and the cells they are counted in. On the labelled clips: how many such pairs
are ONE labelled vehicle (a double count) versus TWO labelled vehicles (two real cars).
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_near_twins.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from backend.services.track_chains import STITCH_STAT_DIST  # noqa: E402
from backend.services.turn_merge import TWIN_IOU_MIN, TWIN_OVERLAP_FRAC  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402
from v2_score_dev import CORRIDOR, NORM, SITES, leg_dir_for  # noqa: E402

WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
           (3, "study_0600"), (4, "study_0700"), (4, "study_1100"), (4, "study_1600"), (5, "study_0700"),
           (5, "study_1100"), (5, "study_1600")]
TOUCH_FRAC = 0.9      # boxes overlap (IoU > 0) in at least this share of common frames


def pairs(db: str, rows: np.ndarray, cam: int):
    """Counted-event track pairs the twin rule tests, with the clause values."""
    d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ev = {int(t): (o, mv) for t, o, mv in d.execute(
        "SELECT vehicle_track_id, origin_leg_id, movement FROM vehicle_events "
        "WHERE camera_id=? AND COALESCE(rejected,0)=0 AND vehicle_track_id >= 0", (cam,))}
    sel = rows[np.isin(rows[:, 0], list(ev))]
    sel = sel[np.lexsort((sel[:, 1], sel[:, 0]))]
    tids, i0 = np.unique(sel[:, 0], return_index=True)
    tr = dict(zip(tids.astype(int), np.split(sel, i0[1:])))
    order = sorted(tr, key=lambda t: tr[t][0, 1])
    out = []
    for i, ti in enumerate(order):
        a = tr[ti]
        for tj in order[i + 1:]:
            b = tr[tj]
            if b[0, 1] > a[-1, 1]:
                break
            ov = min(a[-1, 1], b[-1, 1]) - max(a[0, 1], b[0, 1])
            short = min(a[-1, 1] - a[0, 1], b[-1, 1] - b[0, 1])
            if short <= 0 or ov < TWIN_OVERLAP_FRAC * short:
                continue
            com, ia, ib = np.intersect1d(a[:, 1], b[:, 1], return_indices=True)
            if len(com) < 5:
                continue
            pa, pb = a[ia], b[ib]
            dist = np.hypot(pa[:, 2] - pb[:, 2], pa[:, 3] - pb[:, 3])
            if np.median(dist) > STITCH_STAT_DIST:
                continue
            x1 = np.maximum(pa[:, 2] - pa[:, 4] / 2, pb[:, 2] - pb[:, 4] / 2)
            x2 = np.minimum(pa[:, 2] + pa[:, 4] / 2, pb[:, 2] + pb[:, 4] / 2)
            y1 = np.maximum(pa[:, 3] - pa[:, 5] / 2, pb[:, 3] - pb[:, 5] / 2)
            y2 = np.minimum(pa[:, 3] + pa[:, 5] / 2, pb[:, 3] + pb[:, 5] / 2)
            inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
            iou = inter / np.maximum(pa[:, 4] * pa[:, 5] + pb[:, 4] * pb[:, 5] - inter, 1e-6)
            if np.median(iou) >= TWIN_IOU_MIN:
                continue                       # the rule already takes these
            touch = float((iou > 0).mean())
            w = float(np.median(np.r_[pa[:, 4], pb[:, 4]]))
            dist_w = float(np.median(dist)) / max(w, 1.0)
            out.append(dict(a=ti, b=tj, iou=float(np.median(iou)), touch=touch, w=w, dist_w=dist_w,
                            n=len(com), fa=int(max(a[0, 1], b[0, 1])), fb=int(min(a[-1, 1], b[-1, 1])),
                            ca=ev[ti], cb=ev[tj]))
    return out


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "dt2c"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    print("FLEET: counted pairs passing every twin clause EXCEPT IoU (overlap, >=5 common frames, centres "
          f"<= {STITCH_STAT_DIST:g} px), split by how often the boxes touch")
    for cam, w in WINDOWS:
        chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
        db, rows = locate(stem, {}, cam, w, chash)
        ps = pairs(str(db), rows, cam)
        ld = leg_dir_for(CORRIDOR, cam, SITES[CORRIDOR])
        tight = [p for p in ps if p["touch"] >= TOUCH_FRAC]
        cells = Counter(f"{ld.get(p['cb'][0])} {NORM.get(p['cb'][1], p['cb'][1])}" for p in tight)
        small = sum(p["w"] < 40 for p in tight)
        print(f"  cam{cam} {w}: near-miss pairs {len(ps):4}, touching >= {TOUCH_FRAC:.0%} of frames {len(tight):4} "
              f"(boxes < 40 px: {small})  cells of the later track {cells.most_common(4)}")
    print("\nLABELLED CLIPS: touching near-miss pairs inside a clip, judged by the labels")
    tot = Counter()
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
        byf = je.index_rows(rows, f_lo - 2, f_hi + 2)
        lab = labels                        # duplicates kept on purpose: two clicks may be two cars
        ein, eout = je._assign_clicks(lab, rows, byf, fps)
        owner = {}
        for side in (eout, ein):
            for lid, t in side.items():
                owner.setdefault(t, set()).add(lid)
        dup = je.duplicate_labels(labels, fps, byf)
        for p in pairs(str(db), rows, cam):
            if p["touch"] < TOUCH_FRAC or not (f_lo <= p["fa"] <= f_hi):
                continue
            la, lb = owner.get(p["a"], set()), owner.get(p["b"], set())
            if la and lb and not (la & lb):
                k = "TWO labelled vehicles (two real cars)"
            elif la and lb:
                k = "ONE labelled vehicle on both (double count)"
            elif la or lb:
                k = "one track labelled, the other unclaimed (double count)"
            else:
                k = "neither labelled"
            if (la | lb) & dup:
                k += " [a label the scorer drops as duplicate]"
            tot[k] += 1
            print(f"  {clip['clip_id']:14} t{p['a']} + t{p['b']}  IoU {p['iou']:.2f} touch {p['touch']:.0%} "
                  f"box {p['w']:.0f}px dist {p['dist_w']:.2f}w  labels {sorted(la)} / {sorted(lb)}  -> {k}")
    for k, n in sorted(tot.items()):
        print(f"  {n:3}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
