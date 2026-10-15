"""Define the journey-label clips (2026-09-30, docs/research_tracking_2026-09-29.md
phase 0).

The clips are fixed by RULE, before any tracker output is looked at: each is
3 minutes long and starts at minute 5 of its window's first 15-minute bin.
The window start comes from the window's own detection-cache meta. Cameras
and windows are chosen to span the known difficulties: cam2 (the camera the
default tracker handles worst), cam4 16:00 (far-field northbound), cam5 07:00
(far-field stubs), cam1 07:00, and cam3 at dawn.

HELD-OUT SET (2026-10-01): a second clip per camera by the same rule at minute 50
(clip ids *_m50). The minute-5 clips are the DEVELOPMENT set; the minute-50 clips are
scored only for ship candidates (scripts/eval_journeys.py --heldout), so tuning cannot
drift onto the clips it is judged by.

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
OFFSETS_MIN = (5, 50)          # development set, held-out set
# FM 51 (project 0acb12c0, the never-tuned-on site; 2026-10-15, failure predictor plan): ONE clip by the same
# rule, minute 5 of the 07:00 window. Every FM 51 clip is HELD OUT - the site is never used to build anything.
if PROJ == "0acb12c0":
    CLIPS = [(2, "vl3_l1_study_0700", "FM 51 07:05 (held-out site)")]
    OFFSETS_MIN = (5,)
LENGTH_S = 3 * 60


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    for (cam, variant, label), off in ((c, o) for o in OFFSETS_MIN for c in CLIPS):
        vid, chash, fps = con.execute(
            "SELECT video_id, content_hash, fps FROM videos WHERE camera_id=? "
            "ORDER BY sort_order LIMIT 1", (cam,)).fetchone()
        meta = json.loads(parquet_path(PROJ, cam, chash, variant)
                          .with_suffix(".meta.json").read_text())
        f0 = (meta["windows"][0] if "windows" in meta else meta["frames"])[0]
        start = int(f0 + off * 60 * fps)
        end = int(start + LENGTH_S * fps)
        clip_id = f"cam{cam}_{variant.split('_')[-1]}_m{off}"
        hh, mm = int(variant.split("_")[-1][:2]), off
        lab = (label if off == 5 or PROJ == "0acb12c0" else
               f"cam{cam} {hh:02d}:{mm:02d} (held out){' (dawn)' if cam == 3 else ''}")
        c = upsert_clip(PROJ, clip_id, cam, vid, start, end, float(fps), lab)
        print(f"{clip_id}: video {vid}, frames {c['start_frame']}-{c['end_frame']} "
              f"({fps:g} fps) - {lab}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
