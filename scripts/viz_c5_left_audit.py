"""Cam5 NB_left audit reel — the 12:00-12:15 bin, MOVING film.

Two trail shapes booked as lefts: HOOKS (full arc from the bottom of
frame onto the far road) and STUBS (short flat trails living on the
far road only). Films 2 hooks + 4 stubs, blue box + green ground
trail, clip covers the full track life plus margins.

Usage:  py -X utf8 scripts/viz_c5_left_audit.py
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
BLUE, GREEN, BLACK = (255, 70, 20), (60, 255, 60), (0, 0, 0)
W_OUT, STEP = 440, 3


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
        "SELECT vehicle_track_id, trajectory_data FROM vehicle_events "
        "WHERE camera_id=5 AND rejected=0 AND origin_leg_id=39 AND "
        "destination_leg_id=38 AND timestamp_real >= "
        "'2026-05-12T12:00:00' AND timestamp_real < "
        "'2026-05-12T12:15:00' ORDER BY timestamp_real").fetchall()
    s.close()

    hooks, stubs = [], []
    for tid, tj in evs:
        t = json.loads(tj)
        ys = [p[1] for p in t]
        span = max(ys) - min(ys)
        if span > 120:
            hooks.append(tid)
        else:
            stubs.append(tid)
    print(f"hooks {len(hooks)}, stubs {len(stubs)}")
    picks = ([("hook", t) for t in hooks[:2]]
             + [("stub", t) for t in stubs[:4]])

    td = tracks_dir(parquet_path(PROJ, 5, chash, "l1_study_1100"))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.load(Path(td) / "rows.npy", mmap_mode="r")[:n]

    Path("screenshots").mkdir(exist_ok=True)
    for i, (kind, tid) in enumerate(picks, 1):
        trk = np.asarray(rows[rows[:, 0] == float(tid)])
        if not len(trk):
            continue
        f_lo = max(0, int(trk[0, 1]) - int(2 * fps))
        f_hi = int(trk[-1, 1]) + int(3 * fps)
        if f_hi - f_lo > 40 * fps:
            f_hi = f_lo + int(40 * fps)
        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        frames = []
        for fno in range(f_lo, f_hi):
            ok, fr = cap.read()
            if not ok:
                break
            if (fno - f_lo) % STEP:
                continue
            scale = W_OUT / fr.shape[1]
            img = cv2.resize(fr, (W_OUT, int(fr.shape[0] * scale)))
            pts = trk[trk[:, 1] <= fno]
            if len(pts) >= 2:
                gl = np.stack([pts[:, 2],
                               pts[:, 3] + pts[:, 5] / 2.0], axis=1)
                pl = (gl * scale).astype(int)
                cv2.polylines(img, [pl], False, BLACK, 4)
                cv2.polylines(img, [pl], False, GREEN, 2)
            if len(pts) and fno <= trk[-1, 1]:
                p = pts[-1]
                x, y = int(p[2] * scale), int(p[3] * scale)
                bw = max(int(p[4] * scale / 2), 6)
                bh = max(int(p[5] * scale / 2), 6)
                cv2.rectangle(img, (x - bw, y - bh), (x + bw, y + bh),
                              BLACK, 4)
                cv2.rectangle(img, (x - bw, y - bh), (x + bw, y + bh),
                              BLUE, 2)
            frames.append(Image.fromarray(
                cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        cap.release()
        if not frames:
            continue
        out = Path(f"screenshots/c5_left_{kind}_{i}.gif")
        q = [f.quantize(80, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"clip {i} ({kind}, track {tid}) -> {out} "
              f"({out.stat().st_size//1024} KB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
