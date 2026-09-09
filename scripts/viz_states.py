"""Three-state journey labels (operator instrument request 2026-09-09).

He asked for three states instead of two, so the flicker is visible:
  ENTERING   detected, has NOT yet crossed the mouth threshold
  OCCUPYING  has crossed in; it is in the space of the intersection
  EXITED     has crossed an exit threshold

Every crossing flips the state, so a stationary vehicle wobbling
across a line reads as OCCUPYING/EXITED/OCCUPYING/EXITED — his
"entering and occupying noise" — while a clean pass reads as one
long ENTERING, one long OCCUPYING, then EXITED.

Read-only. Writes screenshots/state_{tid}.gif

Usage:  py -X utf8 scripts/viz_states.py CAM VARIANT TID [TID...]
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
from backend.services.entry_gates import all_crossings  # noqa: E402
from backend.services.entry_gates import build_gates  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
STATE_COL = {"ENTERING": (0, 215, 255),      # amber
             "OCCUPYING": (60, 255, 60),     # green
             "EXITED": (255, 70, 20)}        # blue
MAGENTA, BLACK, WHITE = (255, 0, 220), (0, 0, 0), (255, 255, 255)
W_OUT, STEP = 400, 5


def main() -> int:
    cam = int(sys.argv[1])
    variant = sys.argv[2]
    tids = [int(t) for t in sys.argv[3:]]

    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath, chash, fps = con.execute(
        "SELECT path, content_hash, fps FROM videos WHERE camera_id=?",
        (cam,)).fetchone()
    legs = dict(con.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
        (cam,)))
    con.close()
    fps = float(fps)

    geom = leg_geometry_for_camera(PROJ, cam)
    gates = build_gates(
        {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
        list_paths_for_camera(PROJ, cam),
        {lg: g.get("heading") for lg, g in geom.items()},
        leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})

    td = tracks_dir(parquet_path(PROJ, cam, chash, variant))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])

    for tid in tids:
        trk = rows[rows[:, 0] == float(tid)]
        if not len(trk):
            print(f"{tid}: no track")
            continue
        pts = [(float(r[1]), float(r[2]), float(r[3]) + float(r[5]) / 2)
               for r in trk]
        xs = sorted(all_crossings(pts, gates, fps), key=lambda c: c[0])
        # state timeline: every crossing flips inside/outside
        events = [(int(f), "OCCUPYING" if inward else "EXITED", legs.get(lg))
                  for f, lg, inward, _p in xs]
        flicks = sum(1 for i in range(1, len(events))
                     if events[i][1] != events[i - 1][1])
        print(f"tid {tid}: {len(events)} crossings, {flicks} state flips")
        for f, st, lg in events:
            print(f"     f{f}  -> {st:9} ({lg})")

        f_lo = max(0, int(trk[0, 1]) - int(1.0 * fps))
        f_hi = int(trk[-1, 1]) + int(1.5 * fps)
        if f_hi - f_lo > 60 * fps:
            f_hi = f_lo + int(60 * fps)
        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        frames = []
        for fno in range(f_lo, f_hi):
            ok, fr = cap.read()
            if not ok:
                break
            if (fno - f_lo) % STEP:
                continue
            state = "ENTERING"
            for f, st, _lg in events:
                if fno >= f:
                    state = st
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            for lg, (p1, p2, _nrm) in gates.items():
                a = (int(p1[0] * sc), int(p1[1] * sc))
                b = (int(p2[0] * sc), int(p2[1] * sc))
                cv2.line(im, a, b, BLACK, 5)
                cv2.line(im, a, b, MAGENTA, 2)
            col = STATE_COL[state]
            cv2.rectangle(im, (0, 0), (W_OUT, 30), BLACK, -1)
            cv2.putText(im, state, (10, 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.75, col, 2)
            seen = trk[trk[:, 1] <= fno]
            if len(seen) >= 2:
                gl = np.stack([seen[:, 2],
                               seen[:, 3] + seen[:, 5] / 2.0], axis=1)
                cv2.polylines(im, [(gl * sc).astype(int)], False, BLACK, 4)
                cv2.polylines(im, [(gl * sc).astype(int)], False, col, 2)
            if len(seen) and fno <= trk[-1, 1]:
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
        out = Path(f"screenshots/state_{tid}.gif")
        q = [f.quantize(72, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"   -> {out} ({out.stat().st_size // 1024} KB)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
