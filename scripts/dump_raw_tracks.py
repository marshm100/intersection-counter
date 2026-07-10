"""PASS 1 of the two-pass architecture (MASTER_PLAN 2c): dump RAW tracks.

Thin CLI over backend.services.two_pass.run_pass1 (stage 3.3 — the core moved
into the backend so the ingest jobs and this CLI share ONE implementation:
live-parity tracking input, format-v2 rows, resume with recipe validation,
per-camera pass1_backend recipes incl. botsort+reid from the sidecar).

Usage:
  py scripts/dump_raw_tracks.py --camera 2 --variant study_0700      --start-hms 07:00:00 --minutes 120 [--backend botsort] [--resume]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import DEFAULT_VARIANT
from groundtruth import VIDEO_START


def tracks_path(pq: Path) -> Path:
    return pq.with_name(pq.stem + ".tracks")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=2)
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--variant", default=None)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=120.0)
    ap.add_argument("--backend", default=None,
                    help="override the camera's calib_pass1_backend "
                         "(bytetrack | botsort | botsort+reid)")
    ap.add_argument("--resume", action="store_true",
                    help="continue an interrupted dump (recipe must match; "
                         "cold-tracker boundary splits documented in run_pass1)")
    args = ap.parse_args()

    from backend.services.two_pass import run_pass1

    conn = sqlite3.connect(f"data/projects/{args.project}/project.db")
    fps = float(conn.execute(
        "SELECT fps FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (args.camera,)).fetchone()[0])
    conn.close()
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    f_lo = int((t0 - VIDEO_START).total_seconds() * fps)
    f_hi = f_lo + int(args.minutes * 60 * fps)

    def progress(done, total, points):
        print(f"  tracked {done} frames ({points} points)...", flush=True)

    res = run_pass1(args.project, args.camera,
                    variant=args.variant or DEFAULT_VARIANT,
                    start_frame=f_lo, end_frame=f_hi,
                    backend=args.backend, resume=args.resume,
                    progress=progress)
    print(f"wrote {res['tracks_dir']}  ({res['rows']} points, recipe {res['recipe']})",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
