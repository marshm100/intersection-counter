"""Dynamics-first destination instrument (G-DYN-i,
docs/plan_t3_dyn_dest_2026-08-13.md — operator-directed: the movement is
the PATH OVER TIME, not the mouth or lane entered).

Classifies held-out gate-verified fulls from PREFIXES of their in-box
points using ONLY motion features — net heading change Δθ(f) — against
split-half self-calibrated per-(origin, destination) templates. Channels
appear nowhere. Reports held-out destination accuracy per origin per
prefix fraction: the exact truncated-track case the pipeline guesses on
today (status quo implied through-recall at cam2 entry_28: ~12%).

Usage:
  py -X utf8 scripts/v2_dyn_dest_instrument.py --camera 2 --variant study_0700
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                                  # noqa: E402

from backend.database import get_connection, list_paths_for_camera  # noqa: E402
from backend.services.entry_gates import build_gates, classify      # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir     # noqa: E402
from backend.services.two_pass import (                             # noqa: E402
    _camera_parquet, _tracks_from_rows, gate_axes_for)

SEED = 42
PREFIXES = (0.4, 0.6, 0.8, 1.0)
KIN = 8          # heading window (points), the campaign's KIN_PTS


def heading(pts, i0, i1):
    """Direction (radians) of travel over points [i0, i1)."""
    a, b = pts[i0], pts[min(i1, len(pts) - 1)]
    dx, dy = b[1] - a[1], b[2] - a[2]
    return math.atan2(dy, dx) if (dx * dx + dy * dy) > 1.0 else None


def dtheta_profile(clip):
    """Net heading change (signed, wrapped) at each prefix fraction,
    relative to the entry heading. None where undefined."""
    n = len(clip)
    h0 = heading(clip, 0, KIN)
    out = {}
    for f in PREFIXES:
        j = max(KIN, int(n * f))
        h1 = heading(clip, max(0, j - KIN), j)
        if h0 is None or h1 is None:
            out[f] = None
            continue
        d = h1 - h0
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        out[f] = math.degrees(d)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    args = ap.parse_args()
    cam = args.camera
    rng = np.random.default_rng(SEED)

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
    rows = load_dump(tracks_dir(_camera_parquet(args.project, cam,
                                                args.variant)))
    tracks = {tid: sorted(p) for tid, p in _tracks_from_rows(rows).items()}
    gates = build_gates(mouths, list_paths_for_camera(args.project, cam),
                        heads, leg_axes=gate_axes_for(mouths, tracks.values()))

    # gate-verified fulls with their in-box clips
    fulls = defaultdict(list)          # origin -> [(dest, profile)]
    for tid, pts in tracks.items():
        if len(pts) < 5:
            continue
        o, d, of, df, _op, _dp, tag = classify(pts, gates, fps)
        if tag != "full" or o == d:
            continue
        clip = [p for p in pts if of <= p[0] <= df]
        if len(clip) < KIN + 4:
            continue
        fulls[int(o)].append((int(d), dtheta_profile(clip)))

    report = {}
    print(f"{'origin':>6s} {'dest':>5s} {'n':>5s}  " +
          "  ".join(f"dTheta@{f:.1f} p50" for f in PREFIXES))
    for o, recs in sorted(fulls.items()):
        by_d = defaultdict(list)
        for d, prof in recs:
            by_d[d].append(prof)
        for d, profs in sorted(by_d.items()):
            meds = [np.median([p[f] for p in profs if p[f] is not None])
                    if any(p[f] is not None for p in profs) else float("nan")
                    for f in PREFIXES]
            print(f"{o:>6d} {d:>5d} {len(profs):>5d}  " +
                  "  ".join(f"{m:>13.1f}" for m in meds))

        # split-half: templates from half A, classify half B prefixes
        idx = rng.permutation(len(recs))
        half = len(recs) // 2
        A = [recs[i] for i in idx[:half]]
        B = [recs[i] for i in idx[half:]]
        tmpl = defaultdict(dict)       # dest -> {f: median}
        by_dA = defaultdict(list)
        for d, prof in A:
            by_dA[d].append(prof)
        for d, profs in by_dA.items():
            if len(profs) < 5:
                continue
            for f in PREFIXES:
                vals = [p[f] for p in profs if p[f] is not None]
                if len(vals) >= 5:
                    tmpl[d][f] = float(np.median(vals))
        acc = {}
        for f in PREFIXES:
            cands = [d for d in tmpl if f in tmpl[d]]
            if len(cands) < 2:
                continue
            n_ok = n_tot = 0
            conf = defaultdict(int)
            for d, prof in B:
                if d not in cands or prof[f] is None:
                    continue
                pred = min(cands, key=lambda c: abs(prof[f] - tmpl[c][f]))
                n_tot += 1
                n_ok += (pred == d)
                conf[(d, pred)] += 1
            if n_tot:
                acc[f] = {"acc": round(n_ok / n_tot, 3), "n": n_tot,
                          "confusions": {f"{k[0]}->{k[1]}": v
                                         for k, v in sorted(conf.items())
                                         if k[0] != k[1]}}
        report[o] = acc
        print(f"  origin {o} held-out accuracy: " +
              "  ".join(f"@{f:.1f}={acc[f]['acc']}(n={acc[f]['n']})"
                        for f in PREFIXES if f in acc))

    dst = Path("runs/v2_week1") / (
        f"dyndest_cam{cam}_{args.variant}.json")
    dst.write_text(json.dumps(report, indent=1))
    print(f"-> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
