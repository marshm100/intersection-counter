"""Speed-discontinuity signal on the operator-ruled clips (2026-09-09).

His observation across reels 2 and 4: a theft ends with the box
"launched" by a fast cross-traffic vehicle, or the id "lingers until
it dies". His 2026-09-08 lead: a large speed discontinuity WITHIN one
journey means the box changed vehicles.

For each ruled track, on the bottom-centre path: per-frame speed
(px/frame), then
  jump   = max over the track of speed[i] / (running median of the
           previous 2 s + 0.5 px)  -- the launch
  hold   = longest stationary run (< 1 px/frame) as a share of the
           track  -- the linger
Read-only; prints one row per ruled clip with its ruling.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
RULED = [
    # cam, variant, tid, class, ruling
    (1, "study_0700", 2,      "clean", "reel1 through, corner spawn"),
    (1, "study_0700", 4829,   "clean", "reel1 through, glare"),
    (1, "study_0700", 9205,   "clean?", "reel1 through, 18-wheeler occlusion (identity doubt)"),
    (1, "study_0700", 14948,  "clean", "reel1 through, box-truck occlusion"),
    (1, "study_0700", 22270,  "clean", "reel1 right, corner spawn"),
    (2, "study_0700", 16722,  "clean", "clean right"),
    (2, "study_0700", 17526,  "clean", "waiting right"),
    (2, "study_1600", 4383,   "clean", "reel2 right, corner spawn"),
    (2, "study_1600", 18964,  "clean", "reel2 right, corner spawn"),
    (2, "study_1600", 112,    "THEFT", "reel2 N->S through stole the waiting car"),
    (2, "study_1600", 9031,   "THEFT", "reel2 occlusion theft"),
    (2, "study_1600", 26259,  "THEFT", "reel2 occlusion theft"),
    (3, "study_0600", 14634,  "THEFT", "reel4 lock disrupted, lingers, dies"),
    (3, "study_0600", 154504, "THEFT", "reel4 last-minute theft at N exit"),
    (3, "study_0600", 281674, "THEFT", "reel4 lingers, stolen, runs away"),
    (3, "study_0600", 302741, "THEFT", "reel4 misfire + theft"),
    (3, "study_0600", 332755, "THEFT", "reel4 launched in reverse"),
]


def main() -> int:
    cache = {}
    print(f"{'cam':>3} {'tid':>7} {'class':6} {'fps':>4} {'rows':>5} "
          f"{'jump':>6} {'hold%':>6} {'maxspd':>7}  ruling")
    for cam, variant, tid, cls, ruling in RULED:
        key = (cam, variant)
        if key not in cache:
            con = sqlite3.connect(
                f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
            chash, fps = con.execute(
                "SELECT content_hash, fps FROM videos WHERE camera_id=?",
                (cam,)).fetchone()
            con.close()
            td = tracks_dir(parquet_path(PROJ, cam, chash, variant))
            n = int((Path(td) / "count.txt").read_text())
            rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])
            cache[key] = (rows, float(fps))
        rows, fps = cache[key]
        trk = rows[rows[:, 0] == float(tid)]
        trk = trk[np.argsort(trk[:, 1])]
        if len(trk) < 3:
            print(f"{cam:>3} {tid:>7} {cls:6} no track")
            continue
        f = trk[:, 1]
        x = trk[:, 2]
        y = trk[:, 3] + trk[:, 5] / 2.0
        df = np.maximum(np.diff(f), 1.0)
        spd = np.hypot(np.diff(x), np.diff(y)) / df
        w = max(3, int(2.0 * fps))
        jump = 0.0
        for i in range(w, len(spd)):
            base = np.median(spd[i - w:i]) + 0.5
            jump = max(jump, spd[i] / base)
        still = spd < 1.0
        best = run = 0
        for s_ in still:
            run = run + 1 if s_ else 0
            best = max(best, run)
        hold = best / max(len(spd), 1)
        print(f"{cam:>3} {tid:>7} {cls:6} {fps:>4.0f} {len(trk):>5} "
              f"{jump:>6.1f} {hold * 100:>5.0f}% {spd.max():>7.1f}  {ruling}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
