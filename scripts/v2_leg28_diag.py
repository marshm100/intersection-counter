"""Diagnostic — false-origin anatomy of one leg's entry gate
(docs/diag_cam2_leg28_2026-08-13.md). Read-only over the dump + geometry.

For every track whose classify() origin is --leg: record the crossing
POSITION along the gate line (0..1 of the segment, extended beyond the
drawn endpoints), the crossing SPEED (px/s over the straddling step),
and — for gate-verified fulls — whether the track's EARLY points fit the
leg's own channel family or a rival's (the strict_full_census confusion
test, per track). Prints separated distributions and the drawn geometry.

Usage:
  py -X utf8 scripts/v2_leg28_diag.py --camera 2 --variant study_0700 --leg 28
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                                  # noqa: E402

from backend.database import get_connection, list_paths_for_camera  # noqa: E402
from backend.services.entry_gates import (                          # noqa: E402
    _closest_on_polyline, build_gates, classify)
from backend.services.pass2_replay import load_dump, tracks_dir     # noqa: E402
from backend.services.two_pass import (                             # noqa: E402
    _camera_parquet, _tracks_from_rows, gate_axes_for)

EARLY_PTS = 12   # the strict_full_census confusion window


def _mean_dist(poly, pts):
    """Mean nearest-distance from a point set to a polyline (the
    strict_full_census confusion primitive, nested there — inlined)."""
    return (sum(_closest_on_polyline(poly, p)[2] for p in pts) / len(pts)
            if pts else float("inf"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--leg", type=int, required=True)
    args = ap.parse_args()
    cam, leg = args.camera, args.leg

    conn = get_connection(args.project)
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id = ?", (cam,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
    fps = float(conn.execute(
        "SELECT fps FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (cam,)).fetchone()[0])
    conn.close()

    paths = list_paths_for_camera(args.project, cam)
    rows = load_dump(tracks_dir(_camera_parquet(args.project, cam,
                                                args.variant)))
    tracks = {tid: sorted(p) for tid, p in _tracks_from_rows(rows).items()}
    gates = build_gates(mouths, paths, heads,
                        leg_axes=gate_axes_for(mouths, tracks.values()))
    g = gates[leg]
    p1, p2, inw = g
    glen = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) or 1.0
    gdir = ((p2[0] - p1[0]) / glen, (p2[1] - p1[1]) / glen)

    # channel families by origin (the confusion test's comparison set)
    fam = defaultdict(list)
    for p in paths:
        fam[p["origin_leg_id"]].append(p["polyline"])

    recs = []   # (kind, pos01, speed, tid)
    for tid, pts in tracks.items():
        if len(pts) < 5:
            continue
        o, d, of, df, opos, _dp, tag = classify(pts, gates, fps)
        if o != leg or opos is None:
            continue
        # position along the gate segment (can be <0 or >1 on the pad)
        pos = ((opos[0] - p1[0]) * gdir[0] + (opos[1] - p1[1]) * gdir[1]) / glen
        # crossing speed: the step straddling the crossing frame
        fr = [p[0] for p in pts]
        j = min(range(len(fr)), key=lambda k: abs(fr[k] - of))
        j2 = min(j + 1, len(pts) - 1)
        dt = (pts[j2][0] - pts[max(j - 1, 0)][0]) / fps
        dist = math.hypot(pts[j2][1] - pts[max(j - 1, 0)][1],
                          pts[j2][2] - pts[max(j - 1, 0)][2])
        speed = dist / dt if dt > 0 else 0.0
        if tag == "full":
            early = [(x, y) for _f, x, y in pts[:EARLY_PTS]]
            own = min((_mean_dist(pl, early) for pl in fam.get(leg, [])),
                      default=float("inf"))
            rival = min((_mean_dist(pl, early)
                         for lg, pls in fam.items() if lg != leg
                         for pl in pls), default=float("inf"))
            kind = "full_true" if own <= rival else "full_confused"
        else:
            kind = f"frag_{tag}"
        recs.append((kind, pos, speed, tid))

    print(f"gate leg {leg}: p1={tuple(round(v,1) for v in p1)} "
          f"p2={tuple(round(v,1) for v in p2)} len={glen:.0f}px "
          f"inward={tuple(round(v,2) for v in inw)}")
    by = defaultdict(list)
    for kind, pos, speed, _t in recs:
        by[kind].append((pos, speed))
    print(f"{'population':16s} {'n':>5s} {'pos p10':>8s} {'p50':>6s} "
          f"{'p90':>6s} {'spd p10':>8s} {'p50':>6s} {'p90':>6s}")
    for kind in sorted(by):
        arr = np.array(by[kind])
        pp = np.percentile(arr[:, 0], [10, 50, 90])
        sp = np.percentile(arr[:, 1], [10, 50, 90])
        print(f"{kind:16s} {len(arr):>5d} {pp[0]:>8.2f} {pp[1]:>6.2f} "
              f"{pp[2]:>6.2f} {sp[0]:>8.0f} {sp[1]:>6.0f} {sp[2]:>6.0f}")
    # position histogram, true vs confused fulls, tenths of the segment
    print("\nposition histogram (tenths of the gate segment; <0 / >1 = pad)")
    bins = [-0.5, -0.25, 0, 0.1, 0.2, 0.3, 0.4, 0.5,
            0.6, 0.7, 0.8, 0.9, 1.0, 1.25, 1.5]
    for kind in ("full_true", "full_confused"):
        if kind not in by:
            continue
        h, _ = np.histogram([p for p, _s in by[kind]], bins=bins)
        print(f"  {kind:14s} " + " ".join(f"{int(v):>4d}" for v in h))
    print("  bin edges      " + " ".join(f"{v:>4.2g}" for v in bins[:-1]))
    out = {"leg": leg, "variant": args.variant,
           "gate": {"p1": list(p1), "p2": list(p2), "len_px": glen},
           "populations": {k: {"n": len(v),
                               "pos_p10_50_90": [round(float(x), 3) for x in
                                                 np.percentile([p for p, _ in v],
                                                               [10, 50, 90])],
                               "speed_p10_50_90": [round(float(x), 1) for x in
                                                   np.percentile([s for _, s in v],
                                                                 [10, 50, 90])]}
                           for k, v in by.items()}}
    dst = f"runs/v2_week1/leg{leg}diag_cam{cam}_{args.variant}.json"
    with open(dst, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n-> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
