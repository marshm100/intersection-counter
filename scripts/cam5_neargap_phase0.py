"""CAM5 NEAR-GAP phase 0 — component attribution of the six new-BIG bins
(plan_cam5_neargap_2026-07-29; operator-authorized cycle).

Leave-one-out ablations of the FROZEN LEC2 bundle at cam5 — constants
untouched, flags only: E (survivor keep-one), L (the lpatch40 widened
event stream), C (the thru-reroute default), R (zero-event-chain
resurrection). Chains/tags are built ONCE per window (flag-independent);
each arm is a cheap event-pipeline pass over them.

Per arm: per-bin 5/95 vs GT (rule595), the six target bins' fate, the
full-gate row (G1-G4b as in the 5.2 judgment). Output: the attribution
table — which component(s) manufacture each of the six bins.
Basis: replayed-minutes (BASE + lpatch40 DBs on disk).
Evidence -> runs/stage5_phantom/cam5_neargap_phase0.json
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.database import list_paths_for_camera
from backend.services.entry_gates import classify
from backend.services.path_divergence import (
    build_divergence_map, coverage_s_max, reaches_divergence)
from backend.services.rule595 import compliance, score_cells
from backend.services.track_chains import _end_speed
import cam5_wall_phase0 as P0
import lane_echo_phase0 as CE
from lane_echo_e_arm import chain_tracks_dirgated
from lane_echo_compound import R_MIN_SPAN_PX, _concurrent_dup
from lane_echo_sweep import (
    SWEEP, R_MIN_MEMBERS, gt_perminute, lec2_events, legcards, score)

PROJECT, CAM = "97a7849a", 5
WINDOWS = ["study_0700", "study_1100", "study_1600"]
HOURS = [(7, 9), (11, 13), (16, 18)]
OUT = Path("runs/stage5_phantom/cam5_neargap_phase0.json")
BIG = 20

TARGETS = [("07:30", "N through"), ("08:00", "N through"),
           ("08:15", "N through"), ("07:00", "S through"),
           ("11:00", "S through"), ("16:00", "S through")]

ARMS = [
    {"name": "full", "e": True, "l": True, "c": True, "r": True},
    {"name": "E_off", "e": False, "l": True, "c": True, "r": True},
    {"name": "L_off", "e": True, "l": False, "c": True, "r": True},
    {"name": "C_off", "e": True, "l": True, "c": False, "r": True},
    {"name": "R_off", "e": True, "l": True, "c": True, "r": False},
    # iteration 1 (phase-0-chosen): R off + E keeps one event PER
    # FULL-JOURNEY MEMBER (>=2 full tracks on a chain = distinct real
    # vehicles the chain over-linked; fragment echoes still collapse).
    # Constant-free narrowing of the same frozen machinery.
    {"name": "it1_Roff_Efulls", "e": "keep_fulls", "l": True, "c": True,
     "r": False},
    # iteration 2 (the budget's last): R off + E keeps K events per
    # chain where K = the chain's MAX TEMPORAL CONCURRENCY (fragments
    # of one vehicle are time-disjoint, so overlapping members are
    # provably distinct vehicles; K is a constant-free lower bound of
    # real vehicles on the chain). Echo chains have K=1 = today.
    {"name": "it2_Roff_Ekconc", "e": "keep_kconc", "l": True, "c": True,
     "r": False},
]


def window_context(w, scratch):
    """Everything flag-independent for one window: base/widened event
    streams, tracks, tags, chains, divergence maps."""
    import sqlite3
    base_db = scratch / f"cam{CAM}wall_stock_{w}.db"
    lp_db = scratch / f"cam{CAM}wall_lpatch40_{w}.db"
    assert base_db.exists() and lp_db.exists(), f"replay DBs missing for {w}"

    def load(db):
        out = []
        c = sqlite3.connect(str(db))
        for tid, o, d, mv, ts in c.execute(
                "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
                "movement, timestamp_real FROM vehicle_events WHERE "
                "camera_id=? AND COALESCE(rejected,0)=0", (CAM,)):
            out.append({"tid": tid, "o": o, "d": d, "mv": mv, "ts": ts})
        c.close()
        return out
    base_evs, lp_evs = load(base_db), load(lp_db)

    rows, fps = CE.load_rows(PROJECT, CAM, w)
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append(
            (float(r[1]), float(r[2]), float(r[3])))
    gates, _ = CE.pinned_gates(PROJECT, CAM)
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

    legcard = legcards(PROJECT, CAM)
    div_map = build_divergence_map(list_paths_for_camera(PROJECT, CAM))
    thru_by_origin, thru_cells = {}, {}
    for (o, d), info in div_map.items():
        nm = P0._cell_name(legcard, o, d)
        if nm and nm[1] == "thru":
            thru_by_origin[o] = d
            thru_cells[(o, d)] = info
    return {"base": base_evs, "lp": lp_evs, "tracks": tracks, "tags": tags,
            "gates": gates, "fps": fps, "chain_map": chain_map,
            "members": members, "legcard": legcard, "div_map": div_map,
            "thru_by_origin": thru_by_origin, "thru_cells": thru_cells}


def arm_events(ctx, e_on, l_on, c_on, r_on):
    """The frozen pipeline with component flags (constants untouched;
    mirrors lane_echo_sweep.lec2_events step for step)."""
    tracks, tags, fps = ctx["tracks"], ctx["tags"], ctx["fps"]
    chain_map, members = ctx["chain_map"], ctx["members"]
    div_map = ctx["div_map"]
    base_evs = ctx["base"]
    evs = list(ctx["lp"]) if l_on else list(ctx["base"])

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

    by_chain = defaultdict(list)
    singles = []
    for e in evs:
        ci = chain_map.get(e["tid"])
        (by_chain[ci] if ci is not None else singles).append(e)
    union_cache: dict[int, list] = {}

    def union_xy(ci):
        if ci not in union_cache:
            union_cache[ci] = [(p[1], p[2]) for tid in members[ci]
                               for p in tracks[tid]]
        return union_cache[ci]

    kept = list(singles)
    for ci, ce in by_chain.items():
        if len(ce) == 1 or not e_on:
            kept.extend(ce)
            continue
        uxy = union_xy(ci)

        def rank(e):
            reach = reaches_divergence(uxy, (e["o"], e["d"]), div_map)
            r0 = 0 if reach is True else (1 if reach is None else 2)
            return (r0, 0 if tags.get(e["tid"]) == "full" else 1,
                    -len(tracks.get(e["tid"], [])), e["tid"])
        if e_on == "keep_fulls":
            fulls = [e for e in ce if tags.get(e["tid"]) == "full"]
            if len(fulls) >= 2:
                kept.extend(fulls)       # distinct real vehicles, over-linked
                continue
        if e_on == "keep_kconc":
            spans = []
            for tid in members[ci]:
                pts = tracks.get(tid)
                if pts:
                    fr = [p[0] for p in pts]
                    spans.append((min(fr), max(fr)))
            edges = sorted([(s0, 1) for s0, _e1 in spans]
                           + [(e1, -1) for _s0, e1 in spans],
                           key=lambda t: (t[0], t[1]))
            cur = k = 0
            for _f, d in edges:
                cur += d
                k = max(k, cur)
            k = max(1, k)
            kept.extend(sorted(ce, key=rank)[:k])
            continue
        kept.append(sorted(ce, key=rank)[0])

    if c_on:
        filtered = []
        for e in kept:
            cell = (e["o"], e["d"])
            info = div_map.get(cell)
            nm = P0._cell_name(ctx["legcard"], *cell)
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
                d_thru = ctx["thru_by_origin"].get(e["o"])
                if d_thru is not None:
                    filtered.append({**e, "d": d_thru, "mv": "through"})
            else:
                filtered.append(e)
        kept = filtered

    if r_on:
        ev_ci = {chain_map.get(e["tid"]) for e in kept} - {None}
        for ci, tids in members.items():
            if len(tids) < R_MIN_MEMBERS or ci in ev_ci:
                continue
            uxy = union_xy(ci)
            upts = sorted(p for tid in tids for p in tracks[tid])
            _o, _d, *_rest, utag = classify(upts, ctx["gates"], fps)
            cell = None
            if utag == "full" and _o is not None and _d is not None and _o != _d:
                cell = (_o, _d)
            else:
                ub = CE._bearing(upts)
                best = None
                for (o, d), info in ctx["thru_cells"].items():
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
                nm = P0._cell_name(ctx["legcard"], *cell)
                kept.append({"tid": -ci, "o": cell[0], "d": cell[1],
                             "mv": ("through" if nm and nm[1] == "thru"
                                    else "left"),
                             "ts": near["ts"] if near else None})
    return kept


def main() -> int:
    scratch = Path(f"data/projects/{PROJECT}/_replay_scratch")
    gt = gt_perminute(PROJECT, CAM)
    legcard = legcards(PROJECT, CAM)
    mins = [dtime(h, m) for lo, hi in HOURS for h in range(lo, hi)
            for m in range(60)]

    print("[NG] building window contexts (chains once per window)…", flush=True)
    ctxs = {w: window_context(w, scratch) for w in WINDOWS}

    # base rows for gate deltas
    base_pm = defaultdict(lambda: defaultdict(int))
    for w in WINDOWS:
        for m, cells in score(ctxs[w]["base"], legcard).items():
            for kk, v in cells.items():
                base_pm[m][kk] += v
    rows_b = score_cells(base_pm, gt, mins)
    cb = compliance(rows_b)
    bmap = {(r["bin"], r["cell"]): r for r in rows_b}
    um_b = sum(max(0, r["ref"] - r["ours"]) for r in rows_b)

    # parity check: the 'full' arm must reproduce the committed judgment
    result: dict = {"base_compliance_pct": cb["pct"], "arms": {}}
    for arm in ARMS:
        pm = defaultdict(lambda: defaultdict(int))
        for w in WINDOWS:
            evl = arm_events(ctxs[w], arm["e"], arm["l"], arm["c"], arm["r"])
            for m, cells in score(evl, legcard).items():
                for kk, v in cells.items():
                    pm[m][kk] += v
        rows_l = score_cells(pm, gt, mins)
        cl = compliance(rows_l)
        lmap = {(r["bin"], r["cell"]): r for r in rows_l}
        fixed = broken = 0
        new_big = []
        for kk in set(bmap) | set(lmap):
            b_ok = bmap.get(kk, {"ok": True})["ok"]
            l_ok = lmap.get(kk, {"ok": True})["ok"]
            fixed += (not b_ok) and l_ok
            broken += b_ok and (not l_ok)
            l_r = lmap.get(kk)
            if l_r is not None and not l_ok and \
                    abs(l_r["ours"] - l_r["ref"]) >= BIG:
                b_r = bmap.get(kk)
                if not (b_r is not None and not b_r["ok"]
                        and abs(b_r["ours"] - b_r["ref"]) >= BIG):
                    new_big.append(kk)
        um_l = sum(max(0, r["ref"] - r["ours"]) for r in rows_l)
        targets = {}
        for tb, tc in TARGETS:
            r = lmap.get((tb, tc))
            targets[f"{tb} {tc}"] = {
                "ours": r["ours"] if r else None, "ref": r["ref"] if r else None,
                "big_fail": bool(r and not r["ok"]
                                 and abs(r["ours"] - r["ref"]) >= BIG)}
        gates = {
            "G1": (cl["pct"] or 0) > (cb["pct"] or 0),
            "G2": not new_big,
            "G3": fixed - broken > 0 and broken <= 0.2 * fixed,
            "G4b": um_l <= um_b * 1.05,
        }
        result["arms"][arm["name"]] = {
            "compliance_pct": cl["pct"], "fixed": fixed, "broken": broken,
            "new_big": [f"{b} {c}" for b, c in new_big][:10],
            "undercount": um_l, "targets": targets, "gates": gates,
            "all_pass": all(gates.values()),
        }
        cleared = [k for k, t in targets.items() if not t["big_fail"]]
        print(f"[NG] {arm['name']:>6}: 5/95 {cb['pct']}→{cl['pct']}%  "
              f"fixed {fixed} broken {broken} new_big {len(new_big)} "
              f"uc {um_b}→{um_l}  targets cleared {len(cleared)}/6  "
              f"{'ALL-GATES-PASS' if result['arms'][arm['name']]['all_pass'] else ''}",
              flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("NEARGAP PHASE0 DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
