"""Pipeline-V2 — DEMOTION COUNTERFACTUAL (verdict doc day-6 spec).

If entangled-region DIRECT origin claims (cam2: origin W) were demoted to
branch1-style allocation — corpus-support proportions over origins INTO
the event's (evidence-strong) destination — what do the cell totals
become? Reports control vs counterfactual vs Miovision for every touched
cell, under two brackets:
  EXPECTED — fractional allocation per support proportions (realistic
             estimate of with-shape branch1 behavior);
  ARGMAX   — every demoted event to the max-support origin (the
             no-shape degenerate bound).
Uses the window's own scratch corpus bank; partial_evidence semantics
((support+1) smoothing) verbatim.

Usage:
  py -X utf8 scripts/v2_demotion_counterfactual.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

DB = "data/projects/97a7849a/_replay_scratch/v2_week1/twopass_cam2_study_0700.db"
BANK = "data/projects/97a7849a/_replay_scratch/v2_week1/twopass_bank_cam2_study_0700.json"
SCORE = "runs/v2_week1/score_twopass_cam2_study_0700.json"
DEMOTE_CARD = "W"
CAM = 2


def main() -> int:
    bank = json.loads(open(BANK).read())
    paths = bank["paths"] if isinstance(bank, dict) and "paths" in bank else bank
    by_dest: dict[int, list[dict]] = defaultdict(list)
    for p in paths:
        by_dest[int(p["destination_leg_id"])].append(p)

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    card = {r["leg_id"]: r["cardinal_direction"] for r in conn.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (CAM,))}

    # control totals per (origin card, movement)
    control = defaultdict(float)
    for r in conn.execute(
            "SELECT e.origin_leg_id o, e.movement m, COUNT(*) n, "
            "SUM(CASE WHEN COALESCE(e.posterior_source,'(direct)')='(direct)' "
            "THEN 1 ELSE 0 END) nd "
            "FROM vehicle_events e WHERE e.camera_id=? AND "
            "COALESCE(e.rejected,0)=0 GROUP BY 1,2", (CAM,)):
        control[(card[r["o"]], r["m"])] += r["n"]

    # demotion candidates: W-origin DIRECT events, per destination
    demote = conn.execute(
        "SELECT e.destination_leg_id d, e.movement m, COUNT(*) n "
        "FROM vehicle_events e JOIN legs l ON l.leg_id=e.origin_leg_id "
        "WHERE e.camera_id=? AND COALESCE(e.rejected,0)=0 "
        "AND l.cardinal_direction=? AND "
        "COALESCE(e.posterior_source,'(direct)')='(direct)' "
        "GROUP BY 1,2", (CAM, DEMOTE_CARD)).fetchall()

    expected = dict(control)
    argmax = dict(control)
    moved = 0
    for r in demote:
        dst, n = int(r["d"]), float(r["n"])
        # remove from the original W cell
        expected[(DEMOTE_CARD, r["m"])] -= n
        argmax[(DEMOTE_CARD, r["m"])] -= n
        moved += n
        cands = by_dest.get(dst, [])
        weights = {}
        for p in cands:
            o = int(p["origin_leg_id"])
            weights[o] = weights.get(o, 0.0) + float(
                p.get("supporting_count") or 0) + 1.0
        z = sum(weights.values()) or 1.0
        movement_of = {int(p["origin_leg_id"]): p.get("movement_label")
                       for p in sorted(cands, key=lambda q: float(
                           q.get("supporting_count") or 0))}
        for o, w in weights.items():
            cell = (card[o], movement_of.get(o) or r["m"])
            expected[cell] = expected.get(cell, 0.0) + n * w / z
        best_o = max(weights, key=weights.get)
        bcell = (card[best_o], movement_of.get(best_o) or r["m"])
        argmax[bcell] = argmax.get(bcell, 0.0) + n

    mio = {}
    sc = json.loads(open(SCORE).read())
    for k, (m, _v2, _pr) in sc["totals"].items():
        d, mv = k.split("_", 1)
        dir_to_card = {"EB": "W", "WB": "E", "NB": "S", "SB": "N"}
        mio[(dir_to_card[d], {"thru": "through", "uturn": "u_turn"}.get(mv, mv))] = m

    print(f"demoted (W-origin direct): {moved:.0f} events\n")
    print(f"{'cell':>16} {'Mio':>6} {'control':>8} {'EXPECTED':>9} {'ARGMAX':>7}")
    cells = sorted(set(control) | set(expected) | set(argmax))
    for c in cells:
        m = mio.get(c, "")
        ctrl, ex, am = control.get(c, 0), expected.get(c, 0), argmax.get(c, 0)
        if abs(ex - ctrl) < 0.5 and abs(am - ctrl) < 0.5 and not m:
            continue
        print(f"{c[0]+' '+c[1]:>16} {str(m):>6} {ctrl:>8.0f} {ex:>9.0f} {am:>7.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
