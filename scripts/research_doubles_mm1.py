"""THE LABELLED DOUBLES UNDER THE DEFAULT (2026-10-15, double-counting dive). Every labelled car the
scorer calls "double" (two counted events owned by it): its counted tracks, their decision paths,
(origin, dest), lives, and how they relate in time - SEQUENTIAL (one dies before the other is
born: a broken track the linker did not join; gap in frames) or CONCURRENT (both alive at once:
two tracks on one car; overlap share of the shorter life, touch share, centre distance in widths).
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_doubles_mm1.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from backend.services.mouth_from_motion import _load  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402
from research_phantoms_mm1 import touch  # noqa: E402


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
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
        tag = {e["tid"]: e["tag"] for e in _load(d, cam)}
        d.close()
        od = {int(e["vehicle_track_id"]): (e["origin_leg_id"], e["destination_leg_id"]) for e in events}
        r = je.score_clip(labels, rows, events, clip, fps=float(fps))
        for v in r["per_vehicle"]:
            if v["outcome"] != "double":
                continue
            ts = [t for t in v["tracks"] if t in od]
            tr = {t: rows[rows[:, 0] == t] for t in ts}
            ts.sort(key=lambda t: tr[t][0, 1])
            desc = "  ".join(f"t{t} {tag.get(t)} {od[t][0]}->{od[t][1]} f{int(tr[t][0, 1])}-{int(tr[t][-1, 1])} "
                             f"w{np.median(tr[t][:, 4]):.0f}" for t in ts)
            rel = ""
            if len(ts) == 2:
                a, b = tr[ts[0]], tr[ts[1]]
                if b[0, 1] > a[-1, 1]:
                    gap = int(b[0, 1] - a[-1, 1])
                    dd = np.hypot(*(b[0, 2:4] - a[-1, 2:4])) / max(a[-1, 4], 1)
                    rel = f"SEQUENTIAL gap {gap}f jump {dd:.2f}w"
                else:
                    ov = min(a[-1, 1], b[-1, 1]) - b[0, 1]
                    sh = min(a[-1, 1] - a[0, 1], b[-1, 1] - b[0, 1])
                    t, dist, n = touch(a, b)
                    rel = f"CONCURRENT overlap {ov / max(sh, 1):.2f} touch {t:.2f} dist {dist:.2f}w"
            print(f"{clip['clip_id']:14} label {v['label_id']:4} truth {v['truth'][0]}->{v['truth'][1]}  {desc}  | {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
