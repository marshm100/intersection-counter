"""Identity-stack validation harness — the operator's labeled thefts vs a
candidate re-tracked dump.

The 36 review_log bad_track rulings (R0, 2026-08-24/25) are tids on the
PRODUCTION study dumps. For each label: locate the theft moment on the
production track (the cutter's flip/cut frame — the same validated
signature the operator confirmed), then check the CANDIDATE dump: an
identity that still spans from the pre-theft position to the post-theft
position (spatio-temporal re-match; tid spaces differ) means the theft
survived. Severed = the candidate tracker broke identity at the theft.

Usage:
  py -X utf8 scripts/validate_labeled_splices.py --candidate s4_study_1600
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import numpy as np

from backend.database import (
    leg_geometry_for_camera, list_paths_for_camera, list_review_log,
)
from backend.services.entry_gates import build_gates
from backend.services.pass2_replay import load_dump, tracks_dir
from backend.services.track_cut import FALLBACK_KIN, cut_track
from backend.services.two_pass import _tracks_from_rows, gate_axes_for
from backend.services.detection_cache import parquet_path

PROJ = "97a7849a"
NEAR_PX = 40.0
PAD_S = 2.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--base", default="study_1600")
    ap.add_argument("--camera", type=int, default=2)
    args = ap.parse_args()
    cam = args.camera

    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    chash = con.execute("SELECT content_hash FROM videos WHERE camera_id=?",
                        (cam,)).fetchone()[0]
    fps = float(con.execute("SELECT fps FROM videos WHERE camera_id=?",
                            (cam,)).fetchone()[0])
    con.close()

    labels = sorted({r["source_tid"] for r in list_review_log(PROJ)
                     if r["action"] == "bad_track"
                     and r["source_tid"] is not None})
    base = _tracks_from_rows(load_dump(tracks_dir(
        parquet_path(PROJ, cam, chash, args.base))))
    cand = _tracks_from_rows(load_dump(tracks_dir(
        parquet_path(PROJ, cam, chash, args.candidate))))

    geom = leg_geometry_for_camera(PROJ, cam)
    mouths = {l: g["mouth"] for l, g in geom.items()}
    heads = {l: g["heading"] for l, g in geom.items()}
    drawn = {l: g["gate"] for l, g in geom.items() if g.get("gate")}
    gates = build_gates(mouths, list_paths_for_camera(PROJ, cam), heads,
                        leg_axes=gate_axes_for(mouths, base.values()),
                        leg_gates=drawn or None)

    kin = dict(FALLBACK_KIN)
    severed = carried = unlocatable = 0
    for tid in labels:
        pts = sorted(base.get(tid, []))
        if len(pts) < 5:
            unlocatable += 1
            continue
        _segs, records = cut_track(pts, gates, fps, kin)
        theft_f = records[0][0] if records else pts[len(pts) // 2][0]
        pre = min(pts, key=lambda p: abs(p[0] - (theft_f - PAD_S * fps)))
        post = min(pts, key=lambda p: abs(p[0] - (theft_f + PAD_S * fps)))
        if pre[0] >= post[0]:
            unlocatable += 1
            continue

        def near(track_pts, ref):
            return any(abs(p[0] - ref[0]) <= PAD_S * fps
                       and math.hypot(p[1] - ref[1], p[2] - ref[2])
                       <= NEAR_PX for p in track_pts)

        carried_here = False
        for _ct, cpts in cand.items():
            cs = sorted(cpts)
            if cs[-1][0] < pre[0] or cs[0][0] > post[0]:
                continue
            if near(cs, pre) and near(cs, post):
                carried_here = True
                break
        if carried_here:
            carried += 1
        else:
            severed += 1

    n = len(labels)
    print(f"labeled thefts: {n}  (base {args.base} -> candidate "
          f"{args.candidate})")
    print(f"  SEVERED (identity broken at the theft): {severed}")
    print(f"  CARRIED (theft survived):               {carried}")
    print(f"  unlocatable (short/edge tracks):        {unlocatable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
