"""Score tracking arms against the operator's journey labels (2026-09-30,
docs/research_tracking_2026-09-29.md phase 0b). Minutes, not a fleet arm.

For each labelled clip, the arm's working DB (counted events) and the dump it
replayed (the tracks) are located by stem and dump prefix, and every labelled
vehicle is given one outcome (backend/services/journey_eval.py).

Usage:
  .venv\\Scripts\\python.exe -X utf8 scripts/eval_journeys.py STEM[:PREFIXES] [STEM2[:PREFIXES2]]
    STEM      the arm's DB stem, e.g. rt0 or gx2; "rt0|gx2" = the first that has
              the window (the true default control: rt0 for cams 1-3, gx2 for 4-5)
    PREFIXES  dump prefixes per camera, e.g. 1=rt_,2=rt_,3=rt_ (default: none; cams
              4 / 5 fall back to the vl3_ names the gx2 arm used)
  e.g.  eval_journeys.py rt0:1=rt_,2=rt_,3=rt_
        eval_journeys.py rt0:1=rt_,2=rt_,3=rt_ lk1:1=rt_,2=rt_,3=rt_     (paired comparison)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.journey_eval import mcnemar, score_clip  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")


def parse(spec: str):
    stem, _, pre = spec.partition(":")
    prefixes = {}
    for part in filter(None, pre.split(",")):
        c, _, p = part.partition("=")
        prefixes[int(c)] = p
    return stem, prefixes


def locate(stem: str, prefixes: dict, cam: int, window: str, chash: str):
    """(working DB, dump rows) for this arm, camera and window. The dump is
    the one whose track ids cover the arm's counted events: a linker arm
    replayed the lk_ dump (linked ids), every other arm the plain one."""
    for pre in ([prefixes[cam]] if cam in prefixes else ["", "vl3_"]):
        db = BASE / f"{stem}_cam{cam}_{pre}{window}.db"
        if not db.exists():
            continue
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        ev_tids = {int(t) for (t,) in d.execute(
            "SELECT DISTINCT vehicle_track_id FROM vehicle_events WHERE camera_id=? "
            "AND COALESCE(rejected,0)=0", (cam,))}
        d.close()
        base = f"{pre}{window}" if pre != "vl3_" else window
        best, best_cov = None, -1.0
        for v in (f"lk_{base}", base, f"{pre}{window}"):
            td = tracks_dir(parquet_path(PROJ, cam, chash, v))
            if not (td / "count.txt").exists():
                continue
            rows = np.asarray(load_dump(td))
            cov = (len(ev_tids & set(np.unique(rows[:, 0]).astype(int).tolist()))
                   / max(len(ev_tids), 1))
            if cov > best_cov:
                best, best_cov = rows, cov
        if best is not None:
            return db, best
    return None, None


def run_arm(stem: str, prefixes: dict) -> dict:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    results = {}
    for clip in list_clips(PROJ):
        labels = list_labels(PROJ, clip["clip_id"])
        if not labels:
            continue
        cam = clip["camera_id"]
        window = "study_" + clip["clip_id"].split("_")[1]
        chash, = con.execute("SELECT content_hash FROM videos WHERE video_id=?",
                             (clip["video_id"],)).fetchone()
        db = rows = None
        for st in stem.split("|"):           # "rt0|gx2": first arm that has this window
            db, rows = locate(st, prefixes, cam, window, chash)
            if db is not None:
                break
        if db is None:
            print(f"  {clip['clip_id']}: no {stem} DB/dump found, skipped")
            continue
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        events = [dict(zip(("vehicle_track_id", "origin_leg_id", "destination_leg_id",
                            "start_frame"), r)) for r in d.execute(
            "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
            "COALESCE(start_frame, frame_number) FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,))]
        results[clip["clip_id"]] = score_clip(labels, rows, events, clip)
    return results


def report(stem: str, res: dict) -> None:
    print(f"\n=== {stem} ===")
    tot = {"n": 0, "correct": 0, "broken": 0, "phantoms": 0}
    for cid, r in res.items():
        o = r["outcomes"]
        print(f"  {cid:14} vehicles {r['n_full']:4}  correct {o.get('correct', 0):4}"
              f" ({100 * (r['correct_rate'] or 0):5.1f}%)  wrong {o.get('wrong', 0):3}"
              f"  double {o.get('double', 0):3}  missed {o.get('missed', 0):3}"
              f"  no_track {o.get('no_track', 0):3}  | broken {r['broken']:3}"
              f"  phantoms {r['phantoms']:3}")
        tot["n"] += r["n_full"]
        tot["correct"] += o.get("correct", 0)
        tot["broken"] += r["broken"]
        tot["phantoms"] += r["phantoms"]
        worst = sorted(r["cells"].items(), key=lambda kv: -abs(kv[1]["ours"] - kv[1]["truth"]))[:3]
        print("      biggest cell errors (legs origin->dest: truth / ours): "
              + "; ".join(f"{k}: {v['truth']}/{v['ours']}" for k, v in worst))
    if tot["n"]:
        print(f"  ALL           vehicles {tot['n']:4}  correct {tot['correct']:4}"
              f" ({100 * tot['correct'] / tot['n']:5.1f}%)  broken {tot['broken']}"
              f"  phantoms {tot['phantoms']}")


def main() -> int:
    specs = [parse(s) for s in sys.argv[1:]] or [("rt0|gx2", {1: "rt_", 2: "rt_", 3: "rt_"})]
    arms = []
    for stem, pre in specs:
        res = run_arm(stem, pre)
        report(stem, res)
        arms.append((stem, res))
    if len(arms) == 2:
        (sa, ra), (sb, rb) = arms
        print(f"\n=== paired: {sa} vs {sb} ===")
        for cid in sorted(ra.keys() & rb.keys()):
            m = mcnemar(ra[cid], rb[cid])
            print(f"  {cid:14} {m['vehicles']} vehicles; only {sa} right {m['a_only_correct']},"
                  f" only {sb} right {m['b_only_correct']}, p = {m['p_value']:.3f}")
        allm = mcnemar({"per_vehicle": [v for r in ra.values() for v in r["per_vehicle"]]},
                       {"per_vehicle": [v for r in rb.values() for v in r["per_vehicle"]]})
        print(f"  ALL            {allm['vehicles']} vehicles; only {sa} right "
              f"{allm['a_only_correct']}, only {sb} right {allm['b_only_correct']}, "
              f"p = {allm['p_value']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
