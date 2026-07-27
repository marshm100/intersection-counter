"""Phase 1 — cam5 promotion A/B, bank-content only (plan_cam5_eb_bankhole_2026-07-27).

BASE = the applied 9-path bank (phase-0 plain replays, reused as-is).
P    = applied 9 paths + the ONE guard-surviving corpus candidate: the
       fitted 38->36 EB-thru path (support 58) from
       two_pass/twopass_bank_cam5_study_0700.json. The other two hole
       candidates (36->39 sc1238, 39->36 sc814) FAIL the geometric
       promotion guard — their polylines are near-subsegments (22 px /
       15 px mean-nearest) of the applied SB-thru / NB-thru corridors,
       i.e. misfits fitted from truncated main-stream fragments.

Injection via replay_camera(bank=...) — out_db only, project.db untouched.
Same replay-only scoring chain as phase 0 (REPLAYED-MINUTES basis).

Pre-declared gates (plan doc):
  (a) EB approach MAE improves aggregate and on >=2 of 3 windows;
  (b) 38->36 event count lands within ~1.5x Mio cell volume per window
      (Mio: 4 / 12 / 29) — the phantom check;
  (c) no untouched cell moves more than +/-2 per window;
  (d) per-cell abs error total improves.

Evidence -> runs/cam5_wall/promo_ab.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time as _clock
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.pass2_replay import replay_camera
import cam5_wall_phase0 as P0
import triangulate_manual as T
from interval_metric import per_interval

PROJECT = P0.PROJECT
CAM = P0.CAM
SCRATCH = P0.SCRATCH
WINDOWS = P0.WINDOWS
OUT = Path("runs/cam5_wall/promo_ab.json")


def _norm_paths(paths):
    out = []
    for p in paths:
        q = dict(p)
        if isinstance(q.get("polyline"), str):
            q["polyline"] = json.loads(q["polyline"])
        out.append(q)
    return out


def score(dbs):
    """Pooled + per-window scores and per-cell tables for a set of out_dbs."""
    mio = T.load_miovision(CAM)
    ours_all = defaultdict(lambda: defaultdict(int))
    cells_by_w = {}
    per_window = {}
    for w in WINDOWS:
        pm, cm = P0.load_ours_db(dbs[w])
        for m, cell in pm.items():
            for k, v in cell.items():
                ours_all[m][k] += v
        cells_by_w[w] = P0._agg_cells(cm, P0.window_minutes([w]))
        res_w = per_interval(pm, mio, minutes=P0.window_minutes([w]),
                             by_approach=True)
        per_window[w] = {"total": res_w["avg_abs_err_pct"],
                         "per_approach": {d: r["avg_abs_err_pct"]
                                          for d, r in res_w["per_approach"].items()
                                          if r["n_bins"]}}
    res = per_interval(ours_all, mio, minutes=P0.window_minutes(),
                       by_approach=True)
    pooled = {"total": res["avg_abs_err_pct"],
              "per_approach": {d: r["avg_abs_err_pct"]
                               for d, r in res["per_approach"].items()
                               if r["n_bins"]}}
    return pooled, per_window, cells_by_w


def main() -> int:
    applied = _norm_paths(json.loads(
        Path("evaluations/shipped_bank_cam5.json").read_text())["paths"])
    corpus = json.loads(Path(
        f"data/projects/{PROJECT}/two_pass/twopass_bank_cam5_study_0700.json"
    ).read_text())
    cand = [p for p in _norm_paths(corpus["paths"])
            if (p["origin_leg_id"], p["destination_leg_id"]) == (38, 36)]
    assert len(cand) == 1, f"expected exactly one 38->36 corpus path, got {len(cand)}"
    p_bank = {"paths": applied + cand, "window_seconds": None}
    print(f"[P] bank = 9 applied + corpus 38>36 (sc {cand[0].get('supporting_count')})",
          flush=True)

    base_dbs = {w: SCRATCH / f"cam5wall_stock_{w}.db" for w in WINDOWS}
    p_dbs = {}
    for w in WINDOWS:
        out = SCRATCH / f"cam5wall_promoP_{w}.db"
        p_dbs[w] = out
        if out.exists():
            print(f"[P] {w}: reuse existing DB", flush=True)
            continue
        t0 = _clock.time()
        st = replay_camera(PROJECT, CAM, variant=w, out_db=out, bank=p_bank)
        print(f"[P] {w}: events={st['events']} ({_clock.time() - t0:.0f}s)",
              flush=True)

    base_pooled, base_pw, base_cells = score(base_dbs)
    p_pooled, p_pw, p_cells = score(p_dbs)
    print(f"[AB] BASE pooled {base_pooled}", flush=True)
    print(f"[AB] P    pooled {p_pooled}", flush=True)
    for w in WINDOWS:
        print(f"[AB] {w}: BASE {base_pw[w]} | P {p_pw[w]}", flush=True)

    # per-cell deltas + gates
    mio = T.load_miovision(CAM)
    legcard = P0._legs(sqlite3.connect(f"data/projects/{PROJECT}/project.db"))
    mio_ebthru = {w: T._agg(mio, P0.window_minutes([w])).get(("EB", "thru"), 0)
                  for w in WINDOWS}
    deltas = {}
    phantom_ok = True
    untouched_ok = True
    for w in WINDOWS:
        d = {}
        cells = set(base_cells[w]) | set(p_cells[w])
        for cell in sorted(cells):
            a = base_cells[w].get(cell, 0)
            b = p_cells[w].get(cell, 0)
            if a != b:
                d[f"{cell[0]}>{cell[1]}"] = [a, b]
            if cell not in [(38, 36), (38, 37), (38, 39)] and abs(b - a) > 2:
                untouched_ok = False
        eb36 = p_cells[w].get((38, 36), 0)
        if eb36 > 1.5 * max(1, mio_ebthru[w]):
            phantom_ok = False
        d["_38>36_vs_mio"] = [eb36, mio_ebthru[w]]
        deltas[w] = d
        print(f"[AB] {w} changed cells: {json.dumps(d)}", flush=True)

    # per-cell abs error vs Mio, both arms
    def abs_err(cells_by_w):
        tot = 0
        for w in WINDOWS:
            magg = T._agg(mio, P0.window_minutes([w]))
            for cell, n in cells_by_w[w].items():
                name = P0._cell_name(legcard, *cell)
                tot += abs(n - (magg.get(name, 0) if name else 0))
        return tot

    base_abs = abs_err(base_cells)
    p_abs = abs_err(p_cells)

    eb_improves = sum(
        1 for w in WINDOWS
        if (p_pw[w]["per_approach"].get("EB") or 99)
        < (base_pw[w]["per_approach"].get("EB") or 99))
    gates = {
        "a_eb_improves": {"aggregate": p_pooled["per_approach"].get("EB")
                          < base_pooled["per_approach"].get("EB"),
                          "windows": eb_improves, "need": 2},
        "b_phantom": phantom_ok,
        "c_untouched": untouched_ok,
        "d_abs_err": {"base": base_abs, "p": p_abs, "improves": p_abs < base_abs},
    }
    verdict = (gates["a_eb_improves"]["aggregate"] and eb_improves >= 2
               and phantom_ok and untouched_ok and p_abs < base_abs)
    print(f"[AB] gates: {json.dumps(gates)}", flush=True)
    print(f"[AB] VERDICT: {'PASS' if verdict else 'FAIL'}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"base": {"pooled": base_pooled, "per_window": base_pw},
         "p": {"pooled": p_pooled, "per_window": p_pw},
         "deltas": deltas, "gates": gates,
         "verdict": "PASS" if verdict else "FAIL"}, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("PROMO AB DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
