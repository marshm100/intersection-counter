"""Cam5 NB_left operator audit sheet — the 12:00-12:15 bin (we count
53, Miovision 25). One thumbnail per booked left turn: the video
frame at the track's midpoint, its full ground trail, numbered.

Usage:  py -X utf8 scripts/c5_left_contact_sheet.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, ".")

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
STEM = ("data/projects/97a7849a/_replay_scratch/c45_20260907/"
        "cx_cam5_study_1100.db")
BLUE, BLACK, WHITE = (255, 70, 20), (0, 0, 0), (255, 255, 255)
TH_W, COLS = 320, 6


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath, chash = con.execute(
        "SELECT path, content_hash FROM videos WHERE camera_id=5"
    ).fetchone()
    con.close()

    s = sqlite3.connect(f"file:{STEM}?mode=ro", uri=True)
    evs = s.execute(
        "SELECT vehicle_track_id, timestamp_real FROM vehicle_events "
        "WHERE camera_id=5 AND rejected=0 AND origin_leg_id=39 AND "
        "destination_leg_id=38 AND timestamp_real >= "
        "'2026-05-12T12:00:00' AND timestamp_real < "
        "'2026-05-12T12:15:00' ORDER BY timestamp_real").fetchall()
    s.close()
    print(f"{len(evs)} events in the bin")

    td = tracks_dir(parquet_path(PROJ, 5, chash, "l1_study_1100"))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.load(Path(td) / "rows.npy", mmap_mode="r")[:n]

    cap = cv2.VideoCapture(vpath)
    thumbs = []
    for k, (tid, ts) in enumerate(evs, 1):
        trk = np.asarray(rows[rows[:, 0] == float(tid)])
        if not len(trk):
            continue
        mid = int(trk[len(trk) // 2, 1])
        cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
        ok, fr = cap.read()
        if not ok:
            continue
        scale = TH_W / fr.shape[1]
        img = cv2.resize(fr, (TH_W, int(fr.shape[0] * scale)))
        gl = np.stack([trk[:, 2], trk[:, 3] + trk[:, 5] / 2.0], axis=1)
        pl = (gl * scale).astype(int)
        cv2.polylines(img, [pl], False, BLACK, 3)
        cv2.polylines(img, [pl], False, BLUE, 1)
        p = trk[len(trk) // 2]
        x, y = int(p[2] * scale), int(p[3] * scale)
        bw = max(int(p[4] * scale / 2), 4)
        bh = max(int(p[5] * scale / 2), 4)
        cv2.rectangle(img, (x - bw, y - bh), (x + bw, y + bh), BLACK, 3)
        cv2.rectangle(img, (x - bw, y - bh), (x + bw, y + bh), BLUE, 1)
        cv2.putText(img, str(k), (6, 24), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, BLACK, 4)
        cv2.putText(img, str(k), (6, 24), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, WHITE, 2)
        thumbs.append(img)
    cap.release()

    th = thumbs[0].shape[0]
    rows_n = (len(thumbs) + COLS - 1) // COLS
    sheet = np.zeros((rows_n * th, COLS * TH_W, 3), dtype=np.uint8)
    for i, t in enumerate(thumbs):
        r, c = divmod(i, COLS)
        sheet[r * th:(r + 1) * th, c * TH_W:(c + 1) * TH_W] = t
    out = Path("screenshots/c5_left_audit_1200.png")
    cv2.imwrite(str(out), sheet)
    print(f"{len(thumbs)} thumbnails -> {out} "
          f"({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
