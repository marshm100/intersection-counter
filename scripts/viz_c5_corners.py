"""Cam5 bottom-corner evidence (operator ruling 2026-09-08).

Draws the two BOTTOM CORNERS of the box as separate trails so the
operator can see his own rule being applied: at the entry line both
corners cross (the whole bottom edge passes), at the exit line only
the LEADING corner crosses because tracking ends there.

Read-only. Writes screenshots/c5_corners_{1,2,3}.gif
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
CAM, VARIANT = 5, "l1_study_1100"
TIDS = [(116990, 1), (101816, 2), (106513, 3)]
LEAD = (60, 255, 60)      # leading bottom corner  (green)
TRAIL = (0, 165, 255)     # trailing bottom corner (orange)
MAGENTA, BLACK, WHITE = (255, 0, 220), (0, 0, 0), (255, 255, 255)
W_OUT, STEP = 460, 2


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath, chash, fps = con.execute(
        "SELECT path, content_hash, fps FROM videos WHERE camera_id=?",
        (CAM,)).fetchone()
    legs = dict(con.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
        (CAM,)))
    con.close()
    fps = float(fps)

    geom = leg_geometry_for_camera(PROJ, CAM)
    gates = build_gates(
        {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
        list_paths_for_camera(PROJ, CAM),
        {lg: g.get("heading") for lg, g in geom.items()},
        leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})

    td = tracks_dir(parquet_path(PROJ, CAM, chash, VARIANT))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])

    for tid, idx in TIDS:
        trk = rows[rows[:, 0] == float(tid)]
        f_lo = max(0, int(trk[0, 1]) - int(1.5 * fps))
        f_hi = int(trk[-1, 1]) + int(2.5 * fps)
        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        frames = []
        for fno in range(f_lo, f_hi):
            ok, fr = cap.read()
            if not ok:
                break
            if (fno - f_lo) % STEP:
                continue
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            for lg, (p1, p2, _nrm) in gates.items():
                a = (int(p1[0] * sc), int(p1[1] * sc))
                b = (int(p2[0] * sc), int(p2[1] * sc))
                cv2.line(im, a, b, BLACK, 5)
                cv2.line(im, a, b, MAGENTA, 2)
                cv2.putText(im, legs.get(lg, ""), (a[0] + 3, a[1] - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, BLACK, 4)
                cv2.putText(im, legs.get(lg, ""), (a[0] + 3, a[1] - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, MAGENTA, 1)
            pts = trk[trk[:, 1] <= fno]
            if len(pts) >= 2:
                for sign, col in ((-1.0, LEAD), (1.0, TRAIL)):
                    c = np.stack([pts[:, 2] + sign * pts[:, 4] / 2.0,
                                  pts[:, 3] + pts[:, 5] / 2.0], axis=1)
                    cv2.polylines(im, [(c * sc).astype(int)], False,
                                  BLACK, 4)
                    cv2.polylines(im, [(c * sc).astype(int)], False, col, 2)
            if len(pts) and fno <= trk[-1, 1]:
                p = pts[-1]
                x1 = int((p[2] - p[4] / 2) * sc)
                x2 = int((p[2] + p[4] / 2) * sc)
                y1 = int((p[3] - p[5] / 2) * sc)
                y2 = int((p[3] + p[5] / 2) * sc)
                cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 4)
                cv2.rectangle(im, (x1, y1), (x2, y2), WHITE, 1)
                cv2.line(im, (x1, y2), (x2, y2), BLACK, 5)
                cv2.line(im, (x1, y2), (x2, y2), WHITE, 2)
            frames.append(Image.fromarray(cv2.cvtColor(im,
                                                       cv2.COLOR_BGR2RGB)))
        cap.release()
        out = Path(f"screenshots/c5_corners_{idx}.gif")
        q = [f.quantize(72, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"clip {idx} (tid {tid}) -> {out} "
              f"({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
