"""Boundaries-first path fitting (operator architecture rulings
2026-08-19 boundaries-before-paths / 2026-08-20 one-system pipeline).

Raw auto-cal endpoint clustering is fragment-poisoned: a tracking splice's
endpoint lies wherever the stolen box died, so phantom (entry, exit) pairs
accumulate big raw support (cam2's condemned folded "left" carried 109 raw
supporters vs 6 cut-clean full journeys). This step therefore runs AFTER
the operator's legs are confirmed:

    tracked trajectories
      -> A3 cutter against the confirmed gates (geometry + pinch cuts)
      -> classify cut segments, keep FULL journeys only
      -> fit mean polylines per (origin, destination) cell
      -> fold gate (backend/services/path_shape.py)
      -> carry over existing clean paths for cells not re-fit
      -> staged as the camera's pending calibration suggestion

Two trajectory sources:
  --dumps  production pass-1 dumps (the one-system default): every base
           study_* window with a ready dump, pooled — full-trim support,
           zero new GPU (the W1a loss traced to 15-min sample thinness).
  --npz    a saved auto-cal collection (new-site BOOTSTRAP only, before
           the first processing run).

Never applies anything itself: the operator reviews in the calibration
editor. Apply is wholesale-replace, so the composed suggestion is the
COMPLETE desired path set — re-fits, new fits, and carried-over existing
paths (e.g. the hand-drawn u-turn) all included; existing folded paths
are dropped and reported for hand-redraw.

Usage:
  py -X utf8 scripts/run_pathfit_cli.py --project 97a7849a --camera 2 \
      --dumps [--variants study_0700,study_1600] [--cell-cap 500] \
      [--min-support 8] [--dry-run]
  py -X utf8 scripts/run_pathfit_cli.py --project 97a7849a --camera 2 \
      --npz data/projects/.../autocal/traj_cam2_61198_62098.npz
"""
from __future__ import annotations

import argparse
import json
import random
import re
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
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.path_shape import (                        # noqa: E402
    MEMBER_PINCH_DEG, PATH_FOLD_REJECT_DEG, max_concentrated_turn)
from backend.services.trajectory_classifier import derive_movement  # noqa: E402
from backend.services.two_pass import (                          # noqa: E402
    _camera_parquet, derive_windows, dump_status, gate_axes_for)
from v2_common import fit_motion_residual, load_table            # noqa: E402
from v2_a3_split import MIN_SEG_PTS, cut_track                   # noqa: E402
# auto_calibrate is heavy (pulls the detector) but is the one true home of
# the polyline fitter — byte-consistent fits matter more than import time.
from auto_calibrate import (                                     # noqa: E402
    POLYLINE_CONTROL_POINTS, _fit_mean_polyline)

FALLBACK_KIN = {"v_stop": 8.0, "a_allow": 12.0, "zv_radius": 12.0}  # px/s

# min_support by source: dumps pool 6-13.5 h of full journeys, so the raw
# discovery floor applies; the 15-min bootstrap keeps the operator-review
# floor declared 2026-08-19.
MIN_SUPPORT_DUMPS = 8
MIN_SUPPORT_NPZ = 5

_BASE_VARIANT = re.compile(r"study_\d{4}")


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
        "SELECT fps, width, height FROM videos WHERE camera_id=? "
        "ORDER BY sort_order LIMIT 1", (cam,)).fetchone()
    conn.close()
    fps = float(video[0]) if video else 25.0
    frame_size = ([int(video[1]), int(video[2])]
                  if video and video[1] and video[2] else [640, 480])
    return mouths, heads, labels, legs_full, fps, frame_size


def load_npz_tracks(npz_path: str):
    """Saved collection -> tracks as [(frame, x, y), ...]. The collector
    appends one point per processed frame consecutively, so the point
    index IS the frame offset — speeds in px/frame stay correct."""
    z = np.load(npz_path)
    window = [float(v) for v in z["window"]] if "window" in z else None
    frame_size = ([int(v) for v in z["frame_size"]]
                  if "frame_size" in z else None)
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


def discover_dump_windows(project: str, cam: int,
                          only: set[str] | None = None) -> list[dict]:
    """The camera's base study_* windows whose pass-1 dumps are ready.
    Windows whose frame range CONTAINS another selected window are dropped
    (cam3's 24 h study_0000 ⊇ study_0600 — pooling both double-counts
    every journey in the overlap)."""
    conn = sqlite3.connect(
        f"file:data/projects/{project}/project.db?mode=ro", uri=True)
    row = conn.execute("SELECT intersection_id FROM cameras "
                       "WHERE camera_id=?", (cam,)).fetchone()
    conn.close()
    if not row or row[0] is None:
        return []
    out = []
    for w in derive_windows(project, int(row[0])):
        if w["camera_id"] != cam:
            continue
        if not _BASE_VARIANT.fullmatch(w["variant"]):
            continue
        if only is not None and w["variant"] not in only:
            continue
        pq = _camera_parquet(project, cam, w["variant"])
        st = dump_status(pq, w["start_frame"], w["end_frame"], w["fps"])
        if st["status"] != "ready":
            print(f"  skip {w['variant']}: dump {st['status']}")
            continue
        out.append({**w, "tdir": tracks_dir(pq)})
    kept, dropped = drop_containing_windows(out)
    for w in dropped:
        print(f"  skip {w['variant']}: contains another window "
              "(overlap rule)")
    return kept


def drop_containing_windows(windows: list[dict]):
    """(kept, dropped): windows whose frame range CONTAINS another selected
    window are dropped — pooling a container with its contained window
    would double-count every journey in the overlap."""
    kept, dropped = [], []
    for w in windows:
        contains_another = any(
            o is not w
            and w["start_frame"] <= o["start_frame"]
            and o["end_frame"] <= w["end_frame"]
            for o in windows)
        (dropped if contains_another else kept).append(w)
    return kept, dropped


def resolve_min_support(dumps_mode: bool, explicit: int | None) -> int:
    return explicit if explicit is not None else \
        (MIN_SUPPORT_DUMPS if dumps_mode else MIN_SUPPORT_NPZ)


def pool_full(fulls, full_counts, cell, seg, cap, rng) -> None:
    """Seeded per-cell reservoir: stored fit input capped at `cap`,
    while full_counts stays the exact (uncapped) support."""
    full_counts[cell] += 1
    n = full_counts[cell]
    if len(fulls[cell]) < cap:
        fulls[cell].append(seg)
    else:
        j = rng.randrange(n)
        if j < cap:
            fulls[cell][j] = seg


def iter_dump_tracks(tdir):
    """Yield one [(frame, x, y), ...] list per track from a pass-1 dump,
    smallest memory footprint: rows.npy stays memory-mapped; the only
    O(N) allocation is the stable argsort index (which preserves the
    dump's global frame order within each tid, so per-track lists come
    out frame-ordered without a second sort)."""
    rows = load_dump(tdir)
    if len(rows) == 0:
        return
    order = np.argsort(rows[:, 0], kind="stable")
    tids = rows[order, 0]
    bounds = np.flatnonzero(np.diff(tids)) + 1
    start = 0
    for stop in list(bounds) + [len(order)]:
        idx = order[start:stop]
        start = stop
        if len(idx) < MIN_SEG_PTS:
            continue
        sub = rows[idx]
        yield [(float(f), float(x), float(y))
               for f, x, y in zip(sub[:, 1], sub[:, 2], sub[:, 3])]


def kin_for(cam: int, variant: str, override: str | None):
    tk = Path(override) if override else \
        Path(f"runs/v2_week1/tracklets_cam{cam}_{variant}.npz")
    if tk.exists():
        return fit_motion_residual(load_table(tk)), str(tk)
    return dict(FALLBACK_KIN), "fallback-defaults"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--camera", type=int, required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--npz", help="auto-cal collection npz (bootstrap)")
    src.add_argument("--dumps", action="store_true",
                     help="pool the camera's ready base study_* pass-1 "
                          "dumps (the one-system default)")
    ap.add_argument("--variants", default=None,
                    help="dumps mode: comma-separated variant allowlist "
                         "(default: every ready base window)")
    ap.add_argument("--cell-cap", type=int, default=500,
                    help="per-cell reservoir cap on stored fulls (fit "
                         "input); supporting_count stays uncapped")
    ap.add_argument("--min-support", type=int, default=None,
                    help=f"full journeys needed to fit a cell (default "
                         f"{MIN_SUPPORT_DUMPS} dumps / {MIN_SUPPORT_NPZ} "
                         "npz)")
    ap.add_argument("--tracklets", default=None,
                    help="kinematics tracklets npz override (npz mode / "
                         "single-window dumps)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    min_support = resolve_min_support(args.dumps, args.min_support)

    mouths, heads, labels, legs_full, fps, frame_size = load_legs(
        args.project, args.camera)
    if len(mouths) < 3:
        print(f"REFUSING: camera {args.camera} has {len(mouths)} legs with "
              "mouths — confirm leg geometry first (boundaries before paths)")
        return 2

    existing = list_paths_for_camera(args.project, args.camera)

    # Trajectory source -> a list of (window_tag, frames, kin, kin_source,
    # track_iterable) work units. Gates are built ONCE from the confirmed
    # legs; leg_axes comes from the V2_GATE_AXIS flag gate, which returns
    # None at the default-off setting — no need to stream dump tracks
    # through it (and with the flag on, an empty sample simply omits axes).
    units = []
    sample_window = None
    if args.dumps:
        only = (set(args.variants.split(",")) if args.variants else None)
        windows = discover_dump_windows(args.project, args.camera, only)
        if not windows:
            print("REFUSING: no ready base study_* dumps for this camera")
            return 2
        for w in windows:
            kin, ksrc = kin_for(args.camera, w["variant"],
                                args.tracklets if len(windows) == 1 else None)
            units.append((w["variant"], [w["start_frame"], w["end_frame"]],
                          kin, ksrc, lambda t=w["tdir"]: iter_dump_tracks(t)))
    else:
        tracks, sample_window, npz_fs = load_npz_tracks(args.npz)
        if not tracks:
            print("REFUSING: no usable trajectories in npz")
            return 2
        if npz_fs:
            frame_size = npz_fs
        kin, ksrc = kin_for(args.camera, "study_1600", args.tracklets)
        units.append(("npz", sample_window, kin, ksrc, lambda: iter(tracks)))

    gates = build_gates(mouths, existing, heads,
                        leg_axes=gate_axes_for(mouths, []))

    # Cut every track against the confirmed gates, classify the segments,
    # pool the full journeys per (origin, destination) cell across windows.
    # Reservoir (seeded) caps the STORED fit input; counts stay exact.
    rng = random.Random(42)
    fulls: dict[tuple[int, int], list] = defaultdict(list)
    full_counts: dict[tuple[int, int], int] = defaultdict(int)
    funnel_total = defaultdict(int)
    window_stats = []
    for tag, frames, kin, ksrc, track_iter in units:
        funnel = defaultdict(int)
        kept_tracks = 0
        w_fulls = 0
        for pts in track_iter():
            kept_tracks += 1
            segments, _cuts = cut_track(pts, gates, fps, kin)
            for seg in segments:
                o, d, *_rest, tag_c = classify(seg, gates, fps)
                funnel[tag_c] += 1
                if tag_c != "full":
                    continue
                w_fulls += 1
                pool_full(fulls, full_counts, (o, d), seg,
                          args.cell_cap, rng)
        for k, v in funnel.items():
            funnel_total[k] += v
        window_stats.append({"variant": tag, "frames": frames,
                             "kept_tracks": kept_tracks,
                             "funnel": dict(funnel), "fulls": w_fulls,
                             "kin_source": ksrc})
        print(f"  window {tag}: tracks={kept_tracks} fulls={w_fulls} "
              f"kin={ksrc}")

    # Fit polylines from cut-clean fulls; fold-gate the outputs.
    refits, rejected_fits = {}, []
    for cell in sorted(full_counts):
        o, d = cell
        group = fulls[cell]
        if full_counts[cell] < min_support:
            continue
        xy_group = [[(p[1], p[2]) for p in seg] for seg in group]
        poly = _fit_mean_polyline(xy_group, POLYLINE_CONTROL_POINTS)
        if poly is None:
            continue
        fold = max_concentrated_turn(poly)
        # Gate-doc amendment 1 (2026-08-21): for CUT-CLEAN fits the band
        # [PATH_FOLD_REJECT_DEG, MEMBER_PINCH_DEG) is keep-plus-flag — a
        # tight real apex measures just over 100° while every condemned
        # fold measured >=116°; an ABSENT path collapses its cell (W1a).
        # >= the pinch angle stays reject.
        if o != d and fold >= MEMBER_PINCH_DEG:
            rejected_fits.append({"cell": [o, d],
                                  "max_turn_deg": round(fold, 1),
                                  "supporting_count": full_counts[cell]})
            continue
        # Movement label from confirmed leg headings (the production
        # labeler) — image-space polyline tangents mislabel turns under
        # perspective (all six cam2 refits came out "through").
        movement = ("u_turn" if o == d else
                    derive_movement(legs_full[o], legs_full[d],
                                    list(legs_full.values())))
        refits[cell] = {
            "origin_zone_id": o, "destination_zone_id": d,
            "polyline": [list(pt) for pt in poly],
            "supporting_count": full_counts[cell],
            "movement_label": movement,
            "fit_source": "cutclean",
            **({"shape_flag": "sharp_apex_review",
                "max_turn_deg": round(fold, 1)}
               if o != d and fold >= PATH_FOLD_REJECT_DEG else {}),
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
    for (o, d), n in full_counts.items():
        ins[o] += n
        outs[d] += n

    payload = {
        "sample_window": sample_window,
        "frame_size": frame_size,
        "stats": {
            "source": "pathfit-dumps" if args.dumps else "pathfit-cutclean",
            "trajectories_kept": int(sum(w["kept_tracks"]
                                         for w in window_stats)),
            "segment_funnel": dict(funnel_total),
            "full_journeys": int(sum(full_counts.values())),
            "cells_with_fulls": {f"{o}->{d}": n
                                 for (o, d), n in sorted(full_counts.items())},
            "min_support": min_support,
            "windows": window_stats,
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
        "mode": "dumps" if args.dumps else "npz",
        "npz": args.npz,
        "windows": [w["variant"] for w in window_stats],
        "min_support": min_support,
        "cell_cap": args.cell_cap,
        "refit_cells": [list(c) for c in sorted(refits)],
        "replaced_path_ids": replaced,
        "carryover_count": len(carryover),
        "dropped_folded": dropped_folded,
        "rejected_fits_folded": rejected_fits,
    }

    print(f"legs: {len(mouths)}  windows: {len(window_stats)}  fps: {fps}")
    print(f"segment funnel (pooled): {dict(funnel_total)}")
    print("fulls per cell (pooled, uncapped):")
    for cell in sorted(full_counts):
        o, d = cell
        n = full_counts[cell]
        mark = " -> FIT" if cell in refits else \
               ("  (below min_support)" if n < min_support else "")
        print(f"  {labels.get(o, o)} -> {labels.get(d, d)}  "
              f"[{o}->{d}]  {n}{mark}")
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
