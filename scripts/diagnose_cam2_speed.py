"""Does SPEED discriminate the collinear cam2 SB<->EB pairs? (2026-07-02)

Diagnostic-FIRST check BEFORE building a speed-based tiebreak (the ENTRY version
was DISPROVEN — it fired on the misleading minority). LOW-RAM (pure sqlite + json).

Compares the speed profile of CONFIDENTLY-SB tracks (origin 27 AND born nearer the
SB entry) vs CONFIDENTLY-EB (origin 28 AND born nearer the EB entry) over the two
shared-exit clusters. Using the birth-clean subsets means we compare the TRUE
populations, not the scrambled attribution. Metrics per track (px per sampled
step, a speed proxy): overall mean, tail-third mean (near the exit), smoothed min
(the turn apex), median. Separation reported as Cohen's-d-ish (|dSB-dEB|/pooled
sd): >~0.8 = usable discriminator; <~0.3 = speed is dead too -> PIVOT.

Usage: py scripts/diagnose_cam2_speed.py
"""
from __future__ import annotations
import sqlite3, json, math
from statistics import mean, median, pstdev

PROJECT = "97a7849a"; CAM = 2
db = f"data/projects/{PROJECT}/project.db"


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def track_metrics(traj):
    s = [_d(traj[i], traj[i + 1]) for i in range(len(traj) - 1)]
    if len(s) < 3:
        return None
    n = len(s)
    tail = s[max(0, n - max(3, n // 3)):]                 # last third (near exit)
    sm = [mean(s[i:i + 3]) for i in range(n - 2)]          # 3-window smoothed
    return {"mean": mean(s), "tail": mean(tail), "min": min(sm), "median": median(s)}


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
            print(f"\n=== {title} ===  (path missing)")
            continue
        sb_e, eb_e = tuple(sb[0]), tuple(eb[0])
        dest = sbk[1]
        sb_ms, eb_ms = [], []
        for olid, tj in c.execute(
                "SELECT origin_leg_id, trajectory_data FROM vehicle_events "
                "WHERE camera_id=? AND destination_leg_id=? AND origin_leg_id IN (?,?) "
                "AND COALESCE(rejected,0)=0", (CAM, dest, sbk[0], ebk[0])):
            if not tj:
                continue
            traj = [tuple(p) for p in json.loads(tj)]
            if len(traj) < 4:
                continue
            near_sb = _d(traj[0], sb_e) < _d(traj[0], eb_e)
            m = track_metrics(traj)
            if not m:
                continue
            if olid == sbk[0] and near_sb:
                sb_ms.append(m)
            elif olid == ebk[0] and not near_sb:
                eb_ms.append(m)
        print(f"\n=== {title} ===  SB-clean n={len(sb_ms)}  EB-clean n={len(eb_ms)}")
        if not sb_ms or not eb_ms:
            print("  insufficient clean tracks"); continue
        for key in ("mean", "tail", "min", "median"):
            sv = [x[key] for x in sb_ms]; ev = [x[key] for x in eb_ms]
            pooled = ((pstdev(sv) + pstdev(ev)) / 2) or 1e-9
            d = (mean(sv) - mean(ev)) / pooled
            flag = "  <== USABLE" if abs(d) >= 0.8 else ("  (weak)" if abs(d) >= 0.3 else "  DEAD")
            print(f"  {key:7}: SB {mean(sv):5.1f}+-{pstdev(sv):4.1f}   "
                  f"EB {mean(ev):5.1f}+-{pstdev(ev):4.1f}   sep(d)={d:+.2f}{flag}")
    c.close()


if __name__ == "__main__":
    main()
