"""Does SPEED fix the exact tracks the ENTRY tiebreak got WRONG? (2026-07-02)

The entry tiebreak regressed because it fired on the ~727 genuinely-SB (origin 27)
tracks BORN NEAR THE EB ENTRY (the misleading minority) and flipped them SB->EB.
If those same tracks carry an SB-LIKE speed (~5 px/step), a speed tiebreak keeps
them SB -> it fixes precisely the population entry corrupted. This splits each
origin into born-near-SB vs born-near-EB and reports median speed per subgroup.
LOW-RAM (pure sqlite + json).

Usage: py scripts/diagnose_cam2_speed2.py
"""
from __future__ import annotations
import sqlite3, json, math
from statistics import median

PROJECT = "97a7849a"; CAM = 2
db = f"data/projects/{PROJECT}/project.db"


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def med_speed(traj):
    s = [_d(traj[i], traj[i + 1]) for i in range(len(traj) - 1)]
    return median(s) if len(s) >= 3 else None


def main():
    c = sqlite3.connect(db)
    paths = {(o, dd): json.loads(poly) for o, dd, poly in c.execute(
        "SELECT origin_leg_id,destination_leg_id,polyline FROM intersection_paths "
        "WHERE camera_id=?", (CAM,))}
    pairs = [("leg-29  SB-thru(27) vs EB-right(28)", (27, 29), (28, 29)),
             ("leg-26  SB-left(27) vs EB-thru(28)", (27, 26), (28, 26))]
    for title, sbk, ebk in pairs:
        sb, eb = paths.get(sbk), paths.get(ebk)
        if not sb or not eb:
            print(f"\n=== {title} ===  (path missing)"); continue
        sb_e, eb_e = tuple(sb[0]), tuple(eb[0])
        dest = sbk[1]
        # subgroup -> list of median speeds
        sub = {("27", "nearSB"): [], ("27", "nearEB"): [],
               ("28", "nearSB"): [], ("28", "nearEB"): []}
        for olid, tj in c.execute(
                "SELECT origin_leg_id, trajectory_data FROM vehicle_events "
                "WHERE camera_id=? AND destination_leg_id=? AND origin_leg_id IN (?,?) "
                "AND COALESCE(rejected,0)=0", (CAM, dest, sbk[0], ebk[0])):
            if not tj:
                continue
            traj = [tuple(p) for p in json.loads(tj)]
            if len(traj) < 4:
                continue
            ms = med_speed(traj)
            if ms is None:
                continue
            born = "nearSB" if _d(traj[0], sb_e) < _d(traj[0], eb_e) else "nearEB"
            sub[(str(olid), born)].append(ms)
        print(f"\n=== {title} ===  (SB entry speed~5, EB entry speed~1-2)")
        for (o, born), vals in sub.items():
            if vals:
                tag = "  <== the tracks ENTRY got WRONG" if (o == "27" and born == "nearEB") else ""
                print(f"  origin {o} born {born}: n={len(vals):>4}  median speed={median(vals):4.1f}{tag}")
    c.close()


if __name__ == "__main__":
    main()
