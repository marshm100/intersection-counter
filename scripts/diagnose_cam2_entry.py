"""Confirm WHY the entry-tiebreak REGRESSED cam2 (2026-07-02, post-validation).
LOW-RAM (pure sqlite + json, streaming cursor) so it runs under memory pressure.

The entry-tiebreak replay made cam2 WORSE (EB 33.2->41.0, SB 12.3->15.8, 747
firings) — the opposite of intended. Hypothesis (the handoff's standing warning):
the SB approach is FOV-clipped, so real SB tracks are BORN near the merge, whose
location is closer to the EB path's ENTRY than to the SB path's ENTRY — so the
"pick the entry-closest path" heuristic points the WRONG way. If even tracks the
baseline mdh scorer already attributed to the SB origin (27) have births closer to
the EB entry, the entry is a non-discriminator here and the lever is dead.

Usage: py scripts/diagnose_cam2_entry.py
"""
from __future__ import annotations
import sqlite3, json, math
from collections import defaultdict

PROJECT = "97a7849a"; CAM = 2
db = f"data/projects/{PROJECT}/project.db"


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def main():
    c = sqlite3.connect(db)
    paths = {(o, dd): json.loads(poly) for o, dd, poly in c.execute(
        "SELECT origin_leg_id,destination_leg_id,polyline FROM intersection_paths "
        "WHERE camera_id=?", (CAM,))}
    pairs = [("leg-29 exit: SB-thru(27) vs EB-right(28)", (27, 29), (28, 29)),
             ("leg-26 exit: SB-left(27) vs EB-thru(28)", (27, 26), (28, 26))]
    for title, sb_key, eb_key in pairs:
        sb, eb = paths.get(sb_key), paths.get(eb_key)
        if not sb or not eb:
            print(f"\n=== {title} ===\n  path(s) missing: {sb_key if not sb else ''} "
                  f"{eb_key if not eb else ''}")
            continue
        sb_entry, eb_entry = tuple(sb[0]), tuple(eb[0])
        dest = sb_key[1]
        print(f"\n=== {title} ===")
        print(f"  SB entry {[round(x) for x in sb_entry]}  EB entry "
              f"{[round(x) for x in eb_entry]}  (entry sep {_d(sb_entry, eb_entry):.0f}px)")
        # cluster population: events the BASELINE scorer attributed to either
        # origin at this shared exit. births closer to EB entry => tiebreak flips
        # toward EB (the observed regression).
        stats = defaultdict(lambda: [0, 0, 0.0, 0.0])  # origin -> [n, n_closer_eb, sum_dsb, sum_deb]
        for olid, tj in c.execute(
                "SELECT origin_leg_id, trajectory_data FROM vehicle_events "
                "WHERE camera_id=? AND destination_leg_id=? AND origin_leg_id IN (?,?) "
                "AND COALESCE(rejected,0)=0", (CAM, dest, sb_key[0], eb_key[0])):
            if not tj:
                continue
            traj = json.loads(tj)
            if len(traj) < 2:
                continue
            t0 = tuple(traj[0])
            dsb, deb = _d(t0, sb_entry), _d(t0, eb_entry)
            s = stats[olid]
            s[0] += 1; s[1] += (1 if deb < dsb else 0); s[2] += dsb; s[3] += deb
        for olid, name in ((sb_key[0], "SB"), (eb_key[0], "EB")):
            s = stats[olid]
            if s[0]:
                print(f"  origin {olid} ({name}-attributed): n={s[0]:>4}  "
                      f"births closer to EB entry: {s[1]:>4} ({100*s[1]/s[0]:>3.0f}%)  "
                      f"mean d_sb={s[2]/s[0]:.0f}px  d_eb={s[3]/s[0]:.0f}px")
    c.close()


if __name__ == "__main__":
    main()
