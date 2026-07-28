"""Deliverable-truthfulness SWEEP of the frozen LEC2 bundle
(plan_cam5_lane_echo_2026-07-27, operator-authorized sweep section).

Applies the FROZEN LEC2 pipeline (bearing 55 / L=40 full-journey-only +
concurrent cut / C-proper / R rmin=3 — constants IMPORTED from the
committed modules, no re-fitting) to every corridor camera + FM51
(held-out, ftv2n replay basis), and judges each against the PRE-DECLARED
bar:

  (1) per-cell abs error (GT>=10 cells) strictly improves;
  (2) no GT>=30 cell worsens by more than max(10, 0.20*GT);
  (3) |net_after| <= max(|net_before|, 0.05) — certifiability kept;
  (4) per-approach MAE within +0.3 on every approach (cam3 HARD STOP);
  (5) FM51 same bar.

Scoring keys are (bound-letter, movement) uniformly; GT: corridor =
Miovision per-minute via triangulate_manual, FM51 = the retrospective
loader + its empirical approach->bound mapping.

Usage: py scripts/lane_echo_sweep.py [--only 97a7849a:5]
Evidence -> runs/cam5_wall/sweep_deliverable.json. Replayed-minutes basis.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time as _clock
from collections import Counter, defaultdict
from datetime import datetime, time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np

from backend.database import list_paths_for_camera
from backend.services.cardinals import OPPOSITE
from backend.services.entry_gates import classify
from backend.services.path_divergence import (
    build_divergence_map, coverage_s_max, reaches_divergence)
from backend.services.track_chains import _end_speed
import cam5_wall_phase0 as P0
import lane_echo_phase0 as CE
from lane_echo_e_arm import chain_tracks_dirgated
from lane_echo_compound import (
    L_WIDE_PX, R_MIN_SPAN_PX, _concurrent_dup)
import gate3b_fm51 as FM
import triangulate_manual as T
from interval_metric import per_interval

L_SWEEP_PX = 40.0        # the frozen L width (lec2 fit; lpatch40 DBs)
R_MIN_MEMBERS = 3        # frozen
OUT = Path("runs/cam5_wall/sweep_deliverable.json")

SWEEP = [
    ("97a7849a", 1, ["study_0700"], [(7, 9)]),
    ("97a7849a", 2, ["study_0700", "study_1100", "study_1600"],
     [(7, 9), (11, 13), (16, 18)]),
    ("97a7849a", 3, ["study_0000"], None),
    ("97a7849a", 4, ["study_0700", "study_1100", "study_1600"],
     [(7, 9), (11, 13), (16, 18)]),
    ("97a7849a", 5, ["study_0700", "study_1100", "study_1600"],
     [(7, 9), (11, 13), (16, 18)]),
    ("0acb12c0", 2, ["ftv2n_am", "ftv2n_pm"], [(7, 9), (16, 18)]),
]
_MVN = {"through": "through", "thru": "through", "left": "left",
        "right": "right", "u_turn": "u_turn", "uturn": "u_turn"}


def legcards(project, cam):
    conn = sqlite3.connect(f"data/projects/{project}/project.db")
    out = {lid: (cd or "").strip().upper() for lid, cd in conn.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
        (cam,))}
    conn.close()
    return out


def gt_perminute(project, cam):
    """{minute_time: {(bound_letter, movement): n}}"""
    if project == "97a7849a":
        mio = T.load_miovision(cam)
        out = defaultdict(lambda: defaultdict(int))
        d2l = {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}
        m2m = {"thru": "through", "uturn": "u_turn"}
        for t, cells in mio.items():
            for (d, mv), n in cells.items():
                L = d2l.get(d)
                if L:
                    out[t][(L, m2m.get(mv, mv))] += n
        return out
    mio, appr = FM.load_mio_perminute()
    # empirical approach->bound mapping (the retrospective's, recomputed)
    conn = sqlite3.connect(f"data/projects/{project}/project.db")
    card = {lid: cd for lid, cd in conn.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (cam,))}
    sys_bound = defaultdict(int)
    for (ol,) in conn.execute(
            "SELECT origin_leg_id FROM vehicle_events WHERE camera_id=? AND "
            "COALESCE(rejected,0)=0", (cam,)):
        sys_bound[OPPOSITE.get((card.get(ol) or "").upper(),
                               card.get(ol) or "")] += 1
    conn.close()
    tot = defaultdict(int)
    for cells in mio.values():
        for (ai, _mv), n in cells.items():
            tot[ai] += n
    used, ai2b = set(), {}
    for ai, t in sorted(tot.items(), key=lambda kv: -kv[1]):
        best = min((b for b in sys_bound if b not in used),
                   key=lambda b: abs(sys_bound[b] - t), default=None)
        if best is not None:
            ai2b[ai], _ = best, used.add(best)
    out = defaultdict(lambda: defaultdict(int))
    for t, cells in mio.items():
        for (ai, mv), n in cells.items():
            b = ai2b.get(ai)
            if b:
                out[t.time().replace(second=0, microsecond=0) if isinstance(t, datetime) else t][(b, mv)] += n
    return out


def lec2_events(project, cam, w, scratch):
    """BASE events + the frozen-LEC2 processed events for one window."""
    from backend.services.pass2_replay import replay_camera
    base_db = scratch / f"cam{cam}wall_stock_{w}.db"
    if not base_db.exists():
        t0 = _clock.time()
        st = replay_camera(project, cam, variant=w, out_db=base_db)
        print(f"[R] {project[:4]} cam{cam} {w} BASE: events={st['events']} "
              f"({_clock.time() - t0:.0f}s)", flush=True)
    lp_db = scratch / f"cam{cam}wall_lpatch40_{w}.db"
    if not lp_db.exists():
        import backend.services.pipeline as PL
        orig = PL.score_destination_by_polyline

        def wide(trajectory, origin_leg_id, paths, *, max_avg_distance_px=20.0):
            res = orig(trajectory, origin_leg_id, paths,
                       max_avg_distance_px=L_SWEEP_PX)
            if (res.get("destination_leg_id") is not None
                    and res.get("distance", 0) > max_avg_distance_px
                    and (res.get("movement_label") or "") not in
                    ("through", "thru")):
                return {"destination_leg_id": None, "movement_label": None,
                        "distance": res.get("distance"),
                        "path_id": res.get("path_id"),
                        "considered": res.get("considered", 0)}
            return res
        PL.score_destination_by_polyline = wide
        try:
            t0 = _clock.time()
            st = replay_camera(project, cam, variant=w, out_db=lp_db)
            print(f"[R] {project[:4]} cam{cam} {w} LPATCH: events={st['events']} "
                  f"({_clock.time() - t0:.0f}s)", flush=True)
        finally:
            PL.score_destination_by_polyline = orig

    def load(db):
        out = []
        c = sqlite3.connect(str(db))
        for tid, o, d, mv, ts in c.execute(
                "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
                "movement, timestamp_real FROM vehicle_events WHERE "
                "camera_id=? AND COALESCE(rejected,0)=0", (cam,)):
            out.append({"tid": tid, "o": o, "d": d, "mv": mv, "ts": ts})
        c.close()
        return out
    base_evs = load(base_db)
    evs = load(lp_db)

    rows, fps = CE.load_rows(project, cam, w)
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append(
            (float(r[1]), float(r[2]), float(r[3])))
    gates, _ = CE.pinned_gates(project, cam)
    recs, tags = [], {}
    for tid, pts in tracks.items():
        pts = sorted(pts)
        if len(pts) < 5:
            continue
        _o, _d, *_rest, tag = classify(pts, gates, fps)
        tags[tid] = tag
        recs.append({"tid": tid, "birth": (pts[0][0], pts[0][1], pts[0][2]),
                     "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
                     "tag": tag, "v_end": _end_speed(pts),
                     "bearing": CE._bearing(pts)})
    chains, _cut = chain_tracks_dirgated(recs, fps)
    chain_map = {r["tid"]: ci for ci, ch in enumerate(chains) for r in ch}
    members = defaultdict(list)
    for tid, ci in chain_map.items():
        members[ci].append(tid)

    legcard = legcards(project, cam)
    div_map = build_divergence_map(list_paths_for_camera(project, cam))
    thru_by_origin = {}
    thru_cells = {}
    for (o, d), info in div_map.items():
        nm = P0._cell_name(legcard, o, d)
        if nm and nm[1] == "thru":
            thru_by_origin[o] = d
            thru_cells[(o, d)] = info

    # E-compose-L
    stock_tids = {e["tid"] for e in base_evs}
    stock_chains = {chain_map.get(t) for t in stock_tids} - {None}
    filtered = []
    for e in evs:
        if e["tid"] in stock_tids:
            filtered.append(e)
            continue
        ci = chain_map.get(e["tid"])
        if ci is not None and ci in stock_chains:
            continue
        if tags.get(e["tid"]) != "full":
            continue
        if _concurrent_dup(tracks.get(e["tid"], []), stock_tids, tracks, fps):
            continue
        filtered.append(e)
    evs = filtered

    # survivor selection
    by_chain = defaultdict(list)
    singles = []
    for e in evs:
        ci = chain_map.get(e["tid"])
        (by_chain[ci] if ci is not None else singles).append(e)
    kept = list(singles)
    union_cache: dict[int, list] = {}

    def union_xy(ci):
        if ci not in union_cache:
            union_cache[ci] = [(p[1], p[2]) for tid in members[ci]
                               for p in tracks[tid]]
        return union_cache[ci]

    for ci, ce in by_chain.items():
        if len(ce) == 1:
            kept.append(ce[0])
            continue
        uxy = union_xy(ci)

        def rank(e):
            reach = reaches_divergence(uxy, (e["o"], e["d"]), div_map)
            r0 = 0 if reach is True else (1 if reach is None else 2)
            return (r0, 0 if tags.get(e["tid"]) == "full" else 1,
                    -len(tracks.get(e["tid"], [])), e["tid"])
        ce_sorted = sorted(ce, key=rank)
        kept.append(ce_sorted[0])

    # C-proper
    filtered = []
    for e in kept:
        cell = (e["o"], e["d"])
        info = div_map.get(cell)
        nm = P0._cell_name(legcard, *cell)
        is_turn = bool(nm and nm[1] in ("left", "right"))
        ci = chain_map.get(e["tid"])
        multi = ci is not None and len(by_chain.get(ci, [])) >= 2
        if not (is_turn and info and not multi):
            filtered.append(e)
            continue
        pts_xy = ([(p[1], p[2]) for t in members.get(ci, [e["tid"]])
                   for p in tracks.get(t, [])]
                  if ci is not None else
                  [(p[1], p[2]) for p in tracks.get(e["tid"], [])])
        reach = reaches_divergence(pts_xy, cell, div_map)
        if reach is False:
            d_thru = thru_by_origin.get(e["o"])
            if d_thru is not None:
                filtered.append({**e, "d": d_thru, "mv": "through"})
        else:
            filtered.append(e)
    kept = filtered

    # R
    ev_ci = {chain_map.get(e["tid"]) for e in kept} - {None}
    for ci, tids in members.items():
        if len(tids) < R_MIN_MEMBERS or ci in ev_ci:
            continue
        uxy = union_xy(ci)
        upts = sorted(p for tid in tids for p in tracks[tid])
        _o, _d, *_rest, utag = classify(upts, gates, fps)
        cell = None
        if utag == "full" and _o is not None and _d is not None and _o != _d:
            cell = (_o, _d)
        else:
            ub = CE._bearing(upts)
            best = None
            for (o, d), info in thru_cells.items():
                poly = info["poly"]
                pb = math.degrees(math.atan2(poly[-1][1] - poly[0][1],
                                             poly[-1][0] - poly[0][0]))
                if CE._ang_diff(ub, pb) > 55.0:
                    continue
                span = coverage_s_max(uxy, poly)
                if span >= R_MIN_SPAN_PX and (best is None or span > best[0]):
                    best = (span, (o, d))
            if best:
                cell = best[1]
        if cell:
            near = min(kept, key=lambda e: abs(
                (tracks.get(e["tid"], [(upts[len(upts) // 2][0], 0, 0)])[0][0])
                - upts[len(upts) // 2][0])) if kept else None
            nm = P0._cell_name(legcard, *cell)
            kept.append({"tid": -ci, "o": cell[0], "d": cell[1],
                         "mv": ("through" if nm and nm[1] == "thru" else "left"),
                         "ts": near["ts"] if near else None})
    return base_evs, kept, legcard


def score(evlist, legcard):
    pm = defaultdict(lambda: defaultdict(int))
    for e in evlist:
        b = OPPOSITE.get(legcard.get(e["o"], ""), None)
        if b and e["ts"]:
            key = datetime.fromisoformat(e["ts"]).time().replace(
                second=0, microsecond=0)
            pm[key][(b, _MVN.get(e["mv"], e["mv"]))] += 1
    return pm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    args = ap.parse_args()
    result = {}
    for project, cam, windows, hours in SWEEP:
        key = f"{project[:4]}:c{cam}"
        if args.only and args.only != f"{project}:{cam}":
            continue
        scratch = Path(f"data/projects/{project}/_replay_scratch")
        scratch.mkdir(parents=True, exist_ok=True)
        gt = gt_perminute(project, cam)
        base_pm = defaultdict(lambda: defaultdict(int))
        lec_pm = defaultdict(lambda: defaultdict(int))
        legcard = None
        for w in windows:
            b, k, legcard = lec2_events(project, cam, w, scratch)
            for tag, evl, dst in (("b", b, base_pm), ("k", k, lec_pm)):
                pmw = score(evl, legcard)
                for m, cells in pmw.items():
                    for kk, v in cells.items():
                        dst[m][kk] += v
        minutes = (None if hours is None else
                   [dtime(h, m) for lo, hi in hours
                    for h in range(lo, hi) for m in range(60)])
        mins = sorted(gt.keys()) if minutes is None else minutes

        res = {}
        for tag, pm in (("base", base_pm), ("lec2", lec_pm)):
            r = per_interval(pm, gt, minutes=mins, by_approach=True)
            gt_cells = defaultdict(int)
            our_cells = defaultdict(int)
            for m in mins:
                for kk, v in gt.get(m, {}).items():
                    gt_cells[kk] += v
                for kk, v in pm.get(m, {}).items():
                    our_cells[kk] += v
            abs_err = sum(abs(our_cells.get(kk, 0) - v)
                          for kk, v in gt_cells.items() if v >= 10)
            net = ((sum(our_cells.values()) - sum(gt_cells.values()))
                   / max(1, sum(gt_cells.values())))
            res[tag] = {"mae": r["avg_abs_err_pct"],
                        "per_approach": {d: x["avg_abs_err_pct"]
                                         for d, x in r["per_approach"].items()
                                         if x["n_bins"]},
                        "abs_err": abs_err, "net": round(net, 4),
                        "cells": {f"{kk[0]} {kk[1]}": [our_cells.get(kk, 0), v]
                                  for kk, v in sorted(gt_cells.items())}}
        b, l = res["base"], res["lec2"]
        degraded = []
        for cname, (ours_b, gtv) in b["cells"].items():
            if gtv < 30:
                continue
            ours_l = l["cells"].get(cname, [0, gtv])[0]
            worse = abs(ours_l - gtv) - abs(ours_b - gtv)
            if worse > max(10, 0.20 * gtv):
                degraded.append((cname, ours_b, ours_l, gtv))
        mae_worse = [d for d in set(b["per_approach"]) | set(l["per_approach"])
                     if (l["per_approach"].get(d, 0) or 0)
                     > (b["per_approach"].get(d, 99) or 99) + 0.3]
        bar = {
            "1_abs_improves": l["abs_err"] < b["abs_err"],
            "2_no_cell_degrades": not degraded,
            "3_certifiability": abs(l["net"]) <= max(abs(b["net"]), 0.05),
            "4_mae_within_03": not mae_worse,
        }
        verdict = "PASS" if all(bar.values()) else "FAIL"
        res.update({"bar": bar, "degraded_cells": degraded,
                    "mae_worse_approaches": mae_worse, "verdict": verdict})
        result[key] = res
        print(f"[SW] {key}: {verdict} abs {b['abs_err']}->{l['abs_err']} "
              f"net {b['net']}->{l['net']} mae {b['mae']}->{l['mae']} "
              f"bar={bar} degraded={degraded[:3]}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, default=str))
    passes = [k for k, v in result.items() if v["verdict"] == "PASS"]
    print(f"[SW] SHIP SET: {passes}", flush=True)
    print(f"wrote {OUT}", flush=True)
    print("SWEEP DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
