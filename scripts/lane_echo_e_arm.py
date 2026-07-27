"""LANE+ECHO phase 1 — the E arm (echo suppression), replay-side A/B.
plan_cam5_lane_echo_2026-07-27 + phase-0 amendments.

E = direction-gated fragment chaining + AT MOST ONE COUNTED EVENT PER
CHAIN. No replays: the BASE out_db events are re-scored in memory with
chain-excess events removed. Components under test:

  - chain edges get the AMENDMENT-1 DIRECTION GATE: an edge A->B is
    dropped when the two tracks' overall bearings differ by more than
    BEARING_TOL (55 deg — the builder's bearing_tol class constant; the
    phase-0 census showed same-cell echo pairs at median 4-14 deg vs
    flip pairs at 66-180, and 785 flip pairs/day on held-out FM51 that
    an ungated dedup would have eaten);
  - keep-one preference per chain: journey-complete (gate tag 'full')
    member's event first, else the longest track's; ties by track id
    (deterministic).

E-alone is a DIAGNOSTIC arm (pre-declared): the amended invariant is vs
TRUTH ([0.97, 1.03] on NB-thru/SB-thru), and phase-0 predicts E-alone
lands NB-thru ~0.94 (dedup exposes the ~133 missing vehicles) — the
breach direction is the point: it sizes the recovery that L + union-claim
must supply in the shipping compound.

Usage: py scripts/lane_echo_e_arm.py [--windows ...]
Evidence -> runs/cam5_wall/e_arm.json. Replayed-minutes basis.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.entry_gates import classify
from backend.services.track_chains import (
    STITCH_MOVE_DIST, STITCH_MOVE_GAP_S, STITCH_STAT_DIST, STITCH_STAT_GAP_S,
    STITCH_STAT_SPEED_PXS, _end_speed)
import cam5_wall_phase0 as P0
import lane_echo_phase0 as CE
import triangulate_manual as T
from interval_metric import per_interval

BEARING_TOL = 55.0     # deg — the builder's bearing_tol class constant
PROJECT = "97a7849a"
CAM = 5
WINDOWS = ["study_0700", "study_1100", "study_1600"]
OUT = Path("runs/cam5_wall/e_arm.json")
TRUTH_BAND = (0.97, 1.03)
PROTECTED = [(39, 37), (37, 39)]


def chain_tracks_dirgated(recs, fps, tol=BEARING_TOL):
    """track_chains.chain_tracks with the Amendment-1 direction gate on
    candidate edges (overall-bearing consistency). Everything else — the
    frozen STITCH_* constants, tag gating, greedy matching — verbatim."""
    rs = sorted(recs, key=lambda r: r["birth"][0])
    births = [r["birth"][0] for r in rs]
    A_OK = ("entry_only", "no_crossing")
    B_OK = ("exit_only", "no_crossing")
    cands = []
    cut = 0
    for ai, a in enumerate(rs):
        if a["tag"] not in A_OK:
            continue
        fa, xa, ya = a["death"]
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
            dist = math.hypot(b["birth"][1] - xa, b["birth"][2] - ya)
            moving = (STITCH_MOVE_GAP_S[0] * fps <= gap
                      <= STITCH_MOVE_GAP_S[1] * fps
                      and dist <= STITCH_MOVE_DIST)
            stat = (a_slow and 0 < gap <= STITCH_STAT_GAP_S * fps
                    and dist <= STITCH_STAT_DIST)
            if not (moving or stat):
                continue
            if CE._ang_diff(a["bearing"], b["bearing"]) > tol:
                cut += 1
                continue
            cands.append((dist + 0.5 * max(gap, 0.0), ai, bi))
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
    return chains, cut


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default=",".join(WINDOWS))
    ap.add_argument("--tol", type=float, default=BEARING_TOL)
    args = ap.parse_args()
    windows = args.windows.split(",")

    gates, _anchors = CE.pinned_gates(PROJECT, CAM)
    mio = T.load_miovision(CAM)
    legcard = P0._legs(sqlite3.connect(f"data/projects/{PROJECT}/project.db"))
    scratch = Path(f"data/projects/{PROJECT}/_replay_scratch")

    result = {"tol": args.tol}
    ours_base = defaultdict(lambda: defaultdict(int))
    ours_e = defaultdict(lambda: defaultdict(int))
    cells_base_all = Counter()
    cells_e_all = Counter()
    for w in windows:
        rows, fps = CE.load_rows(PROJECT, CAM, w)
        tracks: dict[int, list] = {}
        for r in rows:
            tracks.setdefault(int(r[0]), []).append(
                (float(r[1]), float(r[2]), float(r[3])))
        recs, tags = [], {}
        for tid, pts in tracks.items():
            pts = sorted(pts)
            if len(pts) < 5:
                continue
            _o, _d, *_rest, tag = classify(pts, gates, fps)
            tags[tid] = tag
            recs.append({"tid": tid,
                         "birth": (pts[0][0], pts[0][1], pts[0][2]),
                         "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
                         "tag": tag, "v_end": _end_speed(pts),
                         "bearing": CE._bearing(pts)})
        chains, cut = chain_tracks_dirgated(recs, fps, args.tol)
        chain_map = {r["tid"]: ci for ci, ch in enumerate(chains) for r in ch}

        # events from the BASE DB, with timestamps for scoring
        db = scratch / f"cam5wall_stock_{w}.db"
        evs = []
        c = sqlite3.connect(str(db))
        for eid, tid, o, d, mv, ts in c.execute(
                "SELECT event_id, vehicle_track_id, origin_leg_id, "
                "destination_leg_id, movement, timestamp_real FROM "
                "vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0",
                (CAM,)):
            evs.append({"eid": eid, "tid": tid, "o": o, "d": d, "mv": mv,
                        "ts": ts})
        c.close()

        # keep-one per chain
        by_chain = defaultdict(list)
        singles = []
        for e in evs:
            ci = chain_map.get(e["tid"])
            (by_chain[ci] if ci is not None else singles).append(e)
        kept, rejected = list(singles), []
        survivor_cells = Counter()
        for ci, ce in by_chain.items():
            if len(ce) == 1:
                kept.append(ce[0])
                continue
            def rank(e):
                full = tags.get(e["tid"]) == "full"
                npts = len(tracks.get(e["tid"], []))
                return (0 if full else 1, -npts, e["tid"])
            ce_sorted = sorted(ce, key=rank)
            kept.append(ce_sorted[0])
            rejected.extend(ce_sorted[1:])
            if len(ce) >= 2:
                survivor_cells[f"{ce_sorted[0]['o']}>{ce_sorted[0]['d']}"] += 1

        # score both arms
        norm = {"through": "thru", "u_turn": "uturn"}
        leg_dir = {lid: T._CARD_TO_DIR.get(cd) for lid, cd in legcard.items()}
        for arm, evlist, pm, cell_ctr in (
                ("base", evs, ours_base, cells_base_all),
                ("e", kept, ours_e, cells_e_all)):
            for e in evlist:
                ddir = leg_dir.get(e["o"])
                if e["ts"] and ddir:
                    key = datetime.fromisoformat(e["ts"]).time().replace(
                        second=0, microsecond=0)
                    pm[key][(ddir, norm.get(e["mv"], e["mv"]))] += 1
                    cell_ctr[(e["o"], e["d"])] += 1

        result[w] = {
            "edges_cut_by_direction_gate": cut,
            "n_events_base": len(evs), "n_rejected": len(rejected),
            "rejected_cells": dict(Counter(
                f"{e['o']}>{e['d']}" for e in rejected).most_common(10)),
            "survivor_cells_multi": dict(survivor_cells.most_common(10)),
        }
        print(f"[E] {w}: cut_edges={cut} rejected={len(rejected)} "
              f"rejected_cells={result[w]['rejected_cells']}", flush=True)

    # pooled scoring, both arms
    mins = P0.window_minutes(windows)
    for arm, pm in (("base", ours_base), ("e", ours_e)):
        res = per_interval(pm, mio, minutes=mins, by_approach=True)
        result[f"score_{arm}"] = {
            "total": res["avg_abs_err_pct"],
            "per_approach": {d: r["avg_abs_err_pct"]
                             for d, r in res["per_approach"].items()
                             if r["n_bins"]}}
        print(f"[E] {arm.upper()} pooled {result[f'score_{arm}']}", flush=True)

    # per-cell table + invariant check vs truth
    magg = T._agg(mio, [m for m in mins if m in mio])
    cell_rows = []
    inv = {}
    for cell in sorted(set(cells_base_all) | set(cells_e_all)):
        name = P0._cell_name(legcard, *cell)
        ref = magg.get(name, 0) if name else 0
        row = {"cell": f"{cell[0]}>{cell[1]}",
               "base": cells_base_all.get(cell, 0),
               "e": cells_e_all.get(cell, 0), "mio": ref}
        cell_rows.append(row)
        if cell in PROTECTED and ref:
            r = row["e"] / ref
            inv[row["cell"]] = {"ratio": round(r, 3),
                                "in_band": TRUTH_BAND[0] <= r <= TRUTH_BAND[1]}
    result["cells"] = cell_rows
    result["invariant_vs_truth"] = inv
    print(f"[E] protected-cell invariant: {json.dumps(inv)}", flush=True)
    for row in cell_rows:
        if row["mio"] >= 30 or abs(row["base"] - row["e"]) >= 10:
            print(f"[E] {row['cell']:>7} base {row['base']:>5} "
                  f"e {row['e']:>5} mio {row['mio']:>5}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("E-ARM DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
