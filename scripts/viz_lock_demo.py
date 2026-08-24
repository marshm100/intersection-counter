"""Stage-4 lock-persistence demo — tracks from any dump variant on real
frames. For each requested tid: the track polyline (gaps drawn dotted),
birth/death markers, and per-track caption with life + max gap.

Usage:
  py -X utf8 scripts/viz_lock_demo.py --variant s4_study_1100 --tids 4113
  py -X utf8 scripts/viz_lock_demo.py --variant study_1100 --tids 3169,3172 \
      --tag stockfrags --frame 1032200
Writes screenshots/lockdemo_<tag>_<variant>.png (one image, all tids).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from auto_calibrate_viz import load_video_frame                       # noqa: E402
from backend.database import leg_geometry_for_camera                  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir       # noqa: E402
from backend.services.two_pass import _camera_parquet, _tracks_from_rows  # noqa: E402

PROJ = "97a7849a"
FPS = 25.0
COLORS = [(80, 220, 80), (60, 60, 230), (0, 165, 255), (255, 200, 0),
          (200, 80, 220), (60, 200, 200), (255, 120, 120), (30, 120, 255)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True)
    ap.add_argument("--tids", required=True)
    ap.add_argument("--camera", type=int, default=2)
    ap.add_argument("--frame", type=int, default=None)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    cam = args.camera

    tracks = _tracks_from_rows(load_dump(tracks_dir(
        _camera_parquet(PROJ, cam, args.variant))))
    geom = leg_geometry_for_camera(PROJ, cam)
    drawn = {lid: g["gate"] for lid, g in geom.items() if g["gate"]}

    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath = con.execute("SELECT path FROM videos WHERE camera_id=?",
                        (cam,)).fetchone()[0]
    con.close()

    tids = [int(x) for x in args.tids.split(",")]
    all_pts = sorted(tracks[tids[0]])
    mid_f = args.frame or all_pts[len(all_pts) // 2][0]
    img = load_video_frame(vpath, mid_f / FPS)
    if img is None:
        img = cv2.imread(f"data/projects/{PROJ}/calibration_backdrop_cam{cam}.png")
    img = img.copy()
    for _g, (g1, g2) in drawn.items():
        cv2.line(img, (int(g1[0]), int(g1[1])), (int(g2[0]), int(g2[1])),
                 (255, 0, 255), 2, cv2.LINE_AA)

    lines = [f"{args.variant}  cam{cam}  frame {int(mid_f)}"]
    for k, tid in enumerate(tids):
        pts = sorted(tracks[tid])
        col = COLORS[k % len(COLORS)]
        fr = np.array([p[0] for p in pts])
        gaps = np.flatnonzero(np.diff(fr) > 12)
        segs, start = [], 0
        for gi in gaps:
            segs.append(pts[start:gi + 1]); start = gi + 1
        segs.append(pts[start:])
        for seg in segs:
            arr = np.array([[int(p[1]), int(p[2])] for p in seg], np.int32)
            if len(arr) > 1:
                cv2.polylines(img, [arr], False, col, 2, cv2.LINE_AA)
        for gi in gaps:                      # dotted occlusion bridges
            p, q = pts[gi], pts[gi + 1]
            a = np.array([p[1], p[2]]); b = np.array([q[1], q[2]])
            n = max(int(np.hypot(*(b - a)) / 8), 1)
            for i in range(0, n + 1, 2):
                c = a + (b - a) * (i / max(n, 1))
                cv2.circle(img, (int(c[0]), int(c[1])), 2,
                           (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(img, (int(pts[0][1]), int(pts[0][2])), 4,
                   (0, 230, 230), -1, cv2.LINE_AA)
        cv2.circle(img, (int(pts[-1][1]), int(pts[-1][2])), 5, col, -1,
                   cv2.LINE_AA)
        maxgap = int(np.diff(fr).max()) if len(fr) > 1 else 0
        cname = ["GREEN", "RED", "ORANGE", "CYAN", "PURPLE", "TEAL",
                 "PINK", "BLUE"][k % 8]
        lines.append(
            f"tid {tid} ({cname}): {len(pts)} pts, life "
            f"{(fr[-1]-fr[0])/FPS:.1f}s, longest occlusion {maxgap/FPS:.1f}s")

    strip = np.zeros((18 * len(lines) + 10, img.shape[1], 3), np.uint8)
    for i, ln in enumerate(lines):
        cv2.putText(strip, ln[:110], (8, 18 * (i + 1)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (230, 230, 230), 1,
                    cv2.LINE_AA)
    tag = args.tag or f"tid{tids[0]}"
    out = f"screenshots/lockdemo_{tag}_{args.variant}.png"
    cv2.imwrite(out, np.vstack([img, strip]))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
