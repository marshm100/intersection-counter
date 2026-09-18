"""Vanish-death class census (operator rulings 2026-09-06 calibrate it).

Classifies every moving mid-scene track death corridor-wide:
- TRAILER: the box ballooned before death (grew >1.8x over its prior
  size) — scene 2's transport trailer.
- THEFT: another track is alive within reach of the death point and
  SURVIVES the death by 20+ frames — scenes 1/3/6 (the thief drives
  on with the box).
- LIGHT_FADE: dies alone, near a gate it almost reached — scenes 4/5
  (the finish-line washout, dark pole and bright pole).
- UNEXPLAINED: none of the above.

Prints per-window class counts and the calibration check against the
six filmed scenes.

Usage:  py -X utf8 scripts/measure_vanish_classes.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
WINDOWS = [(1, "study_0700"), (1, "study_1600"),
           (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
           (3, "study_0600"),
           (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
           (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]
EDGE_PX = 60
MOVE_PX_F = 2.0
MIN_TRACK_OBS = 8
NEIGHBOR_FRAMES = 15
SURVIVE_FRAMES = 20
GROWTH_RATIO = 1.8
GATE_NEAR_PX = 150
# the six filmed scenes: (cam, variant, death frame, track first frame)
FILMED = {(2, "study_1600", 1579465): "S1 theft",
          (2, "study_0700", 661486): "S2 trailer",
          (3, "study_0600", 223348): "S3 theft",
          (3, "study_0600", 218549): "S4 light",
          (1, "study_0700", 260547): "S5 light",
          (5, "study_0700", 306247): "S6 theft-chain"}


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * dx
                                               + (py - y1) * dy) / L2))
    return float(np.hypot(px - (x1 + t * dx), py - (y1 + t * dy)))


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vids = {int(r[0]): r[1] for r in con.execute(
        "SELECT camera_id, content_hash FROM videos")}
    con.close()
    import cv2

    grand = Counter()
    print(f"{'window':16} {'deaths':>7} {'theft':>7} {'light':>7} "
          f"{'trailer':>8} {'unexpl':>7}")
    for cam, variant in WINDOWS:
        td = tracks_dir(parquet_path(PROJ, cam, vids[cam], variant))
        if not (Path(td) / "count.txt").exists():
            continue
        n = int((Path(td) / "count.txt").read_text())
        rows = np.load(Path(td) / "rows.npy", mmap_mode="r")[:n]

        con = sqlite3.connect(
            f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
        vpath = con.execute("SELECT path FROM videos WHERE camera_id=?",
                            (cam,)).fetchone()[0]
        con.close()
        cap = cv2.VideoCapture(vpath)
        W = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920
        H = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080
        cap.release()

        geom = leg_geometry_for_camera(PROJ, cam)
        mouths = {l: g["mouth"] for l, g in geom.items() if g.get("mouth")}
        heads = {l: g.get("heading") for l, g in geom.items()}
        gates = build_gates(mouths, list_paths_for_camera(PROJ, cam), heads)
        chords = [(p1[0], p1[1], p2[0], p2[1])
                  for p1, p2, _n in gates.values()]

        order = np.lexsort((rows[:, 1], rows[:, 0]))
        r = np.asarray(rows[order])
        tid = r[:, 0]
        uniq, starts = np.unique(tid, return_index=True)
        ends = np.r_[starts[1:], len(r)]
        track_end_f = {int(u): int(r[e - 1, 1])
                       for u, e in zip(uniq, ends)}

        forder = np.argsort(r[:, 1], kind="stable")
        rf = r[forder]
        frames_sorted = rf[:, 1]

        counts = Counter()
        for s, e in zip(starts, ends):
            if e - s < MIN_TRACK_OBS:
                continue
            d = r[e - 1]
            f0, x, y = d[1], d[2], d[3]
            if (x < EDGE_PX or x > W - EDGE_PX
                    or y < EDGE_PX or y > H - EDGE_PX):
                continue
            tail = r[max(s, e - 10):e]
            steps = np.diff(tail[:, 1:4], axis=0)
            sp = np.mean(np.hypot(steps[:, 1], steps[:, 2])
                         / np.maximum(steps[:, 0], 1))
            if sp < MOVE_PX_F:
                continue
            counts["deaths"] += 1

            area_late = float(np.mean(tail[-5:, 4] * tail[-5:, 5]))
            head = r[max(s, e - 30):max(s, e - 10)]
            area_early = (float(np.mean(head[:, 4] * head[:, 5]))
                          if len(head) else area_late)
            if area_early > 0 and area_late / area_early > GROWTH_RATIO:
                cls = "trailer"
            else:
                lo = np.searchsorted(frames_sorted, f0 - NEIGHBOR_FRAMES)
                hi = np.searchsorted(frames_sorted, f0 + NEIGHBOR_FRAMES)
                seg = rf[lo:hi]
                reach = max(60.0, 1.5 * max(float(d[4]), float(d[5])))
                near = seg[(seg[:, 0] != d[0])
                           & (np.hypot(seg[:, 2] - x, seg[:, 3] - y)
                              <= reach)]
                thief = any(track_end_f[int(t)] >= f0 + SURVIVE_FRAMES
                            for t in np.unique(near[:, 0]))
                if thief:
                    cls = "theft"
                elif chords and min(seg_dist(x, y, *c)
                                    for c in chords) <= GATE_NEAR_PX:
                    cls = "light_fade"
                else:
                    cls = "unexplained"
            counts[cls] += 1
            key = (cam, variant, int(f0))
            if key in FILMED:
                print(f"  CALIBRATION {FILMED[key]}: classifier says "
                      f"{cls.upper()}")
        print(f"cam{cam} {variant:11} {counts['deaths']:>7} "
              f"{counts['theft']:>7} {counts['light_fade']:>7} "
              f"{counts['trailer']:>8} {counts['unexplained']:>7}")
        grand.update(counts)
    print(f"\n{'CORRIDOR':16} {grand['deaths']:>7} {grand['theft']:>7} "
          f"{grand['light_fade']:>7} {grand['trailer']:>8} "
          f"{grand['unexplained']:>7}")
    d = grand["deaths"] or 1
    print(f"{'shares':16} {'':>7} {100*grand['theft']/d:>6.0f}% "
          f"{100*grand['light_fade']/d:>6.0f}% "
          f"{100*grand['trailer']/d:>7.0f}% "
          f"{100*grand['unexplained']/d:>6.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
