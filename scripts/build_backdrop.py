"""Detection-density calibration backdrop — gate drawing without the video.

The source videos live on a OneDrive this machine no longer has (2026-08-23);
the calibration canvas needs a background image in VIDEO PIXEL coordinates.
The detection caches hold millions of per-frame vehicle bboxes in exactly that
coordinate space, so a density render of detection CENTERS is a long-exposure
photograph of where traffic flows — and centers are precisely the geometry
gates cut (all_crossings walks tracks of detection centers), which makes this
arguably a better gate-placement backdrop than any single frame.

Writes data/projects/<pid>/calibration_backdrop_cam<N>.png at the video's
native resolution. The /videos/{id}/frame endpoint serves it as a fallback
when the video file is gone (backend/routers/videos.py).

  py scripts/build_backdrop.py --project 97a7849a            # all cameras
  py scripts/build_backdrop.py --project 97a7849a --camera 2
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")


def build_for_camera(project_id: str, camera_id: int, width: int, height: int) -> Path | None:
    import pyarrow.parquet as pq

    cam_root = Path("data/projects") / project_id / "detections" / str(camera_id)
    if not cam_root.is_dir():
        print(f"  cam{camera_id}: no detection cache — skipped")
        return None

    acc = np.zeros((height, width), dtype=np.float64)
    n_total = 0
    for hash_dir in sorted(d for d in cam_root.iterdir() if d.is_dir()):
        for pf in sorted(hash_dir.glob("*.parquet")):
            try:
                t = pq.read_table(pf, columns=["bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2"])
            except Exception as e:
                print(f"  cam{camera_id}: unreadable {pf.name}: {e}")
                continue
            x = ((t["bbox_x1"].to_numpy() + t["bbox_x2"].to_numpy()) / 2.0)
            y = ((t["bbox_y1"].to_numpy() + t["bbox_y2"].to_numpy()) / 2.0)
            xi = np.clip(x.astype(np.int32), 0, width - 1)
            yi = np.clip(y.astype(np.int32), 0, height - 1)
            np.add.at(acc, (yi, xi), 1.0)
            n_total += len(xi)

    if n_total == 0:
        print(f"  cam{camera_id}: cache empty — skipped")
        return None

    # Log compression, then a dark-to-bright ramp. Grayscale keeps the canvas
    # overlays (legs, channels, gate lines) maximally legible on top.
    img = np.log1p(acc)
    img /= img.max()
    # mild gamma lift so faint single-lane ribbons stay visible
    img = np.power(img, 0.6)
    gray = (img * 235.0).astype(np.uint8)  # cap below 255: overlays stay brighter

    import cv2
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    label = "DETECTION DENSITY BACKDROP - no video on disk"
    cv2.putText(bgr, label, (8, height - 10), cv2.FONT_HERSHEY_SIMPLEX,
                0.38, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(bgr, label, (8, height - 10), cv2.FONT_HERSHEY_SIMPLEX,
                0.38, (80, 200, 255), 1, cv2.LINE_AA)

    out = Path("data/projects") / project_id / f"calibration_backdrop_cam{camera_id}.png"
    cv2.imwrite(str(out), bgr)
    print(f"  cam{camera_id}: {n_total:,} detections -> {out} ({width}x{height})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=None)
    args = ap.parse_args()

    db = f"data/projects/{args.project}/project.db"
    con = sqlite3.connect(f"file:{db.replace(os.sep, '/')}?mode=ro&immutable=1", uri=True)
    cams = con.execute(
        "SELECT camera_id, width, height FROM videos ORDER BY camera_id").fetchall()
    con.close()

    for cam, w, h in cams:
        if args.camera is not None and cam != args.camera:
            continue
        build_for_camera(args.project, cam, int(w), int(h))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
