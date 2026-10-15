"""THE PHANTOMS UNDER THE DEFAULT (2026-10-15, double-counting dive). The scorer's "double"
(one labelled car owning two counted tracks) is 19 cars on the labelled clips; its "phantoms"
(counted events in the clip that no labelled car's click lands on) are 52 - the bigger channel.
Each phantom is described by its own track and its nearest CLAIMED counted track over its life:
  tag      decision path (track_fates.gate_tag)
  w        median box width;  life  frames
  near     the claimed track whose box it touches most (share of common frames with IoU > 0)
  touch / dist  that share, and median centre distance in box widths
  same     the phantom's (origin, dest) equals the neighbour's
  cover    share of the phantom's life the neighbour is alive
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_phantoms_mm1.py [STEM]
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
from backend.services.mouth_from_motion import _load  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402


def touch(a, b):
    com, ia, ib = np.intersect1d(a[:, 1], b[:, 1], return_indices=True)
    if len(com) < 3:
        return 0.0, 9.9, len(com)
    pa, pb = a[ia], b[ib]
    x1 = np.maximum(pa[:, 2] - pa[:, 4] / 2, pb[:, 2] - pb[:, 4] / 2)
    x2 = np.minimum(pa[:, 2] + pa[:, 4] / 2, pb[:, 2] + pb[:, 4] / 2)
    y1 = np.maximum(pa[:, 3] - pa[:, 5] / 2, pb[:, 3] - pb[:, 5] / 2)
    y2 = np.minimum(pa[:, 3] + pa[:, 5] / 2, pb[:, 3] + pb[:, 5] / 2)
    t = float(((x2 > x1) & (y2 > y1)).mean())
    d = float(np.median(np.hypot(pa[:, 2] - pb[:, 2], pa[:, 3] - pb[:, 3]) / np.maximum(pa[:, 4], 1)))
    return t, d, len(com)


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    kinds = Counter()
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
        lab = [lb for lb in labels if lb["label_id"] not in dups]
        ein, eout = je._assign_clicks(lab, rows, byf, fps)
        claimed = set(ein.values()) | set(eout.values())
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        tag = {e["tid"]: e["tag"] for e in _load(d, cam)}
        evs = d.execute("SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
                        "COALESCE(start_frame, frame_number) FROM vehicle_events "
                        "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,)).fetchall()
        d.close()
        od = {int(t): (o, de) for t, o, de, _ in evs}
        ph = [int(t) for t, o, de, sf in evs if f_lo <= int(sf or -1) <= f_hi and int(t) not in claimed]
        tids = set(ph) | {t for t in claimed if t in od}
        sel = rows[np.isin(rows[:, 0], list(tids))]
        sel = sel[np.lexsort((sel[:, 1], sel[:, 0]))]
        u, i0 = np.unique(sel[:, 0], return_index=True)
        tr = dict(zip(u.astype(int), np.split(sel, i0[1:])))
        for p in ph:
            if p not in tr:
                continue
            b = tr[p]
            best = (0.0, 9.9, 0, None)
            for c in claimed:
                if c not in tr or c not in od:
                    continue
                a = tr[c]
                if a[-1, 1] < b[0, 1] or a[0, 1] > b[-1, 1]:
                    continue
                t, dd, n = touch(a, b)
                if (t, -dd) > (best[0], -best[1]):
                    best = (t, dd, n, c)
            t, dd, n, c = best
            cover = n / max(len(b), 1)
            same = c is not None and od[c] == od[p]
            k = ("touching claimed" if t >= 0.5 else "near claimed" if c is not None and dd < 2 else "alone")
            kinds[(k, tag.get(p))] += 1
            print(f"{clip['clip_id']:14} t{p:<6} {tag.get(p) or '-':12} {od[p][0]}->{od[p][1]}  w {np.median(b[:, 4]):4.0f} "
                  f"life {len(b):4}  near t{c} {od.get(c, ('', ''))[0]}->{od.get(c, ('', ''))[1]} touch {t:.2f} "
                  f"dist {dd:.2f}w cover {cover:.2f} same {'Y' if same else '.'}  [{k}]")
    print()
    for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
