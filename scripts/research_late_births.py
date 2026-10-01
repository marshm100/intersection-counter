"""Step 2 (2026-10-01): does the tracker see each labelled vehicle's ENTRY?

For every labelled vehicle on the development clips, the track the scorer assigns to its entry
click (journey_eval._assign_clicks) is compared with the click: was the track already alive
when the back tyre crossed in (SEEN), or born after it (LATE), and by how much. For LATE ones,
and for vehicles with no entry track at all, the detection cache under the entry click tells why:
  NONE   no box at all (the detector)
  WEAK   only boxes below the birth bar (conf < BIRTH_CONF; the weak-birth lever)
  CONF   a confident box the tracker did not turn into a track in time
Usage: .venv\Scripts\python.exe -X utf8 scripts/research_late_births.py STEM[:prefixes]
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

BIRTH_CONF = 0.35       # activation 0.25 + 0.1: the recovery tracker's birth bar
PAD = 1 + 2 * je.BOX_PAD


def main() -> int:
    stem, prefixes = ej.parse(sys.argv[1])
    con = sqlite3.connect(f"file:data/projects/{ej.PROJ}/project.db?mode=ro", uri=True)
    tally = Counter()
    lags = []
    for clip in list_clips(ej.PROJ):
        cid = clip["clip_id"]
        if ej.is_heldout(cid):
            continue
        labels = list_labels(ej.PROJ, cid)
        if not labels:
            continue
        cam = clip["camera_id"]
        window = "study_" + cid.split("_")[1]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        _, rows = ej.locate(stem.split("|")[0], prefixes, cam, window, chash)
        f_lo, f_hi = clip["start_frame"], clip["end_frame"]
        byf = je.index_rows(rows, f_lo - je.SEARCH_FRAMES, f_hi + je.SEARCH_FRAMES)
        dups = je.duplicate_labels(labels, fps, byf)
        labels = [lb for lb in labels if lb["label_id"] not in dups
                  and lb.get("entry_frame") is not None and lb.get("exit_frame") is not None]
        entry_of, _ = je._assign_clicks(labels, rows, byf, fps)
        first, _ = je._ends(rows[np.isin(rows[:, 0], list(entry_of.values()))])
        det = pd.read_parquet(parquet_path(ej.PROJ, cam, chash, window))
        det = det[(det.frame_idx >= f_lo - 5) & (det.frame_idx <= f_hi + 5)]
        dby = {f: g for f, g in det.groupby("frame_idx")}
        for lb in labels:
            t = entry_of.get(lb["label_id"])
            born = float(first[t][1]) if t is not None and t in first else None
            lag_s = None if born is None else (born - lb["entry_frame"]) / fps
            if born is not None and lag_s <= 0:
                tally[(cam, "SEEN")] += 1
                continue
            confs = []
            for d in range(-2, 3):
                g = dby.get(int(lb["entry_frame"]) + d)
                if g is None:
                    continue
                cx, cy = (g.bbox_x1 + g.bbox_x2) / 2, (g.bbox_y1 + g.bbox_y2) / 2
                w, h = g.bbox_x2 - g.bbox_x1, g.bbox_y2 - g.bbox_y1
                m = ((np.abs(lb["entry_x"] - cx) <= w / 2 * PAD)
                     & (np.abs(lb["entry_y"] - cy) <= h / 2 * PAD))
                confs += g.confidence.values[m].tolist()
            why = ("NONE" if not confs else "WEAK" if max(confs) < BIRTH_CONF else "CONF")
            kind = ("LATE" if born is not None else "NO ENTRY TRACK") + " / " + why
            tally[(cam, kind)] += 1
            if lag_s is not None:
                lags.append(lag_s)
    print(f"{stem}: entries on the development clips")
    for (cam, kind), n in sorted(tally.items()):
        print(f"  cam{cam}  {kind:24} {n}")
    tot = Counter(k for (_, k) in tally.elements())
    print("  ALL   " + ", ".join(f"{k} {n}" for k, n in sorted(tot.items())))
    if lags:
        print(f"  late by: median {np.median(lags):.2f} s, 90th pct {np.percentile(lags, 90):.2f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
