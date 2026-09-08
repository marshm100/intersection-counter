"""Cam3 phantom u-turn reel (G-FLEET-1 blocker, 2026-09-08).

cam3 counts 88 southbound u-turns where Miovision counted ZERO. Their
net heading change is -170 to -175 degrees — a full reversal, the
classic identity-swap signature. This films the REVERSAL MOMENT of
the largest ones: the clip centres on the frame where the track's
direction flips, so the operator can see whether one vehicle turned
around or the box jumped to an oncoming vehicle.

Read-only. Writes screenshots/c3_uturn_{n}.gif
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
from backend.services.entry_gates import build_gates  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
CAM, VARIANT = 3, "study_0600"
STEM = ("data/projects/97a7849a/_replay_scratch/fleet_20260908/"
        "ff_cam3_study_0600.db")
BEFORE, AFTER = (60, 255, 60), (0, 165, 255)   # green pre-flip, orange post
MAGENTA, BLACK, WHITE = (255, 0, 220), (0, 0, 0), (255, 255, 255)
W_OUT, STEP, SPAN_S, N_CLIPS = 440, 3, 7.0, 3


def flip_frame(trk, win=25):
    """Frame index (into trk) where travel direction reverses hardest."""
    best_i, best = None, 0.0
    for i in range(win, len(trk) - win):
        ax = trk[i, 2] - trk[i - win, 2]
        ay = trk[i, 3] - trk[i - win, 3]
        bx = trk[i + win, 2] - trk[i, 2]
        by = trk[i + win, 3] - trk[i, 3]
        na = (ax * ax + ay * ay) ** 0.5
        nb = (bx * bx + by * by) ** 0.5
        if na < 8 or nb < 8:
            continue
        cos = (ax * bx + ay * by) / (na * nb)
        if cos < best or best_i is None:
            best_i, best = i, cos
    return best_i


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
    nleg = [k for k, v in legs.items() if v == "N"][0]
    cands = [int(r[0]) for r in s.execute(
        "SELECT vehicle_track_id FROM vehicle_events WHERE camera_id=? AND "
        "rejected=0 AND movement='u_turn' AND origin_leg_id=? "
        "ORDER BY classifier_path_distance DESC LIMIT 12",
        (CAM, nleg))]
    s.close()

    td = tracks_dir(parquet_path(PROJ, CAM, chash, VARIANT))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])

    made = 0
    for tid in cands:
        if made >= N_CLIPS:
            break
        trk = rows[rows[:, 0] == float(tid)]
        if len(trk) < 60:
            continue
        fi = flip_frame(trk)
        if fi is None:
            continue
        f_mid = int(trk[fi, 1])
        f_lo = max(0, f_mid - int(SPAN_S * fps))
        f_hi = f_mid + int(SPAN_S * fps)
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
            seen = trk[trk[:, 1] <= fno]
            for lo, hi, col in ((0, min(fi + 1, len(seen)), BEFORE),
                                (fi, len(seen), AFTER)):
                seg = seen[lo:hi]
                if len(seg) >= 2:
                    gl = np.stack([seg[:, 2],
                                   seg[:, 3] + seg[:, 5] / 2.0], axis=1)
                    cv2.polylines(im, [(gl * sc).astype(int)], False,
                                  BLACK, 4)
                    cv2.polylines(im, [(gl * sc).astype(int)], False, col, 2)
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
        if len(frames) < 10:
            continue
        made += 1
        out = Path(f"screenshots/c3_uturn_{made}.gif")
        q = [f.quantize(72, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"clip {made}: tid {tid} flip at frame {f_mid} "
              f"({len(trk)} pts) -> {out} "
              f"({out.stat().st_size // 1024} KB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
