"""SHORT-LIVED COUNTED TRACKS (2026-10-15, double-counting dive). 12 of the 52 phantoms on the
labelled clips live under ~25 dump rows - too short to have WITNESSED a journey through the box.
For each life threshold: on the labelled clips, how many counted events below it are a labelled
car's ONLY count (a real car the rule would lose: correct or wrong-but-counted), how many are a
labelled car's second count (double), how many phantoms; and fleet-wide how many counted events
fall below it, by decision path.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_short_life.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from backend.services.mouth_from_motion import _load  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402
from research_near_twins import WINDOWS  # noqa: E402

THRESH = (8, 12, 16, 20, 25, 30, 40)


def lives(rows, tids):
    sel = rows[np.isin(rows[:, 0], list(tids))]
    u, n = np.unique(sel[:, 0], return_counts=True)
    return dict(zip(u.astype(int), n.astype(int)))


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    lab = defaultdict(Counter)              # thresh -> kind -> n
    for clip in list_clips(PROJ):
        labels = list_labels(PROJ, clip["clip_id"])
        if not labels:
            continue
        cam = clip["camera_id"]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        db, rows = locate(stem, {}, cam, "study_" + clip["clip_id"].split("_")[1], chash)
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        events = [dict(zip(("vehicle_track_id", "origin_leg_id", "destination_leg_id", "start_frame"), r))
                  for r in d.execute("SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
                                     "COALESCE(start_frame, frame_number) FROM vehicle_events "
                                     "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,))]
        d.close()
        r = je.score_clip(labels, rows, events, clip, fps=float(fps))
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        byf = je.index_rows(rows, f_lo - je.SEARCH_FRAMES, f_hi + je.SEARCH_FRAMES)
        dups = je.duplicate_labels(labels, float(fps), byf)
        ein, eout = je._assign_clicks([lb for lb in labels if lb["label_id"] not in dups], rows, byf, float(fps))
        owner = {}
        for side in (eout, ein):
            for lid, t in side.items():
                owner[t] = lid
        out = {v["label_id"]: v for v in r["per_vehicle"]}
        inclip = [e for e in events if f_lo <= int(e["start_frame"] or -1) <= f_hi]
        lf = lives(rows, {int(e["vehicle_track_id"]) for e in inclip})
        for e in inclip:
            t = int(e["vehicle_track_id"])
            L = lf.get(t, 0)
            lid = owner.get(t)
            v = out.get(lid)
            if lid is None:
                k = "phantom"
            elif v is None:
                k = "label not a full journey"
            elif v["outcome"] == "double":
                k = "double (one of two)"
            else:
                k = f"only count ({v['outcome']})"
            for th in THRESH:
                if L < th:
                    lab[th][k] += 1
            if L < 25 and k.startswith("only"):
                print(f"  REAL CAR on a short track: {clip['clip_id']} t{t} life {L} label {lid} {v['outcome']}")
    print("\nLABELLED CLIPS (dev + held-out): counted events whose track lives < N dump rows")
    for th in THRESH:
        print(f"  < {th:3}: " + "  ".join(f"{k} {n}" for k, n in sorted(lab[th].items())))
    print("\nFLEET: counted events whose track lives < N rows, by decision path")
    for cam, w in WINDOWS:
        chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
        db, rows = locate(stem, {}, cam, w, chash)
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        evs = _load(d, cam)
        d.close()
        lf = lives(rows, {e["tid"] for e in evs})
        line = []
        for th in (12, 25):
            c = Counter(e["tag"] for e in evs if lf.get(e["tid"], 0) < th)
            line.append(f"<{th}: {sum(c.values()):4} {dict(c.most_common(3))}")
        print(f"  cam{cam} {w}: of {len(evs):5}  " + "   ".join(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
