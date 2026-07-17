"""Backfill intersection_paths.expected_speed = median px-step of each path's
SUPPORTING TRACKS (the speed-tiebreak signature). Blind — computed from the
camera's own stored tracks, no ground truth. Run after a bank build / reprocess
so stored vehicle_events exist; the shared-exit collinear speed-tiebreak stays
inert until a path carries this value AND the camera opts in via
calib_speed_tiebreak=1. See memory project_per_approach_attribution_2026_06_30.

STOP the app server first (it holds project.db's WAL). Dry-run by default;
--apply writes.

Usage:
  py scripts/backfill_expected_speed.py --camera 2            # dry-run (prints)
  py scripts/backfill_expected_speed.py --camera 2 --apply    # persist
  py scripts/backfill_expected_speed.py --all --apply         # every camera
"""
from __future__ import annotations
import argparse, json, math, sqlite3
from collections import defaultdict
from statistics import median


def _track_median_step(tj: str):
    pts = json.loads(tj)
    if len(pts) < 4:
        return None
    s = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
         for i in range(len(pts) - 1)]
    return median(s) if len(s) >= 3 else None


def backfill(db: str, camera: int, apply: bool) -> None:
    conn = sqlite3.connect(db)
    spd: dict = defaultdict(list)
    for olid, dlid, tj in conn.execute(
            "SELECT origin_leg_id, destination_leg_id, trajectory_data FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0", (camera,)):
        if not tj:
            continue
        m = _track_median_step(tj)
        if m is not None:
            spd[(olid, dlid)].append(m)
    paths = conn.execute(
        "SELECT path_id, origin_leg_id, destination_leg_id, expected_speed "
        "FROM intersection_paths WHERE camera_id=? ORDER BY origin_leg_id, destination_leg_id",
        (camera,)).fetchall()
    print(f"cam{camera}: {len(paths)} paths")
    n_set = 0
    for pid, o, d, cur in paths:
        vals = spd.get((o, d))
        newv = round(median(vals), 3) if vals else None
        n = len(vals) if vals else 0
        print(f"  path {pid} ({o}->{d}): n={n:>5}  expected_speed {cur} -> {newv}")
        if apply and newv is not None:
            conn.execute("UPDATE intersection_paths SET expected_speed=? WHERE path_id=?",
                         (newv, pid))
            n_set += 1
    if apply:
        conn.commit()
        print(f"cam{camera}: wrote expected_speed on {n_set} paths")
    else:
        print(f"cam{camera}: DRY-RUN (no writes) -- pass --apply to persist")
    conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    db = f"data/projects/{args.project}/project.db"
    if args.all:
        conn = sqlite3.connect(db)
        cams = [r[0] for r in conn.execute(
            "SELECT DISTINCT camera_id FROM intersection_paths ORDER BY camera_id")]
        conn.close()
    elif args.camera is not None:
        cams = [args.camera]
    else:
        ap.error("pass --camera N or --all")
    for c in cams:
        backfill(db, c, args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
