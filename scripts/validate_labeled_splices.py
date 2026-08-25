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
    tally = {"flip": [0, 0], "dwell": [0, 0]}   # class -> [severed, carried]
    unlocatable = 0
    for tid in labels:
        pts = sorted(base.get(tid, []))
        if len(pts) < 5:
            unlocatable += 1
            continue
        _segs, records = cut_track(pts, gates, fps, kin)
        flips = [r for r in records
                 if r[1].get("rule") in ("flip_at_speed", "stop_flip")]
        klass = "flip" if flips else "dwell"
        theft_f = (flips[0][0] if flips
                   else records[0][0] if records
                   else pts[len(pts) // 2][0])
        # PATH-FOLLOWING carried test (dense traffic defeats point
        # proximity — measured: four unrelated neighbors "spanned" one
        # theft). Sample 5 points along the base track on each side of
        # the theft; carried = ONE candidate track follows >= 4/5 of
        # BOTH sides.
        side = int(PAD_S * fps)
        pre_refs = [min(pts, key=lambda p: abs(p[0] - (theft_f - k)))
                    for k in range(10, side + 40, max(1, side // 4))][:5]
        post_refs = [min(pts, key=lambda p: abs(p[0] - (theft_f + k)))
                     for k in range(10, side + 40, max(1, side // 4))][:5]
        if not pre_refs or not post_refs                 or pre_refs[0][0] >= post_refs[0][0]:
            unlocatable += 1
            continue

        def follows(track_pts, refs):
            hit = 0
            for ref in refs:
                if any(abs(p[0] - ref[0]) <= 12
                       and math.hypot(p[1] - ref[1], p[2] - ref[2])
                       <= NEAR_PX for p in track_pts):
                    hit += 1
            return hit >= max(1, int(0.8 * len(refs)))

        carried_here = False
        for _ct, cpts in cand.items():
            cs = sorted(cpts)
            if cs[-1][0] < pre_refs[0][0] or cs[0][0] > post_refs[-1][0]:
                continue
            if follows(cs, pre_refs) and follows(cs, post_refs):
                carried_here = True
                break
        tally[klass][1 if carried_here else 0] += 1

    n = len(labels)
    print(f"labeled thefts: {n}  (base {args.base} -> candidate "
          f"{args.candidate})")
    fs, fc = tally["flip"]
    ds, dc = tally["dwell"]
    print(f"  FLIP class (a theft with a flip signature — the live "
          f"monitor's target):")
    print(f"    severed {fs} / carried {fc}")
    print(f"  DWELL class (camped on an idle vehicle — no flip to sever;"
          f" the claim-rule/MQE domain):")
    print(f"    severed {ds} / carried {dc}")
    print(f"  unlocatable: {unlocatable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
