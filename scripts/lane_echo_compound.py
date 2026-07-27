"""LANE+ECHO phase 1 — EC and LEC arms (plan_cam5_lane_echo_2026-07-27,
post-E-alone amendments).

EC  = direction-gated chains + DIVERGENCE-AWARE survivor selection
      (fixes E-alone's cell-agnostic keep-one, which let stub LEFTS
      survive over their vehicle's THRU: 820 NB-thru vs 100 NB-left
      rejected). Pure post-processing of BASE events.
LEC = EC + L (lateral acceptance 20->45 px at the fallback polyline
      tier, THROUGH winners only — turn winners keep the 20 px gate;
      needs patched replays) + R (conservative recovery: MULTI-MEMBER
      zero-event chains only — union gate-full claims its gate cell;
      else best-covered bearing-consistent THRU path with coverage
      span >= 60 px (2*AMBIGUITY_PX) claims thru).

Survivor rank per multi-event chain (Amendment: E+C fused):
  (union coverage reaches the event cell's divergence: True < None <
   False) then (gate tag full first) then longest track, then tid.

Usage: py scripts/lane_echo_compound.py --arm ec|lec [--windows ...]
Evidence -> runs/cam5_wall/{arm}_arm.json. Replayed-minutes basis.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time as _clock
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.database import list_paths_for_camera
from backend.services.entry_gates import classify
from backend.services.path_divergence import (
    AMBIGUITY_PX, build_divergence_map, coverage_s_max, reaches_divergence)
from backend.services.track_chains import _end_speed
import cam5_wall_phase0 as P0
import lane_echo_phase0 as CE
from lane_echo_e_arm import BEARING_TOL, chain_tracks_dirgated
import triangulate_manual as T
from interval_metric import per_interval

PROJECT = "97a7849a"
CAM = 5
WINDOWS = ["study_0700", "study_1100", "study_1600"]
TRUTH_BAND = (0.97, 1.03)
PROTECTED = [(39, 37), (37, 39)]
L_WIDE_PX = 45.0          # widened fallback acceptance, THROUGH winners only
R_MIN_SPAN_PX = 2 * AMBIGUITY_PX   # recovery coverage floor (60 px)


CONC_MIN_OVERLAP_S = 1.0
CONC_MAX_DIST_PX = 35.0


def _concurrent_dup(pts, counted_tids, tracks, fps) -> bool:
    """True when `pts` overlaps a counted track in time by >= 1 s with a
    mean same-frame distance <= 35 px (same physical vehicle, two tracks)."""
    if not pts:
        return False
    pts = sorted(pts)
    by_f = {int(p[0]): (p[1], p[2]) for p in pts}
    f_lo, f_hi = int(pts[0][0]), int(pts[-1][0])
    need = int(CONC_MIN_OVERLAP_S * fps)
    for tid in counted_tids:
        opts = tracks.get(tid)
        if not opts:
            continue
        opts = sorted(opts)
        if int(opts[-1][0]) < f_lo or int(opts[0][0]) > f_hi:
            continue
        ds = [math.hypot(x - by_f[int(f)][0], y - by_f[int(f)][1])
              for f, x, y in opts if int(f) in by_f]
        if len(ds) >= need and sum(ds) / len(ds) <= CONC_MAX_DIST_PX:
            return True
    return False


def _l_patched_replay(w: str, out_db: Path):
    """Replay with score_destination_by_polyline widened to L_WIDE_PX for
    THROUGH winners only (turn winners re-rejected past the stock 20 px)."""
    import backend.services.pipeline as PL
    from backend.services.pass2_replay import replay_camera
    orig = PL.score_destination_by_polyline

    def wide(trajectory, origin_leg_id, paths, *, max_avg_distance_px=20.0):
        res = orig(trajectory, origin_leg_id, paths,
                   max_avg_distance_px=L_WIDE_PX)
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
        return replay_camera(PROJECT, CAM, variant=w, out_db=out_db)
    finally:
        PL.score_destination_by_polyline = orig


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["ec", "lec", "lec2"], default="ec")
    ap.add_argument("--windows", default=",".join(WINDOWS))
    ap.add_argument("--lwide", type=float, default=None,
                    help="override L_WIDE_PX (lec2 fit; changes the lpatch "
                         "DB name so variants coexist)")
    ap.add_argument("--r-min-members", type=int, default=2)
    ap.add_argument("--label", default=None,
                    help="evidence-file suffix for fit variants")
    args = ap.parse_args()
    windows = args.windows.split(",")
    arm = args.arm
    global L_WIDE_PX
    if args.lwide is not None:
        L_WIDE_PX = args.lwide
    suffix = f"_{args.label}" if args.label else ""
    outp = Path(f"runs/cam5_wall/{arm}_arm{suffix}.json")
    scratch = Path(f"data/projects/{PROJECT}/_replay_scratch")
    lpatch_tag = f"lpatch{int(L_WIDE_PX)}" if L_WIDE_PX != 45.0 else "lpatch"

    gates, _anch = CE.pinned_gates(PROJECT, CAM)
    mio = T.load_miovision(CAM)
    legcard = P0._legs(sqlite3.connect(f"data/projects/{PROJECT}/project.db"))
    div_map = build_divergence_map(list_paths_for_camera(PROJECT, CAM))
    thru_cells = {(o, d): info for (o, d), info in div_map.items()
                  if P0._cell_name(legcard, o, d)
                  and P0._cell_name(legcard, o, d)[1] == "thru"}

    result = {"arm": arm, "bearing_tol": BEARING_TOL,
              "l_wide_px": L_WIDE_PX if arm == "lec" else None,
              "r_min_span": R_MIN_SPAN_PX if arm == "lec" else None}
    ours = {"base": defaultdict(lambda: defaultdict(int)),
            arm: defaultdict(lambda: defaultdict(int))}
    cells = {"base": Counter(), arm: Counter()}
    norm = {"through": "thru", "u_turn": "uturn"}
    leg_dir = {lid: T._CARD_TO_DIR.get(cd) for lid, cd in legcard.items()}

    def _score_ev(tag, e):
        d = leg_dir.get(e["o"])
        if e["ts"] and d:
            key = datetime.fromisoformat(e["ts"]).time().replace(
                second=0, microsecond=0)
            ours[tag][key][(d, norm.get(e["mv"], e["mv"]))] += 1
            cells[tag][(e["o"], e["d"])] += 1

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
        chains, _cut = chain_tracks_dirgated(recs, fps)
        chain_map = {r["tid"]: ci for ci, ch in enumerate(chains) for r in ch}
        members = defaultdict(list)
        for tid, ci in chain_map.items():
            members[ci].append(tid)

        # BASE events (always from the stock replay for the base arm score)
        base_db = scratch / f"cam5wall_stock_{w}.db"
        # arm events come from the stock DB (ec) or the L-patched replay
        if arm in ("lec", "lec2"):
            arm_db = scratch / f"cam5wall_{lpatch_tag}_{w}.db"
            if not arm_db.exists():
                t0 = _clock.time()
                st = _l_patched_replay(w, arm_db)
                print(f"[L] {w}: events={st['events']} "
                      f"({_clock.time() - t0:.0f}s)", flush=True)
        else:
            arm_db = base_db

        def load_events(db):
            out = []
            c = sqlite3.connect(str(db))
            for tid, o, d, mv, ts in c.execute(
                    "SELECT vehicle_track_id, origin_leg_id, "
                    "destination_leg_id, movement, timestamp_real FROM "
                    "vehicle_events WHERE camera_id=? AND "
                    "COALESCE(rejected,0)=0", (CAM,)):
                out.append({"tid": tid, "o": o, "d": d, "mv": mv, "ts": ts})
            c.close()
            return out

        base_evs = load_events(base_db)
        for e in base_evs:
            _score_ev("base", e)
        evs = load_events(arm_db)

        # lec2 E-compose-L: an L-ADDED event (its track has no stock event)
        # survives only if its chain carried NO stock-counted event — the
        # widened gate rescues uncovered VEHICLES, never extra fragments of
        # counted ones (the LEC 1.093 overshoot fix).
        n_lcut = 0
        if arm == "lec2":
            stock_tids = {e["tid"] for e in base_evs}
            stock_chains = {chain_map.get(t) for t in stock_tids} - {None}
            filtered = []
            for e in evs:
                if e["tid"] in stock_tids:
                    filtered.append(e)
                    continue
                ci = chain_map.get(e["tid"])
                if ci is not None and ci in stock_chains:
                    n_lcut += 1
                    continue
                # the diagnosed lateral class is JOURNEY-COMPLETE (the
                # single_full 258); a non-full track rescued by the wider
                # gate is an unchained fragment, not a missing vehicle
                if tags.get(e["tid"]) != "full":
                    n_lcut += 1
                    continue
                # concurrent-duplicate cut: an L-admitted full whose
                # trajectory overlaps a COUNTED track in time (>=1 s) at
                # lane distance (<=35 px mean) is the same vehicle counted
                # twice — sequential chaining cannot link concurrent
                # tracks by construction.
                if _concurrent_dup(tracks.get(e["tid"], []), stock_tids,
                                   tracks, fps):
                    n_lcut += 1
                    continue
                filtered.append(e)
            evs = filtered

        # union pointlists per chain (x, y only), computed lazily
        union_cache: dict[int, list] = {}

        def union_xy(ci):
            if ci not in union_cache:
                union_cache[ci] = [(p[1], p[2]) for tid in members[ci]
                                   for p in tracks[tid]]
            return union_cache[ci]

        # survivor selection per multi-event chain
        by_chain = defaultdict(list)
        singles = []
        for e in evs:
            ci = chain_map.get(e["tid"])
            (by_chain[ci] if ci is not None else singles).append(e)
        kept = list(singles)
        n_rej = 0
        rej_cells = Counter()
        for ci, ce in by_chain.items():
            if len(ce) == 1:
                kept.append(ce[0])
                continue
            uxy = union_xy(ci)

            def rank(e):
                reach = reaches_divergence(uxy, (e["o"], e["d"]), div_map)
                r0 = 0 if reach is True else (1 if reach is None else 2)
                full = 0 if tags.get(e["tid"]) == "full" else 1
                return (r0, full, -len(tracks.get(e["tid"], [])), e["tid"])
            ce_sorted = sorted(ce, key=rank)
            kept.append(ce_sorted[0])
            n_rej += len(ce_sorted) - 1
            for e in ce_sorted[1:]:
                rej_cells[f"{e['o']}>{e['d']}"] += 1

        # C-proper (lec2): singleton TURN claims must reach their cell's
        # divergence; ineligible claims re-route to the origin's thru
        # sibling (the geometric no-turn prior), else drop.
        n_creroute = n_cdrop = 0
        if arm == "lec2":
            thru_by_origin = {o: d for (o, d) in thru_cells}
            filtered = []
            for e in kept:
                cell = (e["o"], e["d"])
                info = div_map.get(cell)
                name = P0._cell_name(legcard, *cell)
                is_turn = bool(name and name[1] in ("left", "right"))
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
                        n_creroute += 1
                    else:
                        n_cdrop += 1
                else:
                    filtered.append(e)
            kept = filtered

        # R: conservative recovery — multi-member zero-event chains
        n_rec = 0
        rec_cells = Counter()
        if arm in ("lec", "lec2"):
            ev_ci = {chain_map.get(e["tid"]) for e in kept} - {None}
            for ci, tids in members.items():
                if len(tids) < args.r_min_members or ci in ev_ci:
                    continue
                uxy = union_xy(ci)
                upts = sorted(p for tid in tids for p in tracks[tid])
                _o, _d, *_rest, utag = classify(upts, gates, fps)
                cell = None
                if utag == "full" and _o is not None and _d is not None \
                        and _o != _d:
                    cell = (_o, _d)
                else:
                    ub = CE._bearing(upts)
                    best = None
                    for (o, d), info in thru_cells.items():
                        poly = info["poly"]
                        pb = math.degrees(math.atan2(
                            poly[-1][1] - poly[0][1], poly[-1][0] - poly[0][0]))
                        if CE._ang_diff(ub, pb) > BEARING_TOL:
                            continue
                        span = coverage_s_max(uxy, poly)
                        if span >= R_MIN_SPAN_PX and (best is None
                                                      or span > best[0]):
                            best = (span, (o, d))
                    if best:
                        cell = best[1]
                if cell:
                    mid = upts[len(upts) // 2]
                    frame0 = mid[0]
                    # timestamp: derive from any member event? none exist —
                    # use the window's video clock via a sibling event's ts
                    # scale. Simpler: take ts from the nearest-in-frame kept
                    # event (binning tolerance one minute is acceptable).
                    near = min(kept, key=lambda e: abs(
                        (tracks.get(e["tid"], [(frame0, 0, 0)])[0][0])
                        - frame0)) if kept else None
                    ts = near["ts"] if near else None
                    mvname = P0._cell_name(legcard, *cell)
                    kept.append({"tid": -ci, "o": cell[0], "d": cell[1],
                                 "mv": ("through" if mvname
                                        and mvname[1] == "thru" else "left"),
                                 "ts": ts})
                    n_rec += 1
                    rec_cells[f"{cell[0]}>{cell[1]}"] += 1

        for e in kept:
            _score_ev(arm, e)
        result[w] = {"rejected": n_rej,
                     "rejected_cells": dict(rej_cells.most_common(8)),
                     "recovered": n_rec,
                     "recovered_cells": dict(rec_cells.most_common(8)),
                     "l_cut_covered_fragments": n_lcut,
                     "c_rerouted": n_creroute, "c_dropped": n_cdrop}
        print(f"[{arm.upper()}] {w}: rejected={n_rej} "
              f"{dict(rej_cells.most_common(5))} recovered={n_rec} "
              f"{dict(rec_cells.most_common(5))} lcut={n_lcut} "
              f"c_reroute={n_creroute} c_drop={n_cdrop}", flush=True)

    mins = P0.window_minutes(windows)
    for tag in ("base", arm):
        res = per_interval(ours[tag], mio, minutes=mins, by_approach=True)
        result[f"score_{tag}"] = {
            "total": res["avg_abs_err_pct"],
            "per_approach": {d: r["avg_abs_err_pct"]
                             for d, r in res["per_approach"].items()
                             if r["n_bins"]}}
        print(f"[{arm.upper()}] {tag.upper()} pooled {result[f'score_{tag}']}",
              flush=True)

    magg = T._agg(mio, [m for m in mins if m in mio])
    rows_out = []
    inv = {}
    abs_err = {"base": 0, arm: 0}
    for cell in sorted(set(cells["base"]) | set(cells[arm])):
        name = P0._cell_name(legcard, *cell)
        ref = magg.get(name, 0) if name else 0
        row = {"cell": f"{cell[0]}>{cell[1]}", "base": cells["base"].get(cell, 0),
               arm: cells[arm].get(cell, 0), "mio": ref}
        rows_out.append(row)
        abs_err["base"] += abs(row["base"] - ref)
        abs_err[arm] += abs(row[arm] - ref)
        if cell in PROTECTED and ref:
            r = row[arm] / ref
            inv[row["cell"]] = {"ratio": round(r, 3),
                                "in_band": TRUTH_BAND[0] <= r <= TRUTH_BAND[1]}
    result["cells"] = rows_out
    result["invariant_vs_truth"] = inv
    result["per_cell_abs"] = abs_err
    print(f"[{arm.upper()}] invariant: {json.dumps(inv)} "
          f"per_cell_abs={abs_err}", flush=True)
    for row in rows_out:
        if row["mio"] >= 30 or abs(row["base"] - row[arm]) >= 10:
            print(f"[{arm.upper()}] {row['cell']:>7} base {row['base']:>5} "
                  f"{arm} {row[arm]:>5} mio {row['mio']:>5}", flush=True)

    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(result, indent=1))
    print(f"wrote {outp}", flush=True)
    print(f"{arm.upper()}-ARM DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
