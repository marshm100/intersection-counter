"""Define the journey-label clips (2026-09-30, docs/research_tracking_2026-09-29.md
phase 0).

The clips are fixed by RULE, before any tracker output is looked at: each is
3 minutes long and starts at minute 5 of its window's first 15-minute bin.
The window start comes from the window's own detection-cache meta. Cameras
and windows are chosen to span the known difficulties: cam2 (the camera the
default tracker handles worst), cam4 16:00 (far-field northbound), cam5 07:00
(far-field stubs), cam1 07:00, and cam3 at dawn.

Usage: .venv\\Scripts\\python.exe -X utf8 scripts/journey_clips.py [PROJ]
Idempotent: re-running updates the clip frames and keeps any labels.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.journey_labels import upsert_clip  # noqa: E402

PROJ = sys.argv[1] if len(sys.argv) > 1 else "97a7849a"
CLIPS = [  # (camera, window variant, label)
    (2, "study_1600", "cam2 16:05"),
    (4, "study_1600", "cam4 16:05"),
    (5, "study_0700", "cam5 07:05"),
    (1, "study_0700", "cam1 07:05"),
    (3, "study_0600", "cam3 06:05 (dawn)"),
]
OFFSET_S, LENGTH_S = 5 * 60, 3 * 60


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    for cam, variant, label in CLIPS:
        vid, chash, fps = con.execute(
            "SELECT video_id, content_hash, fps FROM videos WHERE camera_id=? "
            "ORDER BY sort_order LIMIT 1", (cam,)).fetchone()
        meta = json.loads(parquet_path(PROJ, cam, chash, variant)
                          .with_suffix(".meta.json").read_text())
        f0 = (meta["windows"][0] if "windows" in meta else meta["frames"])[0]
        start = int(f0 + OFFSET_S * fps)
        end = int(start + LENGTH_S * fps)
        clip_id = f"cam{cam}_{variant.split('_')[-1]}_m5"
        c = upsert_clip(PROJ, clip_id, cam, vid, start, end, float(fps), label)
        print(f"{clip_id}: video {vid}, frames {c['start_frame']}-{c['end_frame']} "
              f"({fps:g} fps) - {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
