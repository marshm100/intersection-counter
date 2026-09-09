"""Cam3 SURVIVING u-turns (G-FX-1 follow-up, 2026-09-08).

After the first-exit rule, 44 u-turn events remain on cam3 and 36 of
them carry posterior_source 'gate_full' — the gate evidence itself
calls them u-turns, so their FIRST legitimate exit really is the same
leg and it passes the dwell/excursion/lane tests.

This films those, spanning entry crossing -> exit crossing (the
pertinent journey only, not the whole track life), with both bottom
corners drawn and the crossing frames annotated.

Read-only. Writes screenshots/c2_reversal_{n}.gif
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
CAM, VARIANT = 2, "study_0700"
STEM = ("data/projects/97a7849a/_replay_scratch/fleet_20260908/"
        "ff_cam2_study_0700.db")
LEAD, TRAIL = (60, 255, 60), (0, 165, 255)
MAGENTA, BLACK, WHITE = (255, 0, 220), (0, 0, 0), (255, 255, 255)
W_OUT, STEP, N_CLIPS = 440, 3, 3


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

    s = sqlite3.connect(f"file:{STEM}?mode=ro", uri=True)
    cands = [(t, "EB") for t in (17428, 17526, 18607)]
    s.close()

    td = tracks_dir(parquet_path(PROJ, CAM, chash, VARIANT))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])

    made = 0
    for tid, ocard in cands:
        if made >= N_CLIPS:
            break
        trk = rows[rows[:, 0] == float(tid)]
        if len(trk) < 20:
            continue
        pts = [(float(r[1]), float(r[2]), float(r[3]) + float(r[5]) / 2)
               for r in trk]
        xs = all_crossings(pts, gates, fps)
        ent = [x for x in xs if x[2]]
        ex = [x for x in xs if not x[2]]
        if not ent or not ex:
            continue
        f_in = int(ent[0][0])
        after = [x for x in ex if x[0] > ent[0][0]]
        if not after:
            continue
        f_out = int(after[0][0])
        if f_out - f_in > 90 * fps:          # keep the clip watchable
            continue
        f_lo = max(0, f_in - int(2 * fps))
        f_hi = f_out + int(3 * fps)
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
            lab = ("ENTERING" if fno < f_out else "EXITED")
            cv2.putText(im, lab, (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, BLACK, 4)
            cv2.putText(im, lab, (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, WHITE, 1)
            seen = trk[trk[:, 1] <= fno]
            if len(seen) >= 2:
                for sign, col in ((-1.0, LEAD), (1.0, TRAIL)):
                    c = np.stack([seen[:, 2] + sign * seen[:, 4] / 2.0,
                                  seen[:, 3] + seen[:, 5] / 2.0], axis=1)
                    cv2.polylines(im, [(c * sc).astype(int)], False,
                                  BLACK, 4)
                    cv2.polylines(im, [(c * sc).astype(int)], False, col, 2)
            if len(seen) and fno <= trk[-1, 1]:
                p = seen[-1]
                x1, x2 = (int((p[2] - p[4] / 2) * sc),
                          int((p[2] + p[4] / 2) * sc))
                y1, y2 = (int((p[3] - p[5] / 2) * sc),
                          int((p[3] + p[5] / 2) * sc))
                cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 4)
                cv2.rectangle(im, (x1, y1), (x2, y2), WHITE, 1)
                cv2.line(im, (x1, y2), (x2, y2), BLACK, 5)
                cv2.line(im, (x1, y2), (x2, y2), WHITE, 2)
            frames.append(Image.fromarray(cv2.cvtColor(im,
                                                       cv2.COLOR_BGR2RGB)))
        cap.release()
        if len(frames) < 8:
            continue
        made += 1
        out = Path(f"screenshots/c2_reversal_{made}.gif")
        q = [f.quantize(72, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"clip {made}: tid {tid} {ocard}->{ocard} labelled RIGHT, in@{f_in} "
              f"out@{f_out} ({(f_out-f_in)/fps:.1f}s) -> {out} "
              f"({out.stat().st_size // 1024} KB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
