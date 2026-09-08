"""Cam2 EB_right twin-pair reel (2026-09-08).

cam2's east-approach right turns run +505 over Miovision across the
day. The vehicles genuinely enter over the W gate (880 of 1,009
witnessed), so it is not a misattributed origin. But 155 pairs of
those tracks stay within 35 px of EACH OTHER for their whole shared
life — the tightest 3-6 px apart for hundreds of frames.

This films the tightest pairs: track A blue, track B orange, both
with ground-contact trails, so the operator can rule whether they are
one vehicle counted twice or two vehicles genuinely that close.

Read-only. Writes screenshots/c2_twin_{n}.gif
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
CAM, VARIANT = 2, "study_1600"
PAIRS = [(4613, 4616), (13682, 13698), (1845, 1846)]
A_COL, B_COL = (255, 70, 20), (0, 165, 255)
MAGENTA, BLACK, WHITE = (255, 0, 220), (0, 0, 0), (255, 255, 255)
W_OUT, STEP = 460, 3


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

    for k, (t1, t2) in enumerate(PAIRS, 1):
        A = rows[rows[:, 0] == float(t1)]
        B = rows[rows[:, 0] == float(t2)]
        if not len(A) or not len(B):
            print(f"pair {k}: missing track")
            continue
        f_lo = max(0, int(min(A[0, 1], B[0, 1])) - int(1.5 * fps))
        f_hi = int(max(A[-1, 1], B[-1, 1])) + int(2 * fps)
        if f_hi - f_lo > 45 * fps:
            f_hi = f_lo + int(45 * fps)
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
            for trk, col in ((A, A_COL), (B, B_COL)):
                seen = trk[trk[:, 1] <= fno]
                if len(seen) >= 2:
                    gl = np.stack([seen[:, 2],
                                   seen[:, 3] + seen[:, 5] / 2.0], axis=1)
                    cv2.polylines(im, [(gl * sc).astype(int)], False,
                                  BLACK, 4)
                    cv2.polylines(im, [(gl * sc).astype(int)], False, col, 2)
                if len(seen) and trk[0, 1] <= fno <= trk[-1, 1]:
                    p = seen[-1]
                    x1, x2 = (int((p[2] - p[4] / 2) * sc),
                              int((p[2] + p[4] / 2) * sc))
                    y1, y2 = (int((p[3] - p[5] / 2) * sc),
                              int((p[3] + p[5] / 2) * sc))
                    cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 4)
                    cv2.rectangle(im, (x1, y1), (x2, y2), col, 2)
            frames.append(Image.fromarray(cv2.cvtColor(im,
                                                       cv2.COLOR_BGR2RGB)))
        cap.release()
        out = Path(f"screenshots/c2_twin_{k}.gif")
        q = [f.quantize(72, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"pair {k}: tracks {t1}+{t2} -> {out} "
              f"({out.stat().st_size // 1024} KB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
