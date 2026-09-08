"""Cam5 gate-coverage evidence (operator request 2026-09-08).

Half A: one overview frame — the four drawn gates, plus the
  ground-contact trails of COUNTED vehicles that never crossed any
  gate (green) against those that did (dim blue). Shows which lanes
  the gates fail to witness.
Half B: three clips of long, obviously-real vehicles whose whole
  journey never touches a gate line.

Read-only. Writes screenshots/c5_gate_coverage.png and
screenshots/c5_unwitnessed_{1,2,3}.gif
"""
from __future__ import annotations

import json
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
GREEN, DIMBLUE, MAGENTA, BLACK, WHITE = ((60, 255, 60), (150, 90, 40),
                                         (255, 0, 220), (0, 0, 0),
                                         (255, 255, 255))
MIN_SPAN = 300.0        # only long, obviously-real journeys


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
    counted = {int(t): mv for t, mv in s.execute(
        "SELECT vehicle_track_id, movement FROM vehicle_events "
        "WHERE camera_id=? AND rejected=0", (CAM,))}
    s.close()

    wit, unwit = [], []
    for tid in np.unique(rows[:, 0]):
        tid = int(tid)
        if tid not in counted:
            continue
        trk = rows[rows[:, 0] == float(tid)]
        if len(trk) < 5:
            continue
        span = float(np.hypot(trk[-1, 2] - trk[0, 2], trk[-1, 3] - trk[0, 3]))
        if span < MIN_SPAN:
            continue
        pts = sorted((float(r[1]), float(r[2]), float(r[3])) for r in trk)
        tag = classify(pts, gates, fps)[-1]
        (unwit if tag == "no_crossing" else wit).append((tid, trk, span))
    print(f"long counted journeys (>= {MIN_SPAN:.0f} px): "
          f"{len(wit)} witnessed, {len(unwit)} NEVER witnessed")

    cap = cv2.VideoCapture(vpath)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(rows[len(rows) // 2, 1]))
    ok, base = cap.read()
    cap.release()
    img = base.copy()
    over = img.copy()
    for _tid, trk, _sp in wit:
        gl = np.stack([trk[:, 2], trk[:, 3] + trk[:, 5] / 2.0], axis=1)
        cv2.polylines(over, [gl.astype(int)], False, DIMBLUE, 1)
    for _tid, trk, _sp in unwit:
        gl = np.stack([trk[:, 2], trk[:, 3] + trk[:, 5] / 2.0], axis=1)
        cv2.polylines(over, [gl.astype(int)], False, GREEN, 1)
    img = cv2.addWeighted(over, 0.75, img, 0.25, 0)
    for lg, (p1, p2, _nrm) in gates.items():
        a = (int(p1[0]), int(p1[1]))
        b = (int(p2[0]), int(p2[1]))
        cv2.line(img, a, b, BLACK, 7)
        cv2.line(img, a, b, MAGENTA, 3)
        lab = legs.get(lg, str(lg))
        cv2.putText(img, lab, (a[0] + 4, a[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, BLACK, 5)
        cv2.putText(img, lab, (a[0] + 4, a[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, MAGENTA, 2)
    big = cv2.resize(img, (1280, int(img.shape[0] * 1280 / img.shape[1])))
    out = Path("screenshots/c5_gate_coverage.png")
    cv2.imwrite(str(out), big)
    print(f"overview -> {out} ({out.stat().st_size // 1024} KB)")

    unwit.sort(key=lambda u: -u[2])
    for i, (tid, trk, span) in enumerate(unwit[:3], 1):
        f_lo = max(0, int(trk[0, 1]) - int(1.5 * fps))
        f_hi = int(trk[-1, 1]) + int(2 * fps)
        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        frames = []
        for fno in range(f_lo, f_hi):
            ok, fr = cap.read()
            if not ok:
                break
            if (fno - f_lo) % 3:
                continue
            sc = 440 / fr.shape[1]
            im = cv2.resize(fr, (440, int(fr.shape[0] * sc)))
            for lg, (p1, p2, _nrm) in gates.items():
                a = (int(p1[0] * sc), int(p1[1] * sc))
                b = (int(p2[0] * sc), int(p2[1] * sc))
                cv2.line(im, a, b, BLACK, 5)
                cv2.line(im, a, b, MAGENTA, 2)
            pts = trk[trk[:, 1] <= fno]
            if len(pts) >= 2:
                gl = np.stack([pts[:, 2],
                               pts[:, 3] + pts[:, 5] / 2.0], axis=1)
                cv2.polylines(im, [(gl * sc).astype(int)], False, BLACK, 4)
                cv2.polylines(im, [(gl * sc).astype(int)], False, GREEN, 2)
            if len(pts) and fno <= trk[-1, 1]:
                p = pts[-1]
                x, y = int(p[2] * sc), int(p[3] * sc)
                bw = max(int(p[4] * sc / 2), 5)
                bh = max(int(p[5] * sc / 2), 5)
                cv2.rectangle(im, (x - bw, y - bh), (x + bw, y + bh),
                              BLACK, 4)
                cv2.rectangle(im, (x - bw, y - bh), (x + bw, y + bh),
                              GREEN, 2)
            frames.append(Image.fromarray(cv2.cvtColor(im,
                                                       cv2.COLOR_BGR2RGB)))
        cap.release()
        o = Path(f"screenshots/c5_unwitnessed_{i}.gif")
        q = [f.quantize(72, dither=Image.Dither.NONE) for f in frames]
        q[0].save(o, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * 3 / fps), loop=0)
        print(f"clip {i}: tid {tid} span {span:.0f}px counted as "
              f"'{counted[tid]}' -> {o} ({o.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
