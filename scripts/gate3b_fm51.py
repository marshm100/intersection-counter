"""§3-B phase 0 — the FM51 retrospective (plan_3b_validation_2026-07-28).

THE founding case for spot-window stratification: on the stock-era FM51
run (which production 0acb12c0 still holds — 3,155 events, AM −3%-ish,
PM 16:30–18:00 −12..−20%), a single random spot window could land in the
AM and certify a run whose PM was bad. This measures, end-to-end with
the production gate code:

  OLD flow — `propose_window` (single uniform-random window), 20 seeds:
      what fraction of draws certify? (the historical false-pass rate)
  NEW flow — `propose_windows` (stratified; trims 07–09/16–18 declared)
      + extend-to-certify + per-approach binding, 5 seeds: the PM
      segment gets its own window every time — does any seed certify?

Approach→bound mapping is empirical (the audit's issue #3: the FM51
calibration's cardinals are mislabeled W/E/S/SE on a 3-leg T): each Mio
approach maps to the system bound letter with the closest full-run
total, anchored by the audit's known pairs (NB 1668↔S-leg, SB 1741↔?,
WB 60↔?). The mapping is printed with its totals for the record.

Simulated operator = perfect (GT per-minute over the window).
Evidence -> runs/3b_validation/fm51_retrospective.json
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.spot_check import (
    compare_spot_count, propose_window, propose_windows)

PROJECT = "0acb12c0"
CAM = 2
XML = Path("docs/historic data/26097 TIA for Wise County, TX/Cam 1 FM51-CORD4699/"
           "405051_0029_20260430_000003_FM51-CORD4699_1398466_04-30-2026.xml")
REC_START = datetime.fromisoformat("2026-04-30T00:00:03")
MINUTES = 30.0
OLD_SEEDS = list(range(1, 21))
NEW_SEEDS = [97, 198, 299, 400, 501]
OUT = Path("runs/3b_validation/fm51_retrospective.json")
_MV = {"T": "through", "L": "left", "R": "right", "U": "u_turn"}


def load_mio_perminute():
    txt = re.sub(r"<\?xml[^>]*\?>", "", XML.read_text(encoding="utf-8-sig"),
                 count=1).lstrip()
    root = ET.fromstring(txt)
    s = lambda t: t.split("}")[-1]
    appr = [a.findtext("Name") for a in root.find("Approaches").findall("Approach")]
    moves = [(m.findtext("Name"), int(m.findtext("InApproachIndex")))
             for m in root.iter() if s(m.tag) == "Movement"]
    per_min: dict = defaultdict(lambda: defaultdict(int))
    for g in (x for x in root.iter() if s(x.tag) == "Group"):
        for b in (x for x in g.iter() if s(x.tag) == "Bin"):
            t = datetime.fromisoformat(b.findtext("Time"))
            vols = [int(v.text) for v in b.find("volumes")]
            for i, v in enumerate(vols):
                if v:
                    mv, ai = _MV.get(moves[i][0], "through"), moves[i][1]
                    per_min[t][(ai, mv)] += v
    return dict(per_min), appr


def main() -> int:
    mio, appr = load_mio_perminute()

    # empirical approach -> system-bound mapping by full-run totals
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    card = {lid: cd for lid, cd in conn.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (CAM,))}
    from backend.services.cardinals import bound_approach
    sys_bound = defaultdict(int)
    for (ol,) in conn.execute(
            "SELECT origin_leg_id FROM vehicle_events WHERE camera_id=? "
            "AND COALESCE(rejected,0)=0", (CAM,)):
        sys_bound[bound_approach(card.get(ol, ""))] += 1
    conn.close()
    mio_appr_tot = defaultdict(int)
    for cells in mio.values():
        for (ai, _mv), n in cells.items():
            mio_appr_tot[ai] += n
    used = set()
    ai_to_bound = {}
    for ai, tot in sorted(mio_appr_tot.items(), key=lambda kv: -kv[1]):
        best = min((b for b in sys_bound if b not in used),
                   key=lambda b: abs(sys_bound[b] - tot), default=None)
        if best is not None:
            ai_to_bound[ai] = best
            used.add(best)
    print(f"[F] system bound totals: {dict(sys_bound)}", flush=True)
    print(f"[F] mio approach totals: "
          f"{ {appr[ai]: t for ai, t in mio_appr_tot.items()} }", flush=True)
    print(f"[F] mapping: { {appr[ai]: b for ai, b in ai_to_bound.items()} }",
          flush=True)

    rec_off = REC_START.hour * 3600 + REC_START.minute * 60 + REC_START.second

    def manual_for(start, duration):
        t0 = rec_off + start
        out = defaultdict(int)
        base = datetime(2026, 4, 30)
        m = base + timedelta(seconds=t0 - (t0 % 60))
        end = base + timedelta(seconds=t0 + duration)
        while m < end:
            for (ai, mv), n in mio.get(m, {}).items():
                b = ai_to_bound.get(ai)
                if b:
                    out[f"{b} {mv}"] += n
            m += timedelta(minutes=1)
        return dict(out)

    def run_window(start, dur, extend=True, seg_end=None):
        rep = compare_spot_count(PROJECT, CAM, start, dur, manual_for(start, dur))
        while (extend and rep["verdict"] == "review" and rep["total"]["manual"]
               and rep["total"]["rel_err"] is not None
               and abs(rep["total"]["rel_err"]) <= 0.05
               and "extend the count" in rep["note"] and dur < 3600.0
               and (seg_end is None or start + dur < seg_end - 60.0)):
            dur = min(dur + 900.0, 3600.0,
                      (seg_end - start) if seg_end else 3600.0)
            rep = compare_spot_count(PROJECT, CAM, start, dur,
                                     manual_for(start, dur))
        return rep, dur

    old_rows = []
    for seed in OLD_SEEDS:
        w = propose_window(PROJECT, CAM, minutes=MINUTES, seed=seed)
        rep, dur = run_window(w["start_seconds"], w["duration_seconds"])
        hh = int((rec_off + w["start_seconds"]) // 3600)
        old_rows.append({"seed": seed, "start_hour": hh, "dur": dur,
                         "verdict": rep["verdict"],
                         "rel_err": rep["total"]["rel_err"]})
    old_pass = sum(1 for r in old_rows if r["verdict"] == "pass")
    print(f"[F] OLD single-window: {old_pass}/{len(OLD_SEEDS)} certify "
          f"({[r['verdict'] for r in old_rows]})", flush=True)

    new_rows = []
    for seed in NEW_SEEDS:
        pw = propose_windows(PROJECT, CAM, minutes=MINUTES, seed=seed)
        wins = []
        for w in pw.get("windows", []):
            rep, dur = run_window(w["start_seconds"], w["duration_seconds"],
                                  seg_end=w["segment"][1])
            hh = int((rec_off + w["start_seconds"]) // 3600)
            wins.append({"segment": w["segment_index"], "start_hour": hh,
                         "dur": dur, "verdict": rep["verdict"],
                         "rel_err": rep["total"]["rel_err"],
                         "binding": [a for a in rep["approaches"]
                                     if a["outside_target"]]})
        vs = [w["verdict"] for w in wins]
        cam_v = ("pass" if vs and all(v == "pass" for v in vs)
                 else "fail" if "fail" in vs else "review")
        new_rows.append({"seed": seed, "camera_verdict": cam_v, "windows": wins})
        print(f"[F] NEW stratified seed={seed}: {cam_v} "
              f"({[(w['start_hour'], w['verdict']) for w in wins]})", flush=True)

    new_pass = sum(1 for r in new_rows if r["camera_verdict"] == "pass")
    result = {"mapping": {appr[ai]: b for ai, b in ai_to_bound.items()},
              "old_single_window": {"n": len(OLD_SEEDS), "pass": old_pass,
                                    "rows": old_rows},
              "new_stratified": {"n": len(NEW_SEEDS), "pass": new_pass,
                                 "rows": new_rows}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"[F] RETRO: old false-pass {old_pass}/{len(OLD_SEEDS)}, "
          f"stratified pass {new_pass}/{len(NEW_SEEDS)}", flush=True)
    print(f"wrote {OUT}", flush=True)
    print("FM51 RETRO DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
