"""Validate whether higher-recall detection captures the TURN CURVES + entries.

Run AFTER an accurate (yolo26l@1280) reprocess of the window. Measures, on the
regenerated events + the detection cache, the three things that decide whether a
robust turn fix is even possible from the observed data:
  1. detection spatial coverage on the arterial band (do boxes reach the entry edge),
  2. through-track completeness (median start_x, % at entry edge, x-span covered),
  3. whether clean PERPENDICULAR turns (entry sector != exit sector) now appear.

Compares against the BALANCED yolo26s@960 baseline (printed inline). The question
this answers: is the turn signal recoverable with better detection, or is it
physically gone (camera FOV/occlusion)?

Usage:  py scripts/validate_recall.py
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import (
    compute_video_content_hash, parquet_path, read_metadata,
)
from backend.services.trajectory_classifier import _exit_velocity
from replay_attribution_changes import PROJECT_DB, load_events

# Balanced yolo26s@960 baseline (measured 2026-05-28/29) for side-by-side.
BASE = {"EB_start_med": 418, "EB_edge_pct": 5, "EB_xspan_med": 139,
        "band_x_p5": 177, "clean_perp_turns": "~2 (E->N=1,W->N=1)"}
DIRS = {"E": 83.0, "W": 262.0, "N": 353.0, "S": 173.0}


def _heading(p, q):
    return math.degrees(math.atan2(q[0] - p[0], -(q[1] - p[1]))) % 360


def _entry_heading(traj, min_dist=30.0):
    p0 = traj[0]
    for q in traj[1:]:
        if math.hypot(q[0] - p0[0], q[1] - p0[1]) >= min_dist:
            return _heading(p0, q)
    return _heading(traj[0], traj[-1])


def _exit_heading(traj):
    vx, vy = _exit_velocity(traj)
    return math.degrees(math.atan2(vx, -vy)) % 360


def _sector(deg):
    return min(DIRS, key=lambda k: abs((deg - DIRS[k] + 180) % 360 - 180))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    args = ap.parse_args()

    conn = sqlite3.connect(str(PROJECT_DB))
    v = conn.execute("SELECT path,file_size_bytes,total_frames FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
                     (args.camera,)).fetchone()
    chash, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pqp = parquet_path(args.project, args.camera, chash)
    meta = read_metadata(pqp) or {}
    print(f"=== cache: {pqp.name}  model={meta.get('model')} imgsz={meta.get('imgsz')} "
          f"conf={meta.get('confidence')} ===")

    # 1) detection spatial coverage on the arterial band
    t = pq.read_table(pqp).to_pandas()
    cx = (t["bbox_x1"] + t["bbox_x2"]) / 2; cy = (t["bbox_y1"] + t["bbox_y2"]) / 2
    area = (t["bbox_x2"] - t["bbox_x1"]) * (t["bbox_y2"] - t["bbox_y1"])
    band = (cy > 195) & (cy < 265)
    print(f"\n[1] DETECTION COVERAGE  total={len(t)}  band={int(band.sum())}")
    print(f"    band center_x p5={np.percentile(cx[band],5):.0f} (balanced {BASE['band_x_p5']})  "
          f"p10={np.percentile(cx[band],10):.0f}  med={cx[band].median():.0f}")
    print(f"    band dets x<120: {int((cx[band]<120).sum())}  box area med={np.median(area[band]):.0f}px^2")

    # 2/3) trajectory completeness + turn capture
    ev = load_events(conn); conn.close()
    trajs = [e["trajectory"] for e in ev if e["trajectory"] and len(e["trajectory"]) >= 4]
    sx = np.array([tj[0][0] for tj in trajs]); ex = np.array([tj[-1][0] for tj in trajs])
    eb = (ex - sx) > 100
    print(f"\n[2] THROUGH COMPLETENESS  events={len(trajs)}  eastbound={int(eb.sum())}")
    if eb.any():
        ebx = sx[eb]; span = np.abs(ex[eb] - ebx)
        print(f"    EB start_x med={np.median(ebx):.0f} (balanced {BASE['EB_start_med']})  "
              f"edge x<60={np.mean(ebx<60)*100:.0f}% (balanced {BASE['EB_edge_pct']}%)  "
              f"x-span med={np.median(span):.0f}px (balanced {BASE['EB_xspan_med']})")

    sectors = [( _sector(_entry_heading(tj)), _sector(_exit_heading(tj))) for tj in trajs]
    perp = [(en, ex_) for en, ex_ in sectors if en != ex_ and {en, ex_} not in ({"E", "W"},)]
    print(f"\n[3] TURN CAPTURE  geometric turners (entry!=exit)={sum(1 for a,b in sectors if a!=b)}")
    print(f"    clean PERPENDICULAR turns (to/from N or S)={len(perp)} "
          f"(balanced {BASE['clean_perp_turns']})")
    for k, n in Counter(perp).most_common(8):
        print(f"      {k[0]}->{k[1]}  n={n}")
    print("\nVERDICT: if EB start_x moved toward the edge, x-span grew, AND perpendicular")
    print("turns jumped vs balanced -> recall recovers turns. If turns are still ~absent,")
    print("the curve is physically gone (camera FOV) and detection alone won't fix turns.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
