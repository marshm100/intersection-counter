"""Cam5 clip-6 fragment chain (operator pairing request 2026-09-08).

Films the three fragments the physics says are ONE vehicle:
  A yellow  108873  approach, stops at the mouth
  B blue    108910  the clip-6 stub  -> booked a phantom LEFT
  C orange  108928  the continuation -> booked a THROUGH
Ground-contact trails; each box labelled A/B/C.

Usage:  py -X utf8 scripts/viz_c5_chain.py
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
CHAIN = [(108873, "A", (0, 215, 255)),      # yellow
         (108910, "B", (255, 70, 20)),      # blue
         (108928, "C", (0, 140, 255))]      # orange
BLACK = (0, 0, 0)
W_OUT, STEP = 420, 3


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath, chash, fps = con.execute(
        "SELECT path, content_hash, fps FROM videos WHERE camera_id=5"
    ).fetchone()
    fps = float(fps)
    con.close()

    td = tracks_dir(parquet_path(PROJ, 5, chash, "l1_study_1100"))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])
    trks = {tid: rows[rows[:, 0] == float(tid)] for tid, _, _ in CHAIN}

    f_lo = int(min(t[0, 1] for t in trks.values()))
    f_hi = int(max(t[-1, 1] for t in trks.values())) + int(2 * fps)
    print(f"chain frames {f_lo}-{f_hi} ({(f_hi-f_lo)/fps:.0f}s)")

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
        for tid, lab, col in CHAIN:
            trk = trks[tid]
            pts = trk[trk[:, 1] <= fno]
            if len(pts) >= 2:
                gl = np.stack([pts[:, 2],
                               pts[:, 3] + pts[:, 5] / 2.0], axis=1)
                pl = (gl * scale).astype(int)
                cv2.polylines(img, [pl], False, BLACK, 4)
                cv2.polylines(img, [pl], False, col, 2)
            if len(pts) and trk[0, 1] <= fno <= trk[-1, 1]:
                p = pts[-1]
                x, y = int(p[2] * scale), int(p[3] * scale)
                bw = max(int(p[4] * scale / 2), 5)
                bh = max(int(p[5] * scale / 2), 5)
                cv2.rectangle(img, (x - bw, y - bh), (x + bw, y + bh),
                              BLACK, 4)
                cv2.rectangle(img, (x - bw, y - bh), (x + bw, y + bh),
                              col, 2)
                cv2.putText(img, lab, (x - bw, y - bh - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, BLACK, 4)
                cv2.putText(img, lab, (x - bw, y - bh - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
        frames.append(Image.fromarray(
            cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    cap.release()
    out = Path("screenshots/c5_chain.gif")
    q = [f.quantize(80, dither=Image.Dither.NONE) for f in frames]
    q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
              duration=int(1000 * STEP / fps), loop=0)
    print(f"{len(frames)} frames -> {out} ({out.stat().st_size//1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
