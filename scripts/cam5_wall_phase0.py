"""Phase 0 — cam5 EB/NB wall decomposition (plan_cam5_eb_bankhole_2026-07-27).

Stage A — plain stock replays (all research flags at import defaults, i.e.
    veto/gate/posterior OFF, no evidence_mode) of cam5's three study windows
    into scratch out_dbs. Resumable via db-exists.
Stage B — OFF-parity vs the rebaseline stock row (total 7.2, EB 16.1 /
    NB 17.3 / SB 5.1 — replayed-minutes basis, corridor_ft2_rebaseline.json)
    + the first per-window splits + per-cell ours-vs-Mio tables + hole-cell
    Mio volumes (the July-9 audit sized them on one 30-min sample only).
Stage D — corpus-bank claimed supports vs Mio same-window volume (the
    phantom-magnet risk read on the discovered-but-unpromoted paths).
Stage E — production hole-cell event counts (the S4 impact definition:
    fallback-tier events are a lower bound of real traffic in a hole).

Evidence -> runs/cam5_wall/phase0.json. Scoring basis: REPLAYED-MINUTES
(per_interval over the three 120-min study windows' wall-clock minutes).
The fate ledger (stage C of the plan) is a separate follow-up script.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time as _clock
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.pass2_replay import replay_camera
import backend.services.pipeline as PL
import triangulate_manual as T
from interval_metric import per_interval

PROJECT = "97a7849a"
CAM = 5
SCRATCH = Path(r"C:\Users\onkar\AppData\Local\Temp\ic_scratch_97a7849a")
WINDOWS = ["study_0700", "study_1100", "study_1600"]
WINDOW_HOURS = {"study_0700": (7, 9), "study_1100": (11, 13),
                "study_1600": (16, 18)}
OUT = Path("runs/cam5_wall/phase0.json")
CORPUS_BANK = Path(f"data/projects/{PROJECT}/two_pass/"
                   "twopass_bank_cam5_study_0700.json")
REBASELINE = {"total": 7.2, "EB": 16.1, "NB": 17.3, "SB": 5.1}
HOLES = [(38, 36), (39, 36), (36, 39)]   # EB-thru, NB-right, WB-left

# Compass geometry: dest leg from origin cardinal + movement. A leg's
# cardinal is its POSITION; the approach direction is the opposite bound
# (cardinal W -> EB traffic heading east; right hand of east = south).
# EB right->S, WB right->N, SB (origin N, heading south) right->W,
# NB (origin S, heading north) right->E.
_OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}
_RIGHT_OF_BOUND = {"W": "S", "E": "N", "N": "W", "S": "E"}   # origin card -> dest card


def _legs(conn):
    return {lid: (card or "").strip().upper() for lid, card in conn.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (CAM,))}


def _cell_name(legcard, o, d):
    """(o,d) -> ('EB','thru') style, via cardinals."""
    oc, dc = legcard.get(o), legcard.get(d)
    if not oc or not dc:
        return None
    if dc == _OPP.get(oc):
        mv = "thru"
    elif dc == _RIGHT_OF_BOUND.get(oc):
        mv = "right"
    elif dc == oc:
        mv = "uturn"
    else:
        mv = "left"
    return (T._CARD_TO_DIR.get(oc), mv)


def window_minutes(windows=WINDOWS):
    mins = []
    for w in windows:
        lo, hi = WINDOW_HOURS[w]
        mins += [time(h, m) for h in range(lo, hi) for m in range(60)]
    return sorted(mins)


def load_ours_db(db):
    """triangulate_manual.load_ours, parameterized on the DB file; also
    returns raw (o,d) leg-pair cell counts keyed by minute."""
    c = sqlite3.connect(str(db))
    legcard = _legs(c)
    leg_dir = {lid: T._CARD_TO_DIR.get(cd) for lid, cd in legcard.items()}
    norm = {"through": "thru", "u_turn": "uturn"}
    per_min = defaultdict(lambda: defaultdict(int))
    cells_min = defaultdict(lambda: defaultdict(int))
    for olid, dlid, mv, ts in c.execute(
            "SELECT origin_leg_id, destination_leg_id, movement, timestamp_real "
            "FROM vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0",
            (CAM,)):
        d = leg_dir.get(olid)
        if ts and d:
            key = datetime.fromisoformat(ts).time().replace(second=0, microsecond=0)
            per_min[key][(d, norm.get(mv, mv))] += 1
            cells_min[key][(olid, dlid)] += 1
    c.close()
    return per_min, cells_min


def _agg_cells(cells_min, minutes):
    out = defaultdict(int)
    mset = set(minutes)
    for m, cells in cells_min.items():
        if m in mset:
            for k, v in cells.items():
                out[k] += v
    return dict(out)


def main() -> int:
    print(f"[flags] veto={PL.ORIGIN_CLAIM_VETO_ENABLED} "
          f"gate={PL.ORIGIN_EVIDENCE_GATE_ENABLED} "
          f"posterior={PL.ORIGIN_POSTERIOR_ENABLED}", flush=True)
    result: dict = {"basis": "replayed-minutes (per_interval, 15-min bins, "
                             "ref_floor 20, windows 0700/1100/1600)"}

    # ---- Stage A: plain replays -------------------------------------------
    dbs = {}
    for w in WINDOWS:
        out = SCRATCH / f"cam5wall_stock_{w}.db"
        dbs[w] = out
        if out.exists():
            print(f"[A] {w}: reuse existing DB", flush=True)
            continue
        t0 = _clock.time()
        st = replay_camera(PROJECT, CAM, variant=w, out_db=out)
        print(f"[A] {w}: events={st['events']} tracks={st.get('tracks')} "
              f"({_clock.time() - t0:.0f}s)", flush=True)

    # ---- Stage B: parity + per-cell ---------------------------------------
    mio = T.load_miovision(CAM)
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    legcard = _legs(conn)

    ours_all = defaultdict(lambda: defaultdict(int))
    cells_all = defaultdict(lambda: defaultdict(int))
    per_window = {}
    for w in WINDOWS:
        pm, cm = load_ours_db(dbs[w])
        for m, cell in pm.items():
            for k, v in cell.items():
                ours_all[m][k] += v
        for m, cell in cm.items():
            for k, v in cell.items():
                cells_all[m][k] += v
        res_w = per_interval(pm, mio, minutes=window_minutes([w]),
                             by_approach=True)
        per_window[w] = {
            "total": res_w["avg_abs_err_pct"],
            "per_approach": {d: r["avg_abs_err_pct"]
                             for d, r in res_w["per_approach"].items()
                             if r["n_bins"]},
            "n_bins": res_w["n_bins"],
        }
        print(f"[B] {w}: total {res_w['avg_abs_err_pct']} "
              f"{per_window[w]['per_approach']}", flush=True)

    res = per_interval(ours_all, mio, minutes=window_minutes(),
                       by_approach=True)
    pooled = {"total": res["avg_abs_err_pct"],
              "per_approach": {d: r["avg_abs_err_pct"]
                               for d, r in res["per_approach"].items()
                               if r["n_bins"]},
              "n_bins": res["n_bins"],
              "wb_bins_scored": res["per_approach"].get("WB", {}).get("n_bins", 0)}
    parity = {k: [REBASELINE.get(k), pooled["total"] if k == "total"
                  else pooled["per_approach"].get(k)]
              for k in ("total", "EB", "NB", "SB")}
    ok = all(a is not None and b is not None and abs(a - b) < 0.05
             for a, b in parity.values())
    print(f"[B] POOLED total {pooled['total']} {pooled['per_approach']} "
          f"| OFF-PARITY vs rebaseline: {'PASS' if ok else 'MISS'} {parity}",
          flush=True)

    # per-cell tables, pooled + per window
    def cell_tables(minutes, cm_src, pm_src):
        ours_cells = _agg_cells(cm_src, minutes)
        mio_cells = T._agg(mio, [m for m in minutes if m in mio])
        rows = []
        for (o, d), n in sorted(ours_cells.items()):
            name = _cell_name(legcard, o, d)
            ref = mio_cells.get(name, 0) if name else None
            rows.append({"cell": f"{o}>{d}", "name": name and f"{name[0]} {name[1]}",
                         "ours": n, "mio": ref})
        ours_named = {f"{k[0]} {k[1]}": v
                      for k, v in T._agg(pm_src, minutes).items()}
        for name, ref in sorted(mio_cells.items()):
            nm = f"{name[0]} {name[1]}"
            if ref and nm not in ours_named:
                rows.append({"cell": None, "name": nm, "ours": 0, "mio": ref})
        return rows

    result["per_window"] = per_window
    result["pooled"] = pooled
    result["off_parity"] = {"pass": ok, "cells": parity}
    result["cells_pooled"] = cell_tables(window_minutes(), cells_all, ours_all)
    result["cells_by_window"] = {}
    for w in WINDOWS:
        pm, cm = load_ours_db(dbs[w])
        result["cells_by_window"][w] = cell_tables(window_minutes([w]), cm, pm)

    # hole-cell Mio volumes per window (the prize sizing)
    hole_vol = {}
    for (o, d) in HOLES:
        name = _cell_name(legcard, o, d)
        per_w = {w: T._agg(mio, window_minutes([w])).get(name, 0)
                 for w in WINDOWS}
        hole_vol[f"{o}>{d}"] = {"name": name and f"{name[0]} {name[1]}",
                                **per_w, "total": sum(per_w.values())}
    result["hole_mio_volumes"] = hole_vol
    print(f"[B] hole-cell Mio volumes: {json.dumps(hole_vol)}", flush=True)

    # ---- Stage D: corpus-bank supports vs Mio -----------------------------
    if CORPUS_BANK.exists():
        bank = json.loads(CORPUS_BANK.read_text())
        paths = bank.get("paths", bank if isinstance(bank, list) else [])
        sup = [{"cell": f"{p['origin_leg_id']}>{p['destination_leg_id']}",
                "support": p.get("supporting_count"),
                "mio_0700": T._agg(mio, window_minutes(["study_0700"])).get(
                    _cell_name(legcard, p["origin_leg_id"],
                               p["destination_leg_id"]), 0)}
               for p in paths]
        result["corpus_supports_vs_mio0700"] = sup
        print(f"[D] corpus supports vs Mio(0700): {json.dumps(sup)}", flush=True)
    else:
        print(f"[D] corpus bank missing: {CORPUS_BANK}", flush=True)

    # ---- Stage E: production hole-cell events (S4 impact definition) ------
    prod = {}
    for (o, d) in HOLES:
        n_all = conn.execute(
            "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=? AND "
            "COALESCE(rejected,0)=0 AND origin_leg_id=? AND destination_leg_id=?",
            (CAM, o, d)).fetchone()[0]
        prod[f"{o}>{d}"] = n_all
    result["production_hole_events"] = prod
    print(f"[E] production hole-cell events: {prod}", flush=True)
    conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("PHASE0 DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
