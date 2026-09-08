"""Measure the extrapolated-stitch hypothesis (operator test request
2026-09-08).

The shipped chainer (track_chains.chain_tracks) tests RAW death->birth
distance. The clip-6 pairing showed raw distance is the wrong measure:
it REJECTED the true pair (75 px) and ACCEPTED a false one (34 px),
while motion-projected distance got both right (6 px / 77 px).

This runs the shipped chainer twice on a real dump — once as shipped,
once with the distance measure swapped for the motion projection —
with EVERYTHING else identical: the tag-gating safety rule (only
journey-incomplete tracks may chain), the direction gate, the greedy
assignment, and the frozen constants. Read-only; no production writes.

Usage:  py -X utf8 scripts/test_extrapolated_stitch.py [--camera 5]
        [--variant l1_study_1100]
"""
from __future__ import annotations

import argparse
import bisect
import math
import sqlite3
import sys
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
                                           _end_speed, chain_tracks,
                                           endpoint_bearings)
from backend.services.track_cut import _bdiff  # noqa: E402

PROJ = "97a7849a"
A_OK = ("entry_only", "no_crossing")
B_OK = ("exit_only", "no_crossing")


def chain_tracks_extrapolated(recs, fps, stats=None):
    """chain_tracks with ONE change: for a moving fragment the distance
    is measured from where its own motion says it should be, not from
    where it died. Stopped fragments keep the raw dwell test (a dwell
    has no direction to project)."""
    rs = sorted(recs, key=lambda r: r["birth"][0])
    births = [r["birth"][0] for r in rs]
    cands = []
    for ai, a in enumerate(rs):
        if a["tag"] not in A_OK:
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
            if b["tag"] not in B_OK:
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
                if stats is not None:
                    stats["direction_rejections"] = (
                        stats.get("direction_rejections", 0) + 1)
                continue
            moving = (STITCH_MOVE_GAP_S[0] * fps <= gap
                      <= STITCH_MOVE_GAP_S[1] * fps
                      and ext <= STITCH_MOVE_DIST)
            stat = (a_slow and 0 < gap <= STITCH_STAT_GAP_S * fps
                    and raw <= STITCH_STAT_DIST)
            if moving or stat:
                cost = (ext if moving else raw) + 0.5 * max(gap, 0.0)
                cands.append((cost, ai, bi))
    cands.sort(key=lambda c: c[0])
    succ, pred = {}, {}
    for _s, ai, bi in cands:
        if ai in succ or bi in pred:
            continue
        succ[ai] = bi
        pred[bi] = ai
    chains = []
    for i in range(len(rs)):
        if i in pred:
            continue
        idx = [i]
        while idx[-1] in succ:
            idx.append(succ[idx[-1]])
        chains.append([rs[k] for k in idx])
    return chains


def build_recs(tracks, gates, fps):
    recs = []
    for tid, pts in tracks.items():
        pts = sorted(pts)
        if len(pts) < 5:
            continue
        o, d, *_rest, tag = classify(pts, gates, fps)
        bs, be = endpoint_bearings(pts, fps)
        seg = pts[-6:] if len(pts) > 6 else pts
        df = seg[-1][0] - seg[0][0]
        v_vec = (((seg[-1][1] - seg[0][1]) / df,
                  (seg[-1][2] - seg[0][2]) / df) if df > 0 else (0.0, 0.0))
        recs.append({"tid": tid,
                     "birth": (pts[0][0], pts[0][1], pts[0][2]),
                     "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
                     "tag": tag, "v_end": _end_speed(pts),
                     "v_vec": v_vec, "b_start": bs, "b_end": be})
    return recs


def pairs_of(chains):
    out = set()
    for c in chains:
        for x, y in zip(c, c[1:]):
            out.add((x["tid"], y["tid"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=5)
    ap.add_argument("--variant", default="l1_study_1100")
    ap.add_argument("--events-db", default=None)
    args = ap.parse_args()
    cam, variant = args.camera, args.variant

    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    chash, fps = con.execute(
        "SELECT content_hash, fps FROM videos WHERE camera_id=?",
        (cam,)).fetchone()
    con.close()
    fps = float(fps)

    geom = leg_geometry_for_camera(PROJ, cam)
    mouths = {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")}
    heads = {lg: g.get("heading") for lg, g in geom.items()}
    drawn = {lg: g["gate"] for lg, g in geom.items() if g.get("gate")}
    gates = build_gates(mouths, list_paths_for_camera(PROJ, cam), heads,
                        leg_gates=drawn)

    td = tracks_dir(parquet_path(PROJ, cam, chash, variant))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append(
            (float(r[1]), float(r[2]), float(r[3])))

    recs = build_recs(tracks, gates, fps)
    print(f"cam{cam} {variant}: {len(recs)} tracks >= 5 points")

    raw_chains = chain_tracks(recs, fps)
    ext_chains = chain_tracks_extrapolated(recs, fps)
    for chains, label in ((raw_chains, "SHIPPED (raw distance)"),
                          (ext_chains, "TEST (motion projection)")):
        multi = [c for c in chains if len(c) > 1]
        joins = sum(len(c) - 1 for c in multi)
        print(f"  {label:26} chains={len(chains):>5}  multi={len(multi):>4}"
              f"  joins={joins:>4}")
    raw_pairs, ext_pairs = pairs_of(raw_chains), pairs_of(ext_chains)
    print(f"\n  joins ONLY the test finds:    {len(ext_pairs - raw_pairs)}")
    print(f"  joins ONLY the shipped finds: {len(raw_pairs - ext_pairs)}")
    print(f"  joins both agree on:          {len(raw_pairs & ext_pairs)}")

    if cam == 5 and variant == "l1_study_1100":
        print()
        for a, b, lab in ((108910, 108928, "B->C (operator: SAME vehicle)"),
                          (108873, 108910, "A->B (operator: DIFFERENT)")):
            print(f"  {lab:34} shipped="
                  f"{'JOIN' if (a, b) in raw_pairs else 'no':>4}   test="
                  f"{'JOIN' if (a, b) in ext_pairs else 'no':>4}")

    dbp = args.events_db or (
        f"data/projects/{PROJ}/_replay_scratch/c45_20260907/"
        f"cx_cam{cam}_{variant.replace('l1_', '')}.db")
    if Path(dbp).exists():
        s = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
        counted = {int(t): (o, d, mv) for t, o, d, mv in s.execute(
            "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
            "movement FROM vehicle_events WHERE camera_id=? AND rejected=0",
            (cam,))}
        s.close()
        succ = dict(ext_pairs)
        roots = set(succ) - set(succ.values())
        collapse = 0
        examples = []
        for r in roots:
            chain, cur = [r], r
            while cur in succ:
                cur = succ[cur]
                chain.append(cur)
            hits = [t for t in chain if t in counted]
            if len(hits) > 1:
                collapse += len(hits) - 1
                if len(examples) < 8:
                    examples.append([(t, counted[t][2]) for t in hits])
        print(f"\n  counted events in this window: {len(counted)}")
        print(f"  events the test would COLLAPSE (double counts): "
              f"{collapse}")
        print("  sample collapses (track, movement):")
        for e in examples:
            print(f"    {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
