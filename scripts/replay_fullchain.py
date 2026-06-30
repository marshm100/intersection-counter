"""Full-chain attribution replay — measure any bank/matcher change on the
acceptance metric in minutes, WITHOUT re-running detection or tracking.

Re-attributes every stored `vehicle_events.trajectory_data` through the REAL
production chain by driving the actual ProcessingPipeline:
  provisional origin (`_assign_origin`) -> `classify_trajectory` ->
  `score_path_joint` + origin-rewrite gate -> fallback
  (`score_destination_by_polyline` -> `score_destination_leg` + `derive_movement`).

The pipeline's lazy components mean no YOLO/tracker is loaded; we monkeypatch
`_write_vehicle_event` to CAPTURE the (origin, dest, movement) instead of a DB
write, and pair each result with the event's STORED timestamp so the per-15-min
acceptance metric (`interval_metric.py`) can be computed directly.

This is the per-approach-attribution campaign's measurement instrument: it
reproduces the LIVE per-approach numbers off the live bank (validate first),
then swap in a candidate bank (`--bank`) or inject paths (`--extra-paths`) to
read the per-approach delta cheaply. The only approximation is that
`_assign_origin` runs on the full stored trajectory rather than the live partial
prefix, which can drift the fallback population a point or two — verify the
live-bank run tracks `interval_metric.py` before trusting an A/B.

Usage:
  py scripts/replay_fullchain.py --camera 2                       # live bank (validate vs interval_metric)
  py scripts/replay_fullchain.py --camera 2 --bank evaluations/gtfree_bank_cam2.json
  py scripts/replay_fullchain.py --camera 2 --extra-paths sbleft.json
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.pipeline import ProcessingPipeline
from backend.database import list_paths_for_camera, get_camera_calibration_params
from reprocess_camera import _load_camera_context
import triangulate_manual as T
import interval_metric as IM

NORM = {"through": "thru", "u_turn": "uturn", "left": "left", "right": "right"}


def _paths_from_json(blob: dict | list) -> list[dict]:
    """Accept either a bank JSON ({'paths': [...]}) or a bare list of paths."""
    return blob["paths"] if isinstance(blob, dict) and "paths" in blob else blob


def replay(project: str, cam: int, bank: list[dict] | None = None,
           extra_paths: list[dict] | None = None):
    db = f"data/projects/{project}/project.db"
    conn = sqlite3.connect(db); ctx = _load_camera_context(conn, cam); conn.close()
    video = ctx["video"]
    leg_dir = {l["leg_id"]: T._CARD_TO_DIR.get((l.get("cardinal_direction") or "").strip().upper())
               for l in ctx["legs"]}
    paths = (list(bank) if bank is not None else list_paths_for_camera(project, cam))
    if extra_paths:
        paths = paths + list(extra_paths)
    calib = get_camera_calibration_params(project, cam)

    pipe = ProcessingPipeline(
        project_id=project, db_path=db, video_path=video["path"], legs=ctx["legs"],
        fps=float(video["fps"]), video_start_time=video["recording_start_datetime"],
        video_id=video["video_id"], calibration_params=calib, paths=paths,
        tracker_backend="botsort")
    pipe._v3_camera_id = cam
    pipe._v3_trim_id = None
    captured: dict = {}
    pipe._write_vehicle_event = lambda **kw: captured.__setitem__("last", kw)

    c = sqlite3.connect(db)
    rows = c.execute(
        "SELECT trajectory_data, timestamp_real, detection_confidence, start_frame, frame_number "
        "FROM vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,)).fetchall()
    c.close()

    per_min: dict = defaultdict(lambda: defaultdict(int))
    n_written = 0
    for tid, (tj, ts, dconf, sf, ef) in enumerate(rows):
        traj = [tuple(p) for p in json.loads(tj)] if tj else []
        if not traj:
            continue
        sf = sf if sf is not None else 0
        ef = ef if ef is not None else sf
        vehicle = {
            "origin_leg_id": None, "reference_heading": None, "origin_frame": None,
            "origin_attempt_failed": False, "start_frame": sf, "last_seen_frame": ef,
            "trajectory": traj, "confidences": [dconf or 0.5] * len(traj),
            "class_id": 2, "class_name": "car", "bbox_width": 30.0, "bbox_height": 30.0,
            "bbox_area": 900.0, "initial_bbox_ratio": 1.0}
        pipe.active_vehicles[tid] = vehicle
        captured.pop("last", None)
        try:
            pipe._assign_origin(tid, sf)
            pipe._finalize_vehicle_data(tid, vehicle, ef)
        except Exception as e:
            print(f"  (event {tid} errored: {e})", file=sys.stderr)
        pipe.active_vehicles.pop(tid, None)
        if "last" in captured and ts:
            kw = captured["last"]
            d = leg_dir.get(kw["origin_leg_id"])
            if d:
                key = datetime.fromisoformat(ts).time().replace(second=0, microsecond=0)
                per_min[key][(d, NORM.get(kw["movement"], kw["movement"]))] += 1
                n_written += 1
    return per_min, n_written, len(rows)


def report(cam: int, per_min: dict, label: str) -> dict:
    mio = T.load_miovision(cam)
    res = IM.per_interval(per_min, mio, by_approach=True)
    print(f"\n=== cam{cam} [{label}] full-chain replay vs Miovision ===")
    print(IM._fmt(res))
    for d, r in res["per_approach"].items():
        if r["n_bins"]:
            print(f"    {d:<3} AVG|err| {r['avg_abs_err_pct']:.1f}%  [{r['verdict']}]  "
                  f"max {r['max_abs_err_pct']:.1f}%@{r['worst_interval']}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--bank", default=None, help="bank JSON to use INSTEAD of the DB bank")
    ap.add_argument("--extra-paths", default=None,
                    help="JSON (bank or bare list) of paths to MERGE into the bank")
    ap.add_argument("--label", default=None)
    args = ap.parse_args()
    bank = _paths_from_json(json.loads(Path(args.bank).read_text())) if args.bank else None
    extra = _paths_from_json(json.loads(Path(args.extra_paths).read_text())) if args.extra_paths else None
    pm, nw, ntot = replay(args.project, args.camera, bank=bank, extra_paths=extra)
    print(f"replay wrote {nw}/{ntot} events")
    label = args.label or (Path(args.bank).stem if args.bank
                           else ("merged" if extra else "live-bank"))
    report(args.camera, pm, label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
