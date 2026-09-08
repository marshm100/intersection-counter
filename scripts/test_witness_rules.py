"""Test the operator's two-half idea (2026-09-08), read-only.

Half 1 STITCH: a fragment with NO witnessed crossing may be merged
  into a witnessed journey it physically continues (motion-projected
  distance, frozen constants). The relaxation is deliberately narrow —
  predecessor tag 'no_crossing' -> successor tag 'full' — because a
  no-crossing fragment cannot itself be a legitimate complete vehicle,
  so absorbing it into a witnessed journey can only remove a phantom,
  never delete a real count. The measured full+full disaster
  (docs: fulls 3459->2951) stays forbidden.
Half 2 VETO: whatever is STILL never-witnessed after stitching does
  not mint a counted movement (the operator's 'journey witness before
  volume').

Prints the per-cell table for: as-counted / veto-only / stitch+veto,
against Miovision. No writes.

Usage:  py -X utf8 scripts/test_witness_rules.py
"""
from __future__ import annotations

import bisect
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates, classify  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402
from backend.services.track_chains import (CHAIN_DIR_TOL_DEG,  # noqa: E402
                                           STITCH_MOVE_DIST,
                                           STITCH_MOVE_GAP_S,
                                           STITCH_STAT_DIST,
                                           STITCH_STAT_GAP_S,
                                           STITCH_STAT_SPEED_PXS,
                                           _end_speed, endpoint_bearings)
from backend.services.track_cut import _bdiff  # noqa: E402

PROJ = "97a7849a"
CAM, VARIANT = 5, "l1_study_1100"
# Miovision, cam5 midday, keyed by (origin cardinal, movement)
# Approach naming: the bound direction is where traffic is GOING, so
# the "eastbound" approach is the WEST leg. (Origin S = NB, N = SB,
# W = EB, E = WB.)
MIO = {("S", "through"): 1362, ("S", "left"): 185, ("S", "right"): 26,
       ("N", "through"): 1496, ("N", "left"): 27, ("N", "right"): 88,
       ("W", "through"): 12, ("W", "left"): 87, ("W", "right"): 162,
       ("E", "through"): 24, ("E", "left"): 17, ("E", "right"): 21}
BOUND = {"S": "NB", "N": "SB", "E": "WB", "W": "EB"}


def stitch_orphans(recs, fps):
    """no_crossing predecessor -> full successor, motion-projected."""
    rs = sorted(recs, key=lambda r: r["birth"][0])
    births = [r["birth"][0] for r in rs]
    cands = []
    for ai, a in enumerate(rs):
        if a["tag"] != "no_crossing":
            continue
        fa, xa, ya = a["death"]
        vx, vy = a["v_vec"]
        lo = bisect.bisect_left(births, fa + STITCH_MOVE_GAP_S[0] * fps)
        hi = bisect.bisect_right(births, fa + STITCH_STAT_GAP_S * fps)
        a_slow = a["v_end"] * fps < STITCH_STAT_SPEED_PXS
        for bi in range(lo, hi):
            if bi == ai:
                continue
            b = rs[bi]
            if b["tag"] not in ("full", "exit_only"):
                continue
            if b["death"][0] <= fa:
                continue
            gap = b["birth"][0] - fa
            raw = math.hypot(b["birth"][1] - xa, b["birth"][2] - ya)
            ex, ey = xa + vx * gap, ya + vy * gap
            ext = math.hypot(b["birth"][1] - ex, b["birth"][2] - ey)
            ba, bb = a.get("b_end"), b.get("b_start")
            if (ba is not None and bb is not None
                    and _bdiff(ba, bb) > CHAIN_DIR_TOL_DEG):
                continue
            moving = (STITCH_MOVE_GAP_S[0] * fps <= gap
                      <= STITCH_MOVE_GAP_S[1] * fps
                      and ext <= STITCH_MOVE_DIST)
            stat = (a_slow and 0 < gap <= STITCH_STAT_GAP_S * fps
                    and raw <= STITCH_STAT_DIST)
            if moving or stat:
                cands.append(((ext if moving else raw) + 0.5 * max(gap, 0),
                              ai, bi))
    cands.sort(key=lambda c: c[0])
    succ, pred, absorbed = {}, {}, {}
    for _s, ai, bi in cands:
        if ai in succ or bi in pred:
            continue
        succ[ai] = bi
        pred[bi] = ai
        absorbed[rs[ai]["tid"]] = rs[bi]["tid"]
    return absorbed


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    chash, fps = con.execute(
        "SELECT content_hash, fps FROM videos WHERE camera_id=?",
        (CAM,)).fetchone()
    legs = dict(con.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
        (CAM,)))
    con.close()
    fps = float(fps)

    geom = leg_geometry_for_camera(PROJ, CAM)
    gates = build_gates(
        {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
        list_paths_for_camera(PROJ, CAM),
        {lg: g.get("heading") for lg, g in geom.items()},
        leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})

    td = tracks_dir(parquet_path(PROJ, CAM, chash, VARIANT))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append(
            (float(r[1]), float(r[2]), float(r[3])))

    recs, tag = [], {}
    for tid, pts in tracks.items():
        pts = sorted(pts)
        if len(pts) < 5:
            continue
        t = classify(pts, gates, fps)[-1]
        tag[tid] = t
        bs, be = endpoint_bearings(pts, fps)
        seg = pts[-6:] if len(pts) > 6 else pts
        df = seg[-1][0] - seg[0][0]
        v = (((seg[-1][1] - seg[0][1]) / df,
              (seg[-1][2] - seg[0][2]) / df) if df > 0 else (0.0, 0.0))
        recs.append({"tid": tid, "birth": (pts[0][0], pts[0][1], pts[0][2]),
                     "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
                     "tag": t, "v_end": _end_speed(pts), "v_vec": v,
                     "b_start": bs, "b_end": be})

    absorbed = stitch_orphans(recs, fps)
    print(f"orphan fragments absorbed into witnessed journeys: "
          f"{len(absorbed)}")

    s = sqlite3.connect(
        f"file:data/projects/{PROJ}/_replay_scratch/c45_20260907/"
        f"cx_cam{CAM}_{VARIANT.replace('l1_', '')}.db?mode=ro", uri=True)
    ev = list(s.execute(
        "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, movement"
        " FROM vehicle_events WHERE camera_id=? AND rejected=0", (CAM,)))
    s.close()

    # path length per track (a genuine FRAGMENT is short; a long
    # never-witnessed track is more likely a real vehicle whose lane
    # simply misses the drawn gates)
    span = {}
    for tid, pts in tracks.items():
        pts = sorted(pts)
        if len(pts) < 5:
            continue
        span[tid] = math.hypot(pts[-1][1] - pts[0][1],
                               pts[-1][2] - pts[0][2])

    now, veto, both = defaultdict(int), defaultdict(int), defaultdict(int)
    for tid, o, d, mv in ev:
        key = (legs.get(o), mv)
        now[key] += 1
        t = tag.get(int(tid), "(short)")
        if t != "no_crossing":
            veto[key] += 1
            both[key] += 1
        elif int(tid) in absorbed:
            pass                      # merged into its witnessed journey
        else:
            pass                      # never witnessed, unstitchable -> out

    # sweep: veto never-witnessed ONLY below a span threshold
    print()
    for thr in (0, 60, 100, 150, 200, 250, 300, 400, 10**9):
        cnt = defaultdict(int)
        for tid, o, d, mv in ev:
            t = tag.get(int(tid), "(short)")
            if t == "no_crossing" and span.get(int(tid), 0) < thr:
                continue
            cnt[(legs.get(o), mv)] += 1
        err = sum(abs(MIO[k] - cnt[k]) for k in MIO)
        tot = sum(cnt[k] for k in MIO)
        lab = ("no veto" if thr == 0 else
               ("veto ALL never-witnessed" if thr > 10**8
                else f"veto never-witnessed under {thr} px"))
        print(f"  {lab:34} total={tot:>5}  abs error vs Mio={err:>5}")
    tot = [0, 0, 0, 0]
    print(f"\n{'cell':10} {'Mio':>6} {'now':>6} {'veto':>6} {'stitch+veto':>12}")
    for key in sorted(MIO, key=lambda k: -MIO[k]):
        m = MIO[key]
        label = f"{BOUND[key[0]]}_{key[1][:5]}"
        print(f"{label:10} {m:>6} {now[key]:>6} {veto[key]:>6} "
              f"{both[key]:>12}")
        tot[0] += m
        tot[1] += now[key]
        tot[2] += veto[key]
        tot[3] += both[key]
    print(f"{'TOTAL':10} {tot[0]:>6} {tot[1]:>6} {tot[2]:>6} {tot[3]:>12}")
    for i, lab in ((1, "now"), (2, "veto"), (3, "stitch+veto")):
        err = sum(abs(MIO[k] - (now, veto, both)[i - 1][k]) for k in MIO)
        print(f"  total absolute error vs Miovision, {lab:12}: {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
