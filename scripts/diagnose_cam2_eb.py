"""Diagnose cam2 EB per-approach error to root cause (2026-07-02). LOW-RAM (pure
sqlite + ElementTree, NO pandas/replay) so it runs even under memory pressure.

Reproduces the airtight finding: cam2 EB is OVER +25% while SB is UNDER -11% (a
~700-veh SB<->EB swap) — a SHARED-EXIT collinear confusion. SB-thru (27->29) and
EB-right (28->29) share the leg-29 exit; mdh's min-directed relaxation sees them as
~11px = the same shape and discards the 171px ENTRY that separates them, so SB-thru
matches EB-right and its origin is rewritten SB->EB. FIX = entry-tiebreak for
shared-exit collinear candidate pairs. See memory
project_per_approach_attribution_2026_06_30 + docs/handoff_2026-07-02_session_end.md.

Usage: py scripts/diagnose_cam2_eb.py
"""
from __future__ import annotations
import sqlite3, json, math, sys
from collections import defaultdict
sys.path.insert(0, "scripts")
import parse_miovision_xml as MIO

PROJECT = "97a7849a"; CAM = 2
_C2D = {"N": "SB", "S": "NB", "E": "WB", "W": "EB"}
NORM = {"through": "thru", "u_turn": "uturn", "left": "left", "right": "right"}
db = f"data/projects/{PROJECT}/project.db"


def miovision_totals():
    data = MIO.parse(CAM); labels = MIO.slot_labels(data["movements"], CAM)
    appr = defaultdict(int); mov = defaultdict(int)
    for _tm, vols in data["per_min"].items():
        for i, v in enumerate(vols):
            d = labels[i][0].strip().split()[0].upper()
            appr[d] += int(v); mov[(d, labels[i][1])] += int(v)
    return appr, mov


def main():
    c = sqlite3.connect(db)
    legdir = {lid: _C2D.get((cd or "").upper()) for lid, cd in
              c.execute("SELECT leg_id,cardinal_direction FROM legs WHERE camera_id=?", (CAM,))}
    # ours per-movement day totals (pure-sqlite GROUP BY, no blob materialize)
    o_appr = defaultdict(int); o_mov = defaultdict(int)
    for olid, mv, n in c.execute(
            "SELECT origin_leg_id, movement, COUNT(*) FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0 GROUP BY origin_leg_id, movement", (CAM,)):
        d = legdir.get(olid)
        if d:
            o_appr[d] += n; o_mov[(d, NORM.get(mv, mv))] += n
    m_appr, m_mov = miovision_totals()

    print("=== cam2 approach day totals (ours vs Miovision) — the SB<->EB swap ===")
    for d in ("EB", "NB", "SB", "WB"):
        o, m = o_appr[d], m_appr[d]
        print(f"  {d}: ours {o:>5}  mio {m:>5}  {o-m:>+5} ({100*(o-m)/m if m else 0:>+4.0f}%)")
    print("\n=== cam2 EB per-movement (ours vs Miovision) ===")
    for mv in ("thru", "right", "left"):
        o, m = o_mov[("EB", mv)], m_mov[("EB", mv)]
        print(f"  EB {mv:<6} ours {o:>5}  mio {m:>5}  {o-m:>+5} ({100*(o-m)/m if m else 0:>+4.0f}%)")

    # shared-exit geometry: SB-thru (27->29) vs EB-right (28->29)
    P = {(o, dd): json.loads(poly) for o, dd, poly in c.execute(
        "SELECT origin_leg_id,destination_leg_id,polyline FROM intersection_paths "
        "WHERE camera_id=? AND destination_leg_id=29", (CAM,))}
    c.close()
    sb, eb = P.get((27, 29)), P.get((28, 29))
    if sb and eb:
        dmin = lambda p, poly: min(math.hypot(p[0]-q[0], p[1]-q[1]) for q in poly)
        md = lambda A, B: sum(dmin(p, B) for p in A) / len(A)
        print("\n=== shared-exit geometry: SB-thru(27->29) vs EB-right(28->29) ===")
        print(f"  exits: SB {[round(x) for x in sb[-1]]}  EB {[round(x) for x in eb[-1]]}  (shared)")
        print(f"  directed mean dist: SB->EB {md(sb,eb):.0f}px  EB->SB {md(eb,sb):.0f}px "
              f"(mdh uses the MIN -> ~{min(md(sb,eb),md(eb,sb)):.0f}px = 'same shape')")
        print(f"  ENTRY separation (the only discriminator, discarded by min): "
              f"{math.hypot(sb[0][0]-eb[0][0], sb[0][1]-eb[0][1]):.0f}px")


if __name__ == "__main__":
    main()
