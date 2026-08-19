"""CLI auto-calibration runner (MASTER_ACCURACY_ROADMAP monitoring law:
long auto-cal runs belong in their own process, NOT the dev server —
the server's GIL starves its API for the whole run and its reloader/
stale-module traps owned every failure of 2026-08-18/19).

Runs scripts/auto_calibrate.run() directly with trajectory persistence
and heartbeat progress lines (parse-friendly: "HEARTBEAT <pct> <fps>
<trajs>"), then writes the suggestion to calibration_suggestions
exactly like the server job would.

Usage:
  py -X utf8 scripts/run_autocal_cli.py --camera 2 --start-hms 17:00 \
      --duration-min 60 [--project 97a7849a]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from backend.database import save_calibration_suggestion        # noqa: E402
from backend.services import auto_calibrator_v2 as acal         # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--start-hms", default=None)
    ap.add_argument("--duration-min", type=float, default=None)
    args = ap.parse_args()

    win = acal.resolve_sample_window(
        args.project, args.camera,
        start_hms=args.start_hms, duration_min=args.duration_min)
    path, vid = acal._resolve_video_path(args.project, args.camera,
                                         win["video_id"])
    s, e = win["sample_start_sec"], win["sample_end_sec"]
    print(f"WINDOW {win['start_clock']}-{win['end_clock']} "
          f"video={vid} sample=[{s},{e}]", flush=True)

    traj_dir = Path(f"data/projects/{args.project}/_replay_scratch/autocal")
    traj_dir.mkdir(parents=True, exist_ok=True)
    traj_npz = traj_dir / f"traj_cam{args.camera}_{int(s)}_{int(e)}.npz"

    from auto_calibrate import run as run_auto_cal              # noqa: E402

    t0 = time.time()
    last = [0.0]

    def _cb(info):
        now = time.time()
        if now - last[0] >= 30.0:
            last[0] = now
            done = info.get("frame_no", 0) - info.get("start_frame", 0)
            total = max(1, info.get("end_frame", 1)
                        - info.get("start_frame", 0))
            rate = done / max(1.0, now - t0)
            print(f"HEARTBEAT {100.0 * done / total:.1f} {rate:.1f} "
                  f"{info.get('finished', 0)}", flush=True)

    result = run_auto_cal(
        path, sample_start_sec=s, sample_end_sec=e,
        on_progress=_cb, save_trajectories_to=str(traj_npz))

    result.pop("video_path", None)
    meta = {"video_id": vid, "video_path": path,
            "sample_window_sec": [s, e],
            "stats": result.get("stats", {}), "source": "cli"}
    save_calibration_suggestion(args.project, args.camera, result,
                                job_metadata=meta)
    print(f"DONE legs={len(result.get('leg_zones', []))} "
          f"paths={len(result.get('paths', []))} "
          f"wall={time.time() - t0:.0f}s npz={traj_npz}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
