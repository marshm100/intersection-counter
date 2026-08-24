"""Track Repair Stage-0 demo — the A3 cut, shown on real vehicles.

What the picture proves: the operator's splice diagnosis, executed. For each
requested vehicle: the full raw track, the cut point(s) the ported cutter
found (Type-1 first-exit / Type-2 pinch), segment 1 (the real vehicle) vs the
discarded splice tail, and each segment's gate verdict.

Usage:
  py -X utf8 scripts/viz_trackrepair_demo.py --window study_0700 --tids 37
Writes screenshots/trackrepair_demo_cam2_tid<id>.png
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from auto_calibrate_viz import load_video_frame                       # noqa: E402
from v2_common import fit_motion_residual, load_table                 # noqa: E402
from backend.database import leg_geometry_for_camera, list_paths_for_camera  # noqa: E402
from backend.services.entry_gates import build_gates, classify        # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir       # noqa: E402
from backend.services.track_cut import FALLBACK_KIN, cut_track        # noqa: E402
from backend.services.two_pass import (                               # noqa: E402
    _camera_parquet, _tracks_from_rows, gate_axes_for,
)

PROJ = "97a7849a"
FPS = 25.0
SEG_COLORS = [(80, 220, 80), (60, 60, 230), (0, 165, 255), (255, 200, 0)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="study_0700")
    ap.add_argument("--tids", required=True)
    ap.add_argument("--camera", type=int, default=2)
    args = ap.parse_args()
    cam = args.camera

    rows = load_dump(tracks_dir(_camera_parquet(PROJ, cam, args.window)))
    tracks = _tracks_from_rows(rows)
    geom = leg_geometry_for_camera(PROJ, cam)
    mouths = {lid: g["mouth"] for lid, g in geom.items()}
    heads = {lid: g["heading"] for lid, g in geom.items()}
    drawn = {lid: g["gate"] for lid, g in geom.items() if g["gate"]}
    gates = build_gates(mouths, list_paths_for_camera(PROJ, cam), heads,
                        leg_axes=gate_axes_for(mouths, tracks.values()),
                        leg_gates=drawn or None)

    npz = Path("runs/v2_week1") / f"tracklets_cam{cam}_{args.window}.npz"
    kin = (fit_motion_residual(load_table(npz)) if npz.exists()
           else dict(FALLBACK_KIN))
    kin_src = "fitted" if npz.exists() else "fallback"

    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    vpath = con.execute("SELECT path FROM videos WHERE camera_id=?",
                        (cam,)).fetchone()[0]

    for tid in (int(x) for x in args.tids.split(",")):
        pts = sorted(tracks[tid])
        segments, records = cut_track(pts, gates, FPS, kin)
        o0, d0, *_r, tag0 = classify(pts, gates, FPS)

        ev = con.execute(
            "SELECT movement, origin_leg_id, destination_leg_id FROM vehicle_events "
            "WHERE camera_id=? AND vehicle_track_id=? AND COALESCE(rejected,0)=0",
            (cam, tid)).fetchone()
        counted = f"counted as '{ev[0]}' {ev[1]}->{ev[2]}" if ev else "not counted"

        mid_f = pts[len(pts) // 2][0]
        img = load_video_frame(vpath, mid_f / FPS)
        if img is None:
            img = cv2.imread(f"data/projects/{PROJ}/calibration_backdrop_cam{cam}.png")
        img = img.copy()
        for glid, (g1, g2) in drawn.items():
            cv2.line(img, (int(g1[0]), int(g1[1])), (int(g2[0]), int(g2[1])),
                     (255, 0, 255), 2, cv2.LINE_AA)

        lines = [f"tid {tid}  cam{cam} {args.window}  |  {len(pts)} pts  |  "
                 f"today: {counted}  (uncut gate tag: {tag0})",
                 f"cutter found {len(records)} cut(s) "
                 + "; ".join(f"{r[1].get('rule')}@f{int(r[0])}" for r in records[:3])
                 + f"  (kin: {kin_src})"]
        for k, seg in enumerate(segments):
            arr = np.array([[int(p[1]), int(p[2])] for p in seg], np.int32)
            col = SEG_COLORS[k % len(SEG_COLORS)]
            cv2.polylines(img, [arr], False, col, 2, cv2.LINE_AA)
            cv2.circle(img, tuple(arr[0]), 4, (0, 230, 230), -1, cv2.LINE_AA)
            cv2.circle(img, tuple(arr[-1]), 5, col, -1, cv2.LINE_AA)
            so, sd, *_sr, stag = classify(seg, gates, FPS)
            lines.append(
                f"segment {k+1} ({['GREEN','RED','ORANGE','CYAN'][k % 4]}, "
                f"{len(seg)} pts): gate verdict {stag}"
                + (f" {so}->{sd}" if stag == 'full' else "")
                + ("  <- a REAL vehicle's journey, counted on its own"
                   if stag == 'full'
                   else "  <- debris, not counted"))
        # cut markers
        for f, diag in records:
            near = min(pts, key=lambda p: abs(p[0] - f))
            x, y = int(near[1]), int(near[2])
            cv2.drawMarker(img, (x, y), (0, 255, 255), cv2.MARKER_TILTED_CROSS,
                           18, 2, cv2.LINE_AA)
        if not records:
            lines.append("no cuts fired - track is clean under the validated rules")

        strip = np.zeros((18 * len(lines) + 10, img.shape[1], 3), np.uint8)
        for i, ln in enumerate(lines):
            cv2.putText(strip, ln[:100], (8, 18 * (i + 1)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (230, 230, 230), 1,
                        cv2.LINE_AA)
        out = f"screenshots/trackrepair_demo_cam{cam}_tid{tid}.png"
        cv2.imwrite(out, np.vstack([img, strip]))
        print(f"wrote {out}  cuts={len(records)} segments={len(segments)}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
