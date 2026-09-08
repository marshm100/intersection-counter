"""Cam5 NB_left curved-phantom pair reel (G-C45-1 hold diagnosis).

Films OVERLAPPING PAIRS of left-turn events: track A blue, track B
orange, both with ground-contact trails. If two boxes ride one
vehicle, the double-count is on film.

Usage:  py -X utf8 scripts/viz_c5_twins.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, ".")

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
STEM = ("data/projects/97a7849a/_replay_scratch/c45_20260907/"
        "cx_cam5_study_1100.db")
BLUE, ORANGE, BLACK = (255, 70, 20), (0, 140, 255), (0, 0, 0)
W_OUT, STEP = 420, 3


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath, chash, fps = con.execute(
        "SELECT path, content_hash, fps FROM videos WHERE camera_id=5"
    ).fetchone()
    fps = float(fps)
    con.close()

    s = sqlite3.connect(f"file:{STEM}?mode=ro", uri=True)
    evs = s.execute(
        "SELECT vehicle_track_id, start_frame, frame_number, "
        "trajectory_data FROM vehicle_events WHERE camera_id=5 AND "
        "rejected=0 AND origin_leg_id=39 AND destination_leg_id=38 "
        "ORDER BY start_frame").fetchall()
    s.close()
    spans = [(r[0], r[1], r[2], json.loads(r[3])) for r in evs]
    pairs = []
    used = set()
    for i in range(len(spans)):
        if spans[i][0] in used:
            continue
        for j in range(i + 1, min(i + 6, len(spans))):
            a, b = spans[i], spans[j]
            if b[1] <= a[2] and a[1] <= b[2] and b[0] not in used:
                ax, ay = a[3][-1][0], a[3][-1][1]
                bx, by = b[3][-1][0], b[3][-1][1]
                if ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 < 120:
                    ov = min(a[2], b[2]) - max(a[1], b[1])
                    pairs.append((ov, a, b))
                    used.add(a[0])
                    used.add(b[0])
                    break
    pairs.sort(key=lambda p: -p[0])

    td = tracks_dir(parquet_path(PROJ, 5, chash, "l1_study_1100"))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.load(Path(td) / "rows.npy", mmap_mode="r")[:n]

    Path("screenshots").mkdir(exist_ok=True)
    made = 0
    for ov, a, b in pairs:
        if made >= 3:
            break
        ta = np.asarray(rows[rows[:, 0] == float(a[0])])
        tb = np.asarray(rows[rows[:, 0] == float(b[0])])
        if not len(ta) or not len(tb):
            continue
        # film the CO-EXISTENCE window (the evidence) +- 3 s
        f_lo = int(max(ta[0, 1], tb[0, 1])) - int(3 * fps)
        f_hi = int(min(ta[-1, 1], tb[-1, 1])) + int(3 * fps)
        if f_hi - f_lo > 40 * fps:
            f_hi = f_lo + int(40 * fps)
        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, f_lo))
        frames = []
        for fno in range(max(0, f_lo), f_hi):
            ok, fr = cap.read()
            if not ok:
                break
            if (fno - f_lo) % STEP:
                continue
            scale = W_OUT / fr.shape[1]
            img = cv2.resize(fr, (W_OUT, int(fr.shape[0] * scale)))
            for trk, col in ((ta, BLUE), (tb, ORANGE)):
                pts = trk[trk[:, 1] <= fno]
                if len(pts) >= 2:
                    gl = np.stack([pts[:, 2],
                                   pts[:, 3] + pts[:, 5] / 2.0], axis=1)
                    pl = (gl * scale).astype(int)
                    cv2.polylines(img, [pl], False, BLACK, 4)
                    cv2.polylines(img, [pl], False, col, 2)
                if len(pts) and fno <= trk[-1, 1]:
                    p = pts[-1]
                    x, y = int(p[2] * scale), int(p[3] * scale)
                    bw = max(int(p[4] * scale / 2), 6)
                    bh = max(int(p[5] * scale / 2), 6)
                    cv2.rectangle(img, (x - bw, y - bh),
                                  (x + bw, y + bh), BLACK, 4)
                    cv2.rectangle(img, (x - bw, y - bh),
                                  (x + bw, y + bh), col, 2)
            frames.append(Image.fromarray(
                cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        cap.release()
        if not frames:
            continue
        made += 1
        out = Path(f"screenshots/c5_twin_{made}.gif")
        q = [f.quantize(72, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"pair {made}: tracks {a[0]}+{b[0]} overlap {ov}f -> {out} "
              f"({out.stat().st_size//1024} KB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
