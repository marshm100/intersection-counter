"""Boundaries-first path fitting (operator architecture ruling 2026-08-19).

Raw auto-cal endpoint clustering is fragment-poisoned: a tracking splice's
endpoint lies wherever the stolen box died, so phantom (entry, exit) pairs
accumulate big raw support (cam2's condemned folded "left" carried 109 raw
supporters vs 6 cut-clean full journeys). This step therefore runs AFTER
the operator's legs are confirmed:

    saved trajectories (npz from the collection step)
      -> A3 cutter against the confirmed gates (geometry + pinch cuts)
      -> classify cut segments, keep FULL journeys only
      -> fit mean polylines per (origin, destination) cell
      -> fold gate (backend/services/path_shape.py)
      -> carry over existing clean paths for cells not re-fit
      -> staged as the camera's pending calibration suggestion

Never applies anything itself: the operator reviews in the calibration
editor. Apply is wholesale-replace, so the composed suggestion is the
COMPLETE desired path set — re-fits, new fits, and carried-over existing
paths (e.g. the hand-drawn u-turn) all included; existing folded paths
are dropped and reported for hand-redraw.

Usage:
  py -X utf8 scripts/run_pathfit_cli.py --project 97a7849a --camera 2 \
      --npz data/projects/97a7849a/_replay_scratch/autocal/traj_cam2_61198_62098.npz \
      [--min-support 5] [--tracklets runs/v2_week1/tracklets_cam2_study_1600.npz] \
      [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                                               # noqa: E402

from backend.database import (                                   # noqa: E402
    list_paths_for_camera, save_calibration_suggestion)
from backend.services.entry_gates import build_gates, classify   # noqa: E402
from backend.services.path_shape import (                        # noqa: E402
    PATH_FOLD_REJECT_DEG, max_concentrated_turn)
from backend.services.trajectory_classifier import derive_movement  # noqa: E402
from backend.services.two_pass import gate_axes_for              # noqa: E402
from v2_common import fit_motion_residual, load_table            # noqa: E402
from v2_a3_split import MIN_SEG_PTS, cut_track                   # noqa: E402
# auto_calibrate is heavy (pulls the detector) but is the one true home of
# the polyline fitter — byte-consistent fits matter more than import time.
from auto_calibrate import (                                     # noqa: E402
    POLYLINE_CONTROL_POINTS, _fit_mean_polyline)

FALLBACK_KIN = {"v_stop": 8.0, "a_allow": 12.0, "zv_radius": 12.0}  # px/s


def load_legs(project: str, cam: int):
    conn = sqlite3.connect(
        f"file:data/projects/{project}/project.db?mode=ro", uri=True)
    mouths, heads, labels, legs_full = {}, {}, {}, {}
    for lid, oz, rh, card, label in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading, "
            "cardinal_direction, label FROM legs WHERE camera_id=?", (cam,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
            labels[lid] = f"{label or ''}({card or '?'})"
            legs_full[lid] = {"leg_id": lid, "reference_heading": rh,
                              "cardinal_direction": card}
    video = conn.execute(
        "SELECT fps FROM videos WHERE camera_id=? ORDER BY sort_order "
        "LIMIT 1", (cam,)).fetchone()
    conn.close()
    return mouths, heads, labels, legs_full, \
        float(video[0]) if video else 25.0


def load_npz_tracks(npz_path: str):
    """Saved collection -> tracks as [(frame, x, y), ...]. The collector
    appends one point per processed frame consecutively, so the point
    index IS the frame offset — speeds in px/frame stay correct."""
    z = np.load(npz_path)
    window = [float(v) for v in z["window"]] if "window" in z else None
    frame_size = ([int(v) for v in z["frame_size"]]
                  if "frame_size" in z else [640, 480])
    tracks = []
    for k in z.files:
        if not k.startswith("t"):
            continue
        arr = z[k]
        if arr.ndim != 2 or arr.shape[0] < MIN_SEG_PTS:
            continue
        tracks.append([(float(i), float(x), float(y))
                       for i, (x, y) in enumerate(arr)])
    return tracks, window, frame_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--npz", required=True)
    ap.add_argument("--min-support", type=int, default=5,
                    help="full journeys needed to fit a cell (default 5 — "
                         "lower than raw discovery's 8 because every "
                         "supporter here is a cut-clean full journey and "
                         "the operator reviews the fit visually)")
    ap.add_argument("--tracklets", default=None,
                    help="tracklets npz for kinematic self-calibration "
                         "(default: runs/v2_week1/tracklets_cam<N>_"
                         "study_1600.npz when present)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mouths, heads, labels, legs_full, fps = load_legs(
        args.project, args.camera)
    if len(mouths) < 3:
        print(f"REFUSING: camera {args.camera} has {len(mouths)} legs with "
              "mouths — confirm leg geometry first (boundaries before paths)")
        return 2

    tracks, window, frame_size = load_npz_tracks(args.npz)
    if not tracks:
        print("REFUSING: no usable trajectories in npz")
        return 2

    existing = list_paths_for_camera(args.project, args.camera)
    gates = build_gates(mouths, existing, heads,
                        leg_axes=gate_axes_for(mouths, tracks))

    tk_path = args.tracklets or (
        f"runs/v2_week1/tracklets_cam{args.camera}_study_1600.npz")
    if Path(tk_path).exists():
        kin, kin_source = fit_motion_residual(load_table(Path(tk_path))), tk_path
    else:
        kin, kin_source = dict(FALLBACK_KIN), "fallback-defaults"

    # Cut every track against the confirmed gates, classify the segments,
    # bank the full journeys per (origin, destination) cell.
    funnel = defaultdict(int)
    fulls: dict[tuple[int, int], list] = defaultdict(list)
    for pts in tracks:
        segments, _cuts = cut_track(pts, gates, fps, kin)
        for seg in segments:
            o, d, *_rest, tag = classify(seg, gates, fps)
            funnel[tag] += 1
            if tag == "full":
                fulls[(o, d)].append(seg)

    # Fit polylines from cut-clean fulls; fold-gate the outputs.
    refits, rejected_fits = {}, []
    for (o, d), group in sorted(fulls.items()):
        if len(group) < args.min_support:
            continue
        xy_group = [[(p[1], p[2]) for p in seg] for seg in group]
        poly = _fit_mean_polyline(xy_group, POLYLINE_CONTROL_POINTS)
        if poly is None:
            continue
        fold = max_concentrated_turn(poly)
        if o != d and fold >= PATH_FOLD_REJECT_DEG:
            rejected_fits.append({"cell": [o, d], "max_turn_deg": round(fold, 1),
                                  "supporting_count": len(group)})
            continue
        # Movement label from confirmed leg headings (the production
        # labeler) — image-space polyline tangents mislabel turns under
        # perspective (all six cam2 refits came out "through").
        movement = ("u_turn" if o == d else
                    derive_movement(legs_full[o], legs_full[d],
                                    list(legs_full.values())))
        refits[(o, d)] = {
            "origin_zone_id": o, "destination_zone_id": d,
            "polyline": [list(pt) for pt in poly],
            "supporting_count": len(group),
            "movement_label": movement,
            "fit_source": "cutclean",
        }

    # Compose the complete set: re-fits win their cell; existing paths carry
    # over when their cell was not re-fit AND their shape passes the gate
    # (u-turns exempt); existing folds are dropped for hand-redraw.
    carryover, dropped_folded, replaced = [], [], []
    for p in existing:
        cell = (p["origin_leg_id"], p["destination_leg_id"])
        fold = max_concentrated_turn(p["polyline"])
        if cell in refits:
            replaced.append({"path_id": p["path_id"], "cell": list(cell),
                             "movement": p["movement_label"]})
            continue
        if (p["movement_label"] != "u_turn"
                and fold >= PATH_FOLD_REJECT_DEG):
            dropped_folded.append({
                "path_id": p["path_id"], "cell": list(cell),
                "movement": p["movement_label"],
                "max_turn_deg": round(fold, 1), "source": p.get("source")})
            continue
        carryover.append({
            "origin_zone_id": cell[0], "destination_zone_id": cell[1],
            "polyline": p["polyline"],
            "supporting_count": p.get("supporting_count", 0),
            "movement_label": p["movement_label"],
            "fit_source": f"carryover:{p.get('source') or 'unknown'}",
        })

    paths_out = list(refits.values()) + carryover
    ins = defaultdict(int)
    outs = defaultdict(int)
    for (o, d), group in fulls.items():
        ins[o] += len(group)
        outs[d] += len(group)

    payload = {
        "sample_window": window,
        "frame_size": frame_size,
        "stats": {
            "source": "pathfit-cutclean",
            "trajectories_kept": len(tracks),
            "segment_funnel": dict(funnel),
            "full_journeys": int(sum(len(g) for g in fulls.values())),
            "cells_with_fulls": {f"{o}->{d}": len(g)
                                 for (o, d), g in sorted(fulls.items())},
            "min_support": args.min_support,
            "kin_source": kin_source,
            "rejected_fits_folded": rejected_fits,
            "dropped_existing_folded": dropped_folded,
        },
        # zone_id = the REAL leg_id and origin_point = the leg's mouth, so
        # the apply endpoint's spatial zone->leg match resolves exactly.
        "leg_zones": [
            {"zone_id": lid, "origin_point": list(mouths[lid]),
             "reference_heading": heads.get(lid),
             "supporting_count": ins.get(lid, 0),
             "confidence": "confirmed-leg"}
            for lid in sorted(mouths)
        ],
        "exit_zones": [
            {"zone_id": lid, "centroid": list(mouths[lid]),
             "supporting_count": outs.get(lid, 0)}
            for lid in sorted(mouths)
        ],
        "paths": paths_out,
    }
    meta = {
        "source": "run_pathfit_cli",
        "npz": args.npz,
        "min_support": args.min_support,
        "kin_source": kin_source,
        "refit_cells": [list(c) for c in sorted(refits)],
        "replaced_path_ids": replaced,
        "carryover_count": len(carryover),
        "dropped_folded": dropped_folded,
        "rejected_fits_folded": rejected_fits,
    }

    print(f"legs: {len(mouths)}  tracks: {len(tracks)}  "
          f"fps: {fps}  kin: {kin_source}")
    print(f"segment funnel: {dict(funnel)}")
    print("fulls per cell:")
    for (o, d), g in sorted(fulls.items()):
        mark = " -> FIT" if (o, d) in refits else \
               ("  (below min_support)" if len(g) < args.min_support else "")
        print(f"  {labels.get(o, o)} -> {labels.get(d, d)}  "
              f"[{o}->{d}]  {len(g)}{mark}")
    for r in rejected_fits:
        print(f"  REJECTED folded fit {r['cell']}: {r['max_turn_deg']} deg")
    print(f"composed suggestion: {len(refits)} re-fit + {len(carryover)} "
          f"carried over = {len(paths_out)} paths")
    for dr in dropped_folded:
        print(f"  DROPPED existing folded path {dr['path_id']} "
              f"{dr['cell']} {dr['movement']} ({dr['max_turn_deg']} deg) "
              f"— hand-redraw")
    if args.dry_run:
        print("DRY RUN — nothing saved")
        return 0
    sid = save_calibration_suggestion(args.project, args.camera, payload,
                                      job_metadata=meta)
    print(f"SAVED suggestion {sid} (pending) for camera {args.camera}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
