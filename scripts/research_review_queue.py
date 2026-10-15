"""THE REVIEW QUEUE - HOW BIG, AND DOES IT HOLD THE ERRORS? (2026-10-15, operator: "1" - engineer review of the
uncertain moments). Steps 9.114-9.116: where two cars overlap in the image, motion, appearance and box geometry
cannot tell one car from two in this video. The software CAN tell where that happens. A FLAG = two COUNTED tracks
meeting (centres within MEET_W box widths) where the outcome can change a count:
  - one of the two counted journeys is partial (not 'full': entry_only / exit_only / no_crossing ...), or
  - one of the two tracks is born or dies within EDGE_S seconds of the meeting.
Meetings of the same pair within MERGE_S are one flag. Label-free: everything here exists at runtime.
Measures:
  WORKLOAD  flags per hour, every one of the 12 windows (the shipped default's working DBs, stem mm1)
  RECALL    on the labelled clips: of the cars the labels score wrong / double / missed / no_track-and-uncounted,
            and of the phantoms, how many have a flag on one of their tracks inside their time in the box
            (labels are not used to make flags, only to score them)
  PRECISION share of the clips' flags that touch such an error
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_review_queue.py [STEM]
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
from backend.services.encounter_flags import EDGE_S, MEET_W, MERGE_S, encounter_flags  # noqa: E402,F401

REVIEW_S = 10          # assumed seconds an engineer spends on one flag


def flags(db: Path, rows: np.ndarray, cam: int, fps: float, f_lo=None, f_hi=None) -> list[dict]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tag = {e["tid"]: e["tag"] for e in _load(c, cam) if e["tid"] is not None and e["tid"] >= 0}
    c.close()
    return encounter_flags(tag, rows, fps, f_lo, f_hi)


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    print("WORKLOAD (every window, the shipped default)")
    tot_f = tot_h = 0.0
    for cam, w in WINDOWS:
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
        fps = float(fps)
        db, rows = locate(stem, {}, cam, w, chash)
        fl = flags(db, rows, cam, fps)
        hours = (rows[:, 1].max() - rows[:, 1].min()) / fps / 3600
        tot_f += len(fl)
        tot_h += hours
        why = Counter(x["why"] for x in fl)
        print(f"  cam{cam} {w}: {len(fl):6} flags in {hours:4.1f} h = {len(fl) / hours:5.0f} / h "
              f"(~{len(fl) / hours * REVIEW_S / 60:3.0f} min of review per hour of video at {REVIEW_S} s each)  {dict(why)}",
              flush=True)
    print(f"  ALL: {tot_f / tot_h:.0f} flags per hour of video")

    print("\nRECALL / PRECISION on the labelled clips")
    hit = Counter()
    allk = Counter()
    nflag = nflag_err = 0
    for clip in list_clips(PROJ):
        labels = list_labels(PROJ, clip["clip_id"])
        if not labels:
            continue
        cam = clip["camera_id"]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        fps = float(fps)
        db, rows = locate(stem, {}, cam, "study_" + clip["clip_id"].split("_")[1], chash)
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        events = [dict(zip(("vehicle_track_id", "origin_leg_id", "destination_leg_id", "start_frame"), r))
                  for r in d.execute("SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
                                     "COALESCE(start_frame, frame_number) FROM vehicle_events "
                                     "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,))]
        d.close()
        r = je.score_clip(labels, rows, events, clip, fps=fps)
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        fl = flags(db, rows, cam, fps, f_lo - int(5 * fps), f_hi + int(5 * fps))
        by_t = defaultdict(list)
        for x in fl:
            by_t[x["a"]].append(x)
            by_t[x["b"]].append(x)
        lab = {lb["label_id"]: lb for lb in labels}
        touched = set()
        pad = int(2 * fps)
        for v in r["per_vehicle"]:
            k = v["outcome"]
            if k == "correct":
                continue
            lb = lab[v["label_id"]]
            lo, hi = int(lb["entry_frame"]) - pad, int(lb["exit_frame"]) + pad
            # the car's own tracks, and the track it lost a click to (the tracks under its clicks)
            ts = set(v["tracks"])
            if k == "no_track":
                byf = je.index_rows(rows, lo, hi)
                for fr_, x, y in ((lb["entry_frame"], lb["entry_x"], lb["entry_y"]),
                                  (lb["exit_frame"], lb["exit_x"], lb["exit_y"])):
                    t = je.track_at(byf, int(fr_), x, y)
                    if t is not None:
                        ts.add(int(t))
            got = [x for t in ts for x in by_t.get(t, []) if lo <= x["f0"] <= hi or lo <= x["f1"] <= hi]
            allk[k] += 1
            if got:
                hit[k] += 1
                touched.update(id(x) for x in got)
        claimed = set()
        for v in r["per_vehicle"]:
            claimed.update(v["tracks"])
        for e in events:
            t = int(e["vehicle_track_id"])
            if f_lo <= int(e["start_frame"] or -1) <= f_hi and t not in claimed:
                allk["phantom"] += 1
                if by_t.get(t):
                    hit["phantom"] += 1
                    touched.update(id(x) for x in by_t[t])
        inclip = [x for x in fl if f_lo <= x["f0"] <= f_hi]
        nflag += len(inclip)
        nflag_err += sum(id(x) in touched for x in inclip)
        mins = (f_hi - f_lo) / fps / 60
        print(f"  {clip['clip_id']:14} {len(inclip):4} flags in {mins:.0f} min; errors flagged " +
              ", ".join(f"{k} {hit[k]}/{allk[k]}" for k in sorted(allk)), flush=True)
        hit_c, all_c = Counter(hit), Counter(allk)
        hit.clear(); allk.clear()
        for k in all_c:
            main.tot_all[k] = main.tot_all.get(k, 0) + all_c[k]
            main.tot_hit[k] = main.tot_hit.get(k, 0) + hit_c[k]
    print("  ALL: " + ", ".join(f"{k} {main.tot_hit.get(k, 0)}/{n}" for k, n in sorted(main.tot_all.items())))
    e_all, e_hit = sum(main.tot_all.values()), sum(main.tot_hit.values())
    print(f"  RECALL {e_hit}/{e_all} = {100 * e_hit / max(e_all, 1):.0f}% of the labelled count errors sit on a flag;"
          f"  PRECISION {nflag_err}/{nflag} = {100 * nflag_err / max(nflag, 1):.0f}% of the clips' flags touch one")
    return 0


main.tot_all = {}
main.tot_hit = {}

if __name__ == "__main__":
    raise SystemExit(main())
