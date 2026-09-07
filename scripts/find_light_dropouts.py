"""Light/shadow dropout finder (operator disease class, scene 6 cam3).

A shadow dropout = a MOVING track that dies mid-scene: not at a frame
edge (normal exit), not stopped (the parked/red-light class is
handled by stop-fracture). Death locations are clustered on an 80px
grid per camera-window — shadows are fixed in place for a given time
of day, so a real light-based zone shows up as a hot cluster.

For each cluster: n deaths, mean death speed, share reborn nearby
(a track born within 90px/60 frames after the death = a fracture the
rejoiner could bridge; no rebirth = the vehicle went invisible).

Usage:  py -X utf8 scripts/find_light_dropouts.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
WINDOWS = [(1, "study_0700"), (1, "study_1600"),
           (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
           (3, "study_0600"),
           (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
           (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]
EDGE_PX = 60          # deaths this close to a frame edge are normal exits
MOVE_PX_F = 2.0       # mean speed over the last 10 obs to count as moving
GRID = 80             # death-location cluster cell size
REBIRTH_PX = 90
REBIRTH_FRAMES = 60
MIN_TRACK_OBS = 8


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vids = {int(r[0]): (r[1], r[2]) for r in con.execute(
        "SELECT camera_id, content_hash, path FROM videos")}
    con.close()

    import cv2
    report = []
    for cam, variant in WINDOWS:
        chash = vids[cam][0]
        td = tracks_dir(parquet_path(PROJ, cam, chash, variant))
        cf = Path(td) / "count.txt"
        if not cf.exists():
            continue
        n = int(cf.read_text())
        rows = np.load(Path(td) / "rows.npy", mmap_mode="r")[:n]

        cap = cv2.VideoCapture(vids[cam][1])
        W = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920
        H = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080
        cap.release()

        order = np.lexsort((rows[:, 1], rows[:, 0]))
        r = np.asarray(rows[order])
        tid = r[:, 0]
        starts = np.searchsorted(tid, np.unique(tid), side="left")
        ends = np.r_[starts[1:], len(r)]

        births = []           # (frame, x, y) for rebirth lookup
        deaths = []           # (frame, x, y, speed, track_len)
        for s, e in zip(starts, ends):
            if e - s < MIN_TRACK_OBS:
                continue
            births.append((r[s, 1], r[s, 2], r[s, 3]))
            tail = r[max(s, e - 10):e]
            d = r[e - 1]
            steps = np.diff(tail[:, 1:4], axis=0)
            fgap = np.maximum(steps[:, 0], 1)
            sp = float(np.mean(np.hypot(steps[:, 1], steps[:, 2]) / fgap))
            deaths.append((d[1], d[2], d[3], sp, e - s, r[s, 0]))
        births_a = np.array(births) if births else np.zeros((0, 3))

        clusters = defaultdict(list)
        for f, x, y, sp, tl, t in deaths:
            if (x < EDGE_PX or x > W - EDGE_PX
                    or y < EDGE_PX or y > H - EDGE_PX):
                continue
            if sp < MOVE_PX_F:
                continue
            near = births_a[(np.abs(births_a[:, 0] - f) <= REBIRTH_FRAMES)
                            & (births_a[:, 0] > f)]
            reborn = bool(len(near)) and bool(
                np.any(np.hypot(near[:, 1] - x, near[:, 2] - y)
                       <= REBIRTH_PX))
            clusters[(int(x // GRID), int(y // GRID))].append(
                (f, x, y, sp, tl, t, reborn))

        for key, ds in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
            if len(ds) < 8:
                continue
            xs = [d[1] for d in ds]; ys = [d[2] for d in ds]
            rb = sum(1 for d in ds if d[6]) / len(ds)
            sp = float(np.mean([d[3] for d in ds]))
            report.append((cam, variant, int(np.mean(xs)), int(np.mean(ys)),
                           len(ds), sp, rb))
    report.sort(key=lambda r: -r[4])
    print(f"{'cam':>3} {'window':12} {'x':>5} {'y':>5} {'deaths':>7} "
          f"{'spd':>5} {'reborn%':>8}")
    for cam, v, x, y, nn, sp, rb in report[:30]:
        print(f"{cam:>3} {v:12} {x:>5} {y:>5} {nn:>7} {sp:>5.1f} "
              f"{100*rb:>7.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
