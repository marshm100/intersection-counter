"""Pipeline-V2 — origin-lane probe for the direct-attribution flood.

For a (origin cardinal, movement) cell's events in a pass-2 working DB,
fetch each event's track from the dump table and measure which ORIGIN
CHANNEL FAMILY its earliest segment rides: the claimed origin's own
channels vs each rival origin's channels (applied-bank polylines,
production geometry). Reports the rival-side population = the estimated
false-origin mass, and runs the same test on sibling cells as the
over-aggression control.

Usage:
  py -X utf8 scripts/v2_origin_lane_probe.py \
      data/projects/97a7849a/_replay_scratch/v2_week1/twopass_cam2_study_0700.db \
      runs/v2_week1/tracklets_cam2_study_0700.npz --cells W:right W:left W:through
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import load_table, track_points         # noqa: E402

EARLY_PTS = 12


def seg_dist(poly, pts):
    """Mean distance of pts to polyline poly."""
    best = np.full(len(pts), np.inf)
    P = np.asarray(pts, dtype=float)
    for i in range(len(poly) - 1):
        a = np.asarray(poly[i], dtype=float)
        b = np.asarray(poly[i + 1], dtype=float)
        ab = b - a
        L2 = float(ab @ ab)
        if L2 < 1e-9:
            continue
        t = np.clip(((P - a) @ ab) / L2, 0, 1)
        proj = a + t[:, None] * ab
        d = np.hypot(*(P - proj).T)
        best = np.minimum(best, d)
    return float(best.mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("table")
    ap.add_argument("--camera", type=int, default=2)
    ap.add_argument("--cells", nargs="+", default=["W:right"])
    args = ap.parse_args()

    t = load_table(args.table)
    tid_to_idx = {int(t["track_id"][i]): i for i in range(t["n"])}

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    legs = {r["leg_id"]: r["cardinal_direction"] for r in conn.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
        (args.camera,))}
    chans: dict[int, list] = {}
    for r in conn.execute(
            "SELECT origin_leg_id, polyline FROM intersection_paths "
            "WHERE camera_id=?", (args.camera,)):
        chans.setdefault(r["origin_leg_id"], []).append(
            json.loads(r["polyline"]))

    for cell in args.cells:
        card, mv = cell.split(":")
        oleg = next(k for k, v in legs.items() if v == card)
        rows = conn.execute(
            "SELECT e.vehicle_track_id, COALESCE(e.posterior_source,'(direct)') src "
            "FROM vehicle_events e JOIN legs l ON l.leg_id=e.origin_leg_id "
            "WHERE e.camera_id=? AND COALESCE(e.rejected,0)=0 "
            "AND l.cardinal_direction=? AND e.movement=?",
            (args.camera, card, mv)).fetchall()
        own, rival, miss = 0, {}, 0
        for r in rows:
            if r["src"] != "(direct)":
                continue
            i = tid_to_idx.get(int(r["vehicle_track_id"]))
            if i is None:
                miss += 1
                continue
            tr = track_points(t, i)
            early = tr[:EARLY_PTS, 2:4]
            d_own = min((seg_dist(p, early) for p in chans.get(oleg, [])),
                        default=np.inf)
            best_r, best_d = None, np.inf
            for rl, ps in chans.items():
                if rl == oleg:
                    continue
                d = min((seg_dist(p, early) for p in ps), default=np.inf)
                if d < best_d:
                    best_d, best_r = d, rl
            if d_own <= best_d:
                own += 1
            else:
                rival[legs.get(best_r, "?")] = rival.get(
                    legs.get(best_r, "?"), 0) + 1
        print(f"cell {card} {mv}: direct events={own + sum(rival.values())} "
              f"own-lane={own} rival-lane={dict(sorted(rival.items()))} "
              f"(unmatched track ids: {miss})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
