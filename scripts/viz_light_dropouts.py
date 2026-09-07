"""Light/shadow dropout reel — the corridor's top VANISH zones.

Each clip follows ONE moving vehicle to its mid-scene death: blue
box + trail while tracked, then a magenta X pinned at the last seen
point while the video keeps rolling — the vehicle drives on with no
marking. High-contrast, black-outlined (operator instrument rule);
clips run long enough to cover the movement (operator rule).

Usage:  py -X utf8 scripts/viz_light_dropouts.py
Writes screenshots/light_dropout_{1..6}.gif
"""
from __future__ import annotations

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
BLUE, MAGENTA, BLACK = (255, 70, 20), (255, 0, 220), (0, 0, 0)
W_OUT, STEP = 440, 4
PRE_S, POST_S = 6.0, 5.0
# (camera, variant, cluster x, cluster y)
SCENES = [(2, "study_1600", 188, 103),
          (2, "study_0700", 185, 104),
          (3, "study_0600", 117, 180),
          (3, "study_0600", 190, 171),
          (1, "study_0700", 115, 250),
          (5, "study_0700", 194, 203)]


def pick_example(rows, cx, cy, used=()):
    """Longest MOVING track that dies within 80px of the cluster."""
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    r = np.asarray(rows[order])
    tid = r[:, 0]
    starts = np.searchsorted(tid, np.unique(tid), side="left")
    ends = np.r_[starts[1:], len(r)]
    best, best_len = None, 0
    for s, e in zip(starts, ends):
        if e - s < 25 or r[s, 0] in used:
            continue
        d = r[e - 1]
        if abs(d[2] - cx) > 80 or abs(d[3] - cy) > 80:
            continue
        tail = r[max(s, e - 10):e]
        steps = np.diff(tail[:, 1:4], axis=0)
        sp = np.mean(np.hypot(steps[:, 1], steps[:, 2])
                     / np.maximum(steps[:, 0], 1))
        if sp < 4.0:
            continue
        if e - s > best_len:
            best, best_len = r[s:e], e - s
    return best


def draw(frame, trk, fno, death_f, dx, dy):
    scale = W_OUT / frame.shape[1]
    img = cv2.resize(frame, (W_OUT, int(frame.shape[0] * scale)))
    pts = trk[trk[:, 1] <= fno]
    if len(pts) >= 2:
        pl = (pts[:, 2:4] * scale).astype(int)
        cv2.polylines(img, [pl], False, BLACK, 4)
        cv2.polylines(img, [pl], False, BLUE, 2)
    if fno <= death_f and len(pts):
        p = pts[-1]
        x, y = int(p[2] * scale), int(p[3] * scale)
        bw = max(int(p[4] * scale / 2), 8)
        bh = max(int(p[5] * scale / 2), 8)
        cv2.rectangle(img, (x - bw, y - bh), (x + bw, y + bh), BLACK, 4)
        cv2.rectangle(img, (x - bw, y - bh), (x + bw, y + bh), BLUE, 2)
    else:
        x, y = int(dx * scale), int(dy * scale)
        for a, b in [((-12, -12), (12, 12)), ((-12, 12), (12, -12))]:
            cv2.line(img, (x + a[0], y + a[1]), (x + b[0], y + b[1]),
                     BLACK, 6)
            cv2.line(img, (x + a[0], y + a[1]), (x + b[0], y + b[1]),
                     MAGENTA, 3)
    return img


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vids = {int(r[0]): (r[1], r[2], float(r[3] or 25.0)) for r in con.execute(
        "SELECT camera_id, content_hash, path, fps FROM videos")}
    con.close()
    Path("screenshots").mkdir(exist_ok=True)

    used: set = set()
    for i, (cam, variant, cx, cy) in enumerate(SCENES, 1):
        chash, vpath, fps = vids[cam]
        td = tracks_dir(parquet_path(PROJ, cam, chash, variant))
        n = int((Path(td) / "count.txt").read_text())
        rows = np.load(Path(td) / "rows.npy", mmap_mode="r")[:n]
        trk = pick_example(rows, cx, cy, used)
        if trk is None:
            print(f"scene {i}: no example found")
            continue
        used.add((trk[0, 0]))
        death_f = int(trk[-1, 1])
        dx, dy = float(trk[-1, 2]), float(trk[-1, 3])
        f_lo = max(0, death_f - int(PRE_S * fps))
        f_hi = death_f + int(POST_S * fps)

        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        frames = []
        for fno in range(f_lo, f_hi):
            ok, fr = cap.read()
            if not ok:
                break
            if (fno - f_lo) % STEP:
                continue
            img = draw(fr, trk, fno, death_f, dx, dy)
            frames.append(Image.fromarray(
                cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        cap.release()
        out = Path(f"screenshots/light_dropout_{i}.gif")
        q = [f.quantize(96, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"scene {i}: cam{cam} {variant} death@f{death_f} "
              f"({dx:.0f},{dy:.0f}) track_len={len(trk)} -> {out} "
              f"({out.stat().st_size//1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
