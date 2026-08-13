"""Re-derive one origin's intersection_paths from the site's OWN
gate-verified full journeys (docs/diag_cam2_leg28_2026-08-13.md, the
operator-approved repair). GT-free: pools strict fulls from the study
windows' base dumps, clips gate-to-gate, arc-resamples, and takes the
per-cell mean polyline (the discover_channels shape). Dry-run by
default; --write UPDATEs existing (origin,dest) rows' polylines and
INSERTs missing cells with support >= --min-support, after a WAL-safe
project.db backup.

Usage:
  py -X utf8 scripts/v2_rederive_paths.py --camera 2 --origin-leg 28 \
      --variants study_0700 study_1100 study_1600 [--write]
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.database import get_connection, get_db_path, list_paths_for_camera  # noqa: E402
from backend.services.entry_gates import build_gates, classify      # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir     # noqa: E402
from backend.services.trajectory_classifier import derive_movement  # noqa: E402
from backend.services.two_pass import (                             # noqa: E402
    _camera_parquet, _tracks_from_rows, gate_axes_for)

RESAMPLE_N = 15
SOURCE_TAG = "rederived-fulls-20260813"


def _resample(xy, n=RESAMPLE_N):
    segs = [math.hypot(xy[i + 1][0] - xy[i][0], xy[i + 1][1] - xy[i][1])
            for i in range(len(xy) - 1)]
    total = sum(segs) or 1.0
    out, acc, si = [], 0.0, 0
    for k in range(n):
        d = total * k / (n - 1)
        while si < len(segs) - 1 and acc + segs[si] < d:
            acc += segs[si]
            si += 1
        t = (d - acc) / segs[si] if segs[si] > 1e-9 else 0.0
        out.append((xy[si][0] + t * (xy[si + 1][0] - xy[si][0]),
                    xy[si][1] + t * (xy[si + 1][1] - xy[si][1])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--origin-leg", type=int, required=True)
    ap.add_argument("--variants", nargs="+", required=True)
    ap.add_argument("--min-support", type=int, default=30)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    cam, origin = args.camera, args.origin_leg

    conn = get_connection(args.project)
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id = ?", (cam,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
    conn.row_factory = sqlite3.Row
    legs_full = {r["leg_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM legs WHERE camera_id=?", (cam,))}
    fps = float(conn.execute(
        "SELECT fps FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (cam,)).fetchone()[0])
    conn.close()
    all_legs = list(legs_full.values())
    paths = list_paths_for_camera(args.project, cam)

    by_cell = defaultdict(list)
    for variant in args.variants:
        rows = load_dump(tracks_dir(_camera_parquet(args.project, cam, variant)))
        tracks = {tid: sorted(p) for tid, p in _tracks_from_rows(rows).items()}
        gates = build_gates(mouths, paths, heads,
                            leg_axes=gate_axes_for(mouths, tracks.values()))
        n_win = 0
        for tid, pts in tracks.items():
            if len(pts) < 5:
                continue
            o, d, of, df, _op, _dp, tag = classify(pts, gates, fps)
            if tag != "full" or o != origin or o == d:
                continue
            clip = [(x, y) for f, x, y in pts if of <= f <= df]
            if len(clip) >= 4:
                by_cell[(int(o), int(d))].append(_resample(clip))
                n_win += 1
        print(f"[paths] {variant}: {n_win} origin-{origin} fulls pooled")

    existing = {(p["origin_leg_id"], p["destination_leg_id"]): p
                for p in paths}
    plan = []
    for cell, tracks_r in sorted(by_cell.items()):
        n = len(tracks_r)
        mean = [(round(sum(t[k][0] for t in tracks_r) / n, 1),
                 round(sum(t[k][1] for t in tracks_r) / n, 1))
                for k in range(RESAMPLE_N)]
        mv = derive_movement(legs_full[cell[0]], legs_full.get(cell[1]),
                             all_legs)
        old = existing.get(cell)
        action = ("UPDATE" if old else
                  ("INSERT" if n >= args.min_support else "SKIP-thin"))
        plan.append({"cell": cell, "n_fulls": n, "movement": mv,
                     "action": action,
                     "old_support": old["supporting_count"] if old else None,
                     "old_source": old["source"] if old else None,
                     "path_id": old["path_id"] if old else None,
                     "polyline": mean})
        print(f"[paths] {cell[0]}->{cell[1]} {mv:8s} {action:10s} "
              f"n={n:4d}  first={mean[0]}  mid={mean[7]}  last={mean[-1]}"
              + (f"  (replaces path {old['path_id']}, was support "
                 f"{old['supporting_count']}, {old['source']})" if old else ""))

    out = Path("runs/v2_week1") / f"rederive_paths_cam{cam}_leg{origin}.json"
    out.write_text(json.dumps(plan, indent=1))
    print(f"[paths] -> {out}")

    if not args.write:
        print("[paths] DRY RUN — nothing written. Re-run with --write.")
        return 0

    # WAL-safe backup, then write
    db = get_db_path(args.project)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = Path(str(db) + f".backup_pathfix_{stamp}")
    src = sqlite3.connect(db)
    dst = sqlite3.connect(bak)
    src.backup(dst)
    dst.close()
    src.close()
    print(f"[paths] backup -> {bak}")
    wconn = sqlite3.connect(db)
    with wconn:
        for p in plan:
            if p["action"] == "UPDATE":
                wconn.execute(
                    "UPDATE intersection_paths SET polyline=?, "
                    "supporting_count=?, source=?, movement_label=? "
                    "WHERE path_id=?",
                    (json.dumps(p["polyline"]), p["n_fulls"], SOURCE_TAG,
                     p["movement"], p["path_id"]))
            elif p["action"] == "INSERT":
                wconn.execute(
                    "INSERT INTO intersection_paths (camera_id, "
                    "origin_leg_id, destination_leg_id, polyline, "
                    "movement_label, supporting_count, source) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (cam, p["cell"][0], p["cell"][1],
                     json.dumps(p["polyline"]), p["movement"],
                     p["n_fulls"], SOURCE_TAG))
    wconn.close()
    done = [p for p in plan if p["action"] in ("UPDATE", "INSERT")]
    print(f"[paths] WROTE {len(done)} paths "
          f"({sum(1 for p in done if p['action'] == 'UPDATE')} updated, "
          f"{sum(1 for p in done if p['action'] == 'INSERT')} inserted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
