"""Dry run (2026-09-26): how many counted events come through the FALLBACK side door?

A track that crossed NO gate ('no_crossing') and that the joint shape scorer
refuses is still given a destination by score_destination_by_polyline (nearest
applied path line) or, failing that, the softmax scorer. On cam5 that is where
the far-field NB-left stubs get "left": the applied left path starts ~28 px
further upstream than the through path.

For every counted, unrejected no_crossing event in the basis arm DBs (gx2 ==
production) this replays score_path_joint against the APPLIED paths
(list_paths_for_camera, what pass 2 uses) with the config admission and the
camera's cost metric. Refused -> the fallback labelled it. Then it prices
removing exactly those events against Miovision on all 12 windows.
Approximation: the pipeline's origin-rewrite veto can also null a joint pick;
the arm is the honest price.

Usage: .venv\\Scripts\\python.exe -X utf8 scripts/research_nocross_fallback.py [STEM]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend.config as C  # noqa: E402
import v2_score_dev as V  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.rule595 import score_cells  # noqa: E402
from backend.services.trajectory_classifier import score_path_joint  # noqa: E402

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"),
           (2, "study_1100"), (2, "study_1600"), (3, "study_0600"),
           (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
           (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]


def appr(pm):
    o = defaultdict(lambda: defaultdict(int))
    for m, c in pm.items():
        for k, v in c.items():
            o[m][k[0]] += v
    return o


def pct(rows):
    return 100 * sum(x["ok"] for x in rows) / len(rows)


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "gx2"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    metric_by_cam = dict(con.execute("SELECT camera_id, calib_cost_metric FROM cameras"))
    site = V.SITES[V.CORRIDOR]
    tot = defaultdict(float)
    per_cam = defaultdict(lambda: defaultdict(float))
    for cam, variant in WINDOWS:
        legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
                                (cam,)))
        paths = list_paths_for_camera(PROJ, cam)
        metric = metric_by_cam.get(cam) or C.JOINT_SCORER_COST_METRIC
        tag = f"vl3_{variant}" if cam in (4, 5) else variant
        db = BASE / f"{stem}_cam{cam}_{tag}.db"
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        nocross = {(v, t) for v, t in d.execute(
            "SELECT video_id, vehicle_track_id FROM track_fates "
            "WHERE gate_tag='no_crossing' AND disposition='counted'")}
        side = set()
        cells = Counter()
        n_nc = 0
        for eid, vid, tid, o, mv, tj in d.execute(
                "SELECT event_id, video_id, vehicle_track_id, origin_leg_id, movement, "
                "trajectory_data FROM vehicle_events WHERE camera_id=? AND "
                "COALESCE(rejected,0)=0 AND posterior_source IS NULL", (cam,)):
            if (vid, tid) not in nocross:
                continue
            n_nc += 1
            j = score_path_joint(
                json.loads(tj), paths, max_cost=C.JOINT_SCORER_MAX_COST_PX,
                min_coverage_frac=C.JOINT_SCORER_MIN_COVERAGE_FRAC,
                tail_window=C.JOINT_SCORER_TAIL_WINDOW,
                tail_weight=C.JOINT_SCORER_TAIL_WEIGHT,
                coverage_weight=C.JOINT_SCORER_COVERAGE_WEIGHT, cost_metric=metric,
                turn_tail_prior_floor=C.JOINT_SCORER_TURN_TAIL_PRIOR_FLOOR,
                turn_min_coverage=C.JOINT_SCORER_TURN_MIN_COVERAGE)
            if j.get("destination_leg_id") is None:
                side.add(eid)
                cells[f"{legs.get(o)} {mv}"] += 1
        lo, hi = site["windows"][variant]
        mio = V.load_miovision(cam, site)
        mm = [m for m in (dtime(h, x) for h in range(lo, hi) for x in range(60)) if m in mio]
        ld = V.leg_dir_for(V.CORRIDOR, cam, site)
        base, kept = [], []
        for eid, o, mv, ts in d.execute(
                "SELECT event_id, origin_leg_id, movement, timestamp_real FROM vehicle_events "
                "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,)):
            if ts is None:
                continue
            ev = {"origin_leg": o, "movement": mv, "wallclock": ts}
            base.append(ev)
            if eid not in side:
                kept.append(ev)
        res = {}
        for k, evs in (("base", base), ("rule", kept)):
            pm = V.per_min_from_events(evs, ld)
            res[k] = (pct(score_cells(pm, mio, mm)), pct(score_cells(appr(pm), appr(mio), mm)))
            tot[k + "_m"] += res[k][0]
            tot[k + "_a"] += res[k][1]
            per_cam[cam][k + "_m"] += res[k][0]
            per_cam[cam][k + "_a"] += res[k][1]
        per_cam[cam]["n"] += 1
        print(f"cam{cam} {variant}: counted no_crossing {n_nc}, via the fallback {len(side)} "
              f"| top {cells.most_common(4)}")
        print(f"   movement {res['base'][0]:.1f} -> {res['rule'][0]:.1f}   "
              f"approach {res['base'][1]:.1f} -> {res['rule'][1]:.1f}", flush=True)
    print(f"\nFLEET movement {tot['base_m'] / 12:.2f} -> {tot['rule_m'] / 12:.2f} "
          f"({(tot['rule_m'] - tot['base_m']) / 12:+.2f})   approach {tot['base_a'] / 12:.2f} -> "
          f"{tot['rule_a'] / 12:.2f} ({(tot['rule_a'] - tot['base_a']) / 12:+.2f})")
    for cam, v in sorted(per_cam.items()):
        n = v["n"]
        print(f"  cam{cam}: movement {(v['rule_m'] - v['base_m']) / n:+.2f}  "
              f"approach {(v['rule_a'] - v['base_a']) / n:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
