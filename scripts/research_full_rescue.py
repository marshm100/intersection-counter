"""Dry run (2026-09-25): would THE PATH-MATCH RESCUE keep the right dropped journeys?

A track witnessed entering one gate and exiting another ('full') that the
classifier drops as insufficient_data (the perspective u-turn branch) is
tested against the bank path of ITS OWN gate cell with the joint scorer's
frozen admission (score_path_joint, config JOINT_SCORER_*, per-camera cost
metric). Admitted -> it would count at the path's label. The same test on
a sample of COUNTED full journeys of the same cells is the control: an
admission rule that refuses the journeys we already count is broken.

Reads the gx2 arm DBs (== production), the pass-2 banks and the dumps. No
pass 2. Prices the admitted add-back against Miovision on all 12 windows
(events added AFTER the dedup passes, so an arm is still the honest price).

Usage: .venv\\Scripts\\python.exe -X utf8 scripts/research_full_rescue.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend.config as C  # noqa: E402
import v2_score_dev as V  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.rule595 import score_cells  # noqa: E402
from backend.services.trajectory_classifier import score_path_joint  # noqa: E402

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"),
           (2, "study_1100"), (2, "study_1600"), (3, "study_0600"),
           (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
           (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]
CONTROL_PER_CELL = 200


def tag(cam: int, variant: str) -> str:
    return f"vl3_{variant}" if cam in (4, 5) else variant


def admitted(traj, cell_paths, metric):
    if not cell_paths or len(traj) < 4:
        return None
    j = score_path_joint(
        traj, cell_paths, max_cost=C.JOINT_SCORER_MAX_COST_PX,
        min_coverage_frac=C.JOINT_SCORER_MIN_COVERAGE_FRAC,
        tail_window=C.JOINT_SCORER_TAIL_WINDOW,
        tail_weight=C.JOINT_SCORER_TAIL_WEIGHT,
        coverage_weight=C.JOINT_SCORER_COVERAGE_WEIGHT, cost_metric=metric,
        turn_tail_prior_floor=C.JOINT_SCORER_TURN_TAIL_PRIOR_FLOOR,
        turn_min_coverage=C.JOINT_SCORER_TURN_MIN_COVERAGE)
    return j["movement_label"] if j.get("destination_leg_id") is not None else None


def appr(pm):
    o = defaultdict(lambda: defaultdict(int))
    for m, c in pm.items():
        for k, v in c.items():
            o[m][k[0]] += v
    return o


def pct(rows):
    return 100 * sum(x["ok"] for x in rows) / len(rows)


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    metric_by_cam = dict(con.execute("SELECT camera_id, calib_cost_metric FROM cameras"))
    site = V.SITES[V.CORRIDOR]
    tot = defaultdict(float)
    per_cam = defaultdict(lambda: defaultdict(float))
    for cam, variant in WINDOWS:
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?",
                                 (cam,)).fetchone()
        fps = float(fps)
        legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
                                (cam,)))
        metric = metric_by_cam.get(cam) or C.JOINT_SCORER_COST_METRIC
        bank = json.loads((BASE / "arm" / f"twopass_bank_cam{cam}_{tag(cam, variant)}.json").read_text())
        paths = bank["paths"] if isinstance(bank, dict) else bank
        by_cell = defaultdict(list)
        for p in paths:
            by_cell[(p["origin_leg_id"], p["destination_leg_id"])].append(p)
        rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
        order = np.argsort(rows[:, 0], kind="stable")
        rs, tids = rows[order], rows[order][:, 0]

        def traj(tid):
            lo, hi = np.searchsorted(tids, tid, "left"), np.searchsorted(tids, tid, "right")
            sel = rs[lo:hi]
            sel = sel[np.argsort(sel[:, 1])]
            return [(float(r[2]), float(r[3])) for r in sel]

        db = BASE / f"gx2_cam{cam}_{tag(cam, variant)}.db"
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        off = {}
        for vid, sf, ts in d.execute(
                "SELECT video_id, start_frame, timestamp_real FROM vehicle_events WHERE camera_id=? "
                "AND start_frame IS NOT NULL AND timestamp_real IS NOT NULL", (cam,)):
            if vid not in off or sf < off[vid][0]:
                off[vid] = (sf, datetime.fromisoformat(ts))
        fates = d.execute(
            "SELECT video_id, vehicle_track_id, disposition, reason, gate_origin_leg_id, "
            "gate_dest_leg_id, start_frame FROM track_fates WHERE gate_tag='full'").fetchall()
        drops = [f for f in fates if f[3] == "classifier_insufficient" and f[4] != f[5]]
        verdict = defaultdict(Counter)
        add = []
        for vid, tid, _d, _r, o, de, sf in drops:
            lab = admitted(traj(tid), by_cell.get((o, de), []), metric)
            cell = f"{legs.get(o)}->{legs.get(de)}"
            verdict[cell]["admitted" if lab else ("no_path" if not by_cell.get((o, de)) else "refused")] += 1
            if lab and vid in off:
                f0, t0 = off[vid]
                add.append({"origin_leg": o, "movement": lab,
                            "wallclock": (t0 + timedelta(seconds=(sf - f0) / fps)).isoformat()})
        # control: counted full journeys of the same cells
        ctrl = Counter()
        cells = {(f[4], f[5]) for f in drops}
        seen = Counter()
        for vid, tid, disp, _r, o, de, _sf in fates:
            if disp != "counted" or (o, de) not in cells or seen[(o, de)] >= CONTROL_PER_CELL:
                continue
            seen[(o, de)] += 1
            ctrl["admitted" if admitted(traj(tid), by_cell.get((o, de), []), metric) else "refused"] += 1
        lo, hi = site["windows"][variant]
        mio = V.load_miovision(cam, site)
        mm = [m for m in (dtime(h, x) for h in range(lo, hi) for x in range(60)) if m in mio]
        ld = V.leg_dir_for(V.CORRIDOR, cam, site)
        base_ev = V.events_from_db(str(db), cam, site)
        res = {}
        for k, extra in (("base", []), ("rescue", add)):
            pm = V.per_min_from_events(base_ev + extra, ld)
            res[k] = (pct(score_cells(pm, mio, mm)), pct(score_cells(appr(pm), appr(mio), mm)))
            tot[k + "_m"] += res[k][0]
            tot[k + "_a"] += res[k][1]
            per_cam[cam][k + "_m"] += res[k][0]
            per_cam[cam][k + "_a"] += res[k][1]
        per_cam[cam]["n"] += 1
        top = sorted(verdict.items(), key=lambda kv: -sum(kv[1].values()))[:4]
        print(f"cam{cam} {variant}: dropped full {len(drops)}, rescued {len(add)} "
              f"{dict(Counter(e['movement'] for e in add))} | control (counted) {dict(ctrl)}")
        print(f"   by cell: " + "; ".join(f"{c} {dict(v)}" for c, v in top))
        print(f"   movement {res['base'][0]:.1f} -> {res['rescue'][0]:.1f}   "
              f"approach {res['base'][1]:.1f} -> {res['rescue'][1]:.1f}", flush=True)
    print(f"\nFLEET movement {tot['base_m'] / 12:.2f} -> {tot['rescue_m'] / 12:.2f} "
          f"({(tot['rescue_m'] - tot['base_m']) / 12:+.2f})   approach {tot['base_a'] / 12:.2f} -> "
          f"{tot['rescue_a'] / 12:.2f} ({(tot['rescue_a'] - tot['base_a']) / 12:+.2f})")
    for cam, v in sorted(per_cam.items()):
        n = v["n"]
        print(f"  cam{cam}: movement {(v['rescue_m'] - v['base_m']) / n:+.2f}  "
              f"approach {(v['rescue_a'] - v['base_a']) / n:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
