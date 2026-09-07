"""Cam1 phantom driveway-turn reel (G-C1-1 iteration-1 diagnosis).

Films real events the machine booked as driveway turns on the new
basis: blue box + trail = the tracked vehicle; the magenta line =
the driveway leg's drawn gate (permanent); the box vanishing = the
track's death. High-contrast, black-outlined; clips cover the full
movement plus tail (operator instrument rules).

Usage:  py -X utf8 scripts/viz_c1_phantoms.py
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
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

PROJ = "97a7849a"
STEM = "data/projects/97a7849a/_replay_scratch/c1_20260907/l1_cam1_study_0700.db"
BLUE, MAGENTA, BLACK = (255, 70, 20), (255, 0, 220), (0, 0, 0)
W_OUT, STEP, TAIL_S, LEAD_S = 460, 3, 3.0, 2.0


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath, chash, fps = con.execute(
        "SELECT path, content_hash, fps FROM videos WHERE camera_id=1"
    ).fetchone()
    fps = float(fps)
    eg = json.loads(con.execute(
        "SELECT gate_segment FROM legs WHERE camera_id=1 AND leg_id=25"
    ).fetchone()[0])
    con.close()

    s = sqlite3.connect(f"file:{STEM}?mode=ro", uri=True)
    picks = []
    for od, lab in (((22, 25), "into the driveway (NB_right)"),
                    ((25, 23), "out of the driveway (WB_right)")):
        rows = s.execute(
            "SELECT vehicle_track_id, start_frame, frame_number, "
            "classifier_path_distance FROM vehicle_events WHERE "
            "camera_id=1 AND rejected=0 AND origin_leg_id=? AND "
            "destination_leg_id=? ORDER BY classifier_path_distance "
            "DESC LIMIT 2", od).fetchall()
        picks += [(r, lab) for r in rows]
    s.close()

    td = tracks_dir(parquet_path(PROJ, 1, chash, "l1_study_0700"))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.load(Path(td) / "rows.npy", mmap_mode="r")[:n]

    Path("screenshots").mkdir(exist_ok=True)
    g1 = tuple(map(int, eg[0]))
    g2 = tuple(map(int, eg[1]))
    for i, ((tid, sf, ef, dist), lab) in enumerate(picks, 1):
        trk = np.asarray(rows[rows[:, 0] == float(tid)])
        if not len(trk):
            print(f"clip {i}: track {tid} not in dump")
            continue
        f_lo = max(0, int(trk[0, 1]) - int(LEAD_S * fps))
        f_hi = int(trk[-1, 1]) + int(TAIL_S * fps)
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
            gg1 = (int(g1[0] * scale), int(g1[1] * scale))
            gg2 = (int(g2[0] * scale), int(g2[1] * scale))
            cv2.line(img, gg1, gg2, BLACK, 5)
            cv2.line(img, gg1, gg2, MAGENTA, 2)
            pts = trk[trk[:, 1] <= fno]
            if len(pts) >= 2:
                pl = (pts[:, 2:4] * scale).astype(int)
                cv2.polylines(img, [pl], False, BLACK, 4)
                cv2.polylines(img, [pl], False, BLUE, 2)
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
        out = Path(f"screenshots/c1_phantom_{i}.gif")
        q = [f.quantize(96, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"clip {i} ({lab}): track {tid} dist={dist:.0f}px "
              f"{len(frames)} frames -> {out} "
              f"({out.stat().st_size//1024} KB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
