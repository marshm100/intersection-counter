"""Cam5 contradicted-origin evidence (operator request 2026-09-08).

Clip 1 (tid 116990) was counted origin=W ("left") while its bottom
edge visibly crossed the S line — S->N is a THROUGH, which is what
the operator ruled it. This finds every counted event whose ASSIGNED
origin is contradicted by the ground-anchored gate evidence, and
films the largest ones.

Read-only. Writes screenshots/c5_wrongorigin_{n}.gif
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
from backend.services.entry_gates import build_gates, classify  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
CAM, VARIANT = 5, "l1_study_1100"
LEAD, TRAIL = (60, 255, 60), (0, 165, 255)
MAGENTA, BLACK, WHITE = (255, 0, 220), (0, 0, 0), (255, 255, 255)
W_OUT, STEP, N_CLIPS = 440, 3, 3


def entry_of(trk, gates, fps):
    """Ground-anchored ENTRY leg: both bottom corners must agree."""
    outs = []
    for sign in (-1.0, 1.0):
        pts = sorted((float(r[1]),
                      float(r[2]) + sign * float(r[4]) / 2.0,
                      float(r[3]) + float(r[5]) / 2.0) for r in trk)
        outs.append(classify(pts, gates, fps)[0])
    return outs[0] if outs[0] == outs[1] else None


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

    td = tracks_dir(parquet_path(PROJ, CAM, chash, VARIANT))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])

    s = sqlite3.connect(
        f"file:data/projects/{PROJ}/_replay_scratch/c45_20260907/"
        f"cx_cam{CAM}_study_1100.db?mode=ro", uri=True)
    ev = list(s.execute(
        "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
        "movement, destination_confidence FROM vehicle_events "
        "WHERE camera_id=? AND rejected=0", (CAM,)))
    s.close()

    bad = []
    for tid, o, d, mv, conf in ev:
        trk = rows[rows[:, 0] == float(tid)]
        if len(trk) < 5:
            continue
        ge = entry_of(trk, gates, fps)
        if ge is not None and ge != o:
            span = float(np.hypot(trk[-1, 2] - trk[0, 2],
                                  trk[-1, 3] - trk[0, 3]))
            bad.append((span, int(tid), o, ge, d, mv, conf, trk))
    bad.sort(key=lambda b: -b[0])
    print(f"counted events whose ASSIGNED origin is contradicted by the "
          f"ground gate evidence: {len(bad)}")
    for span, tid, o, ge, d, mv, conf, _t in bad[:12]:
        print(f"   tid {tid:>7} span {span:>4.0f}px  assigned "
              f"{legs.get(o)}->{legs.get(d)} '{mv}' (conf "
              f"{conf if conf is None else round(conf, 2)})  but entered "
              f"over {legs.get(ge)}")

    for i, (span, tid, o, ge, d, mv, conf, trk) in enumerate(
            bad[:N_CLIPS], 1):
        f_lo = max(0, int(trk[0, 1]) - int(1.5 * fps))
        f_hi = int(trk[-1, 1]) + int(2 * fps)
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
            pts = trk[trk[:, 1] <= fno]
            if len(pts) >= 2:
                for sign, col in ((-1.0, LEAD), (1.0, TRAIL)):
                    c = np.stack([pts[:, 2] + sign * pts[:, 4] / 2.0,
                                  pts[:, 3] + pts[:, 5] / 2.0], axis=1)
                    cv2.polylines(im, [(c * sc).astype(int)], False,
                                  BLACK, 4)
                    cv2.polylines(im, [(c * sc).astype(int)], False, col, 2)
            if len(pts) and fno <= trk[-1, 1]:
                p = pts[-1]
                x1, x2 = int((p[2] - p[4] / 2) * sc), int((p[2] + p[4] / 2) * sc)
                y1, y2 = int((p[3] - p[5] / 2) * sc), int((p[3] + p[5] / 2) * sc)
                cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 4)
                cv2.rectangle(im, (x1, y1), (x2, y2), WHITE, 1)
                cv2.line(im, (x1, y2), (x2, y2), BLACK, 5)
                cv2.line(im, (x1, y2), (x2, y2), WHITE, 2)
            frames.append(Image.fromarray(cv2.cvtColor(im,
                                                       cv2.COLOR_BGR2RGB)))
        cap.release()
        out = Path(f"screenshots/c5_wrongorigin_{i}.gif")
        q = [f.quantize(72, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"clip {i}: tid {tid} counted '{legs.get(o)} {mv}', entered "
              f"over {legs.get(ge)} -> {out} "
              f"({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
