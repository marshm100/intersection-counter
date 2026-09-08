"""U-turn speed-consistency sweep (2026-09-08) — MEASUREMENT ONLY.

Operator ruling: a real u-turn holds a steady slow speed; a theft
shows a speed discontinuity where the box changes vehicles. Measured
on his three ruled cam3 tracks: REAL 1.2x, THEFT 6.4x, THEFT 2.6x.

Three cases is too few to fix a threshold on. This sweeps candidate
thresholds against Miovision's per-approach u-turn counts, which are
the aggregate truth: an approach where Miovision says ZERO is pure
signal (every survivor is false); an approach where it says N > 0
measures the collateral.

Two statistics:
  A  median speed, first half vs second half of the journey
  B  max/min of the median speed over THIRDS (catches slow-fast-slow)

Read-only: opens the working DBs and dumps read-only, writes nothing.

Usage:  py -X utf8 scripts/uturn_speed_sweep.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import all_crossings  # noqa: E402
from backend.services.entry_gates import build_gates  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
ARM = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
WINDOWS = [(1, "study_0700"), (1, "study_1600"),
           (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
           (3, "study_0600")]
# Miovision u-turn counts, keyed (cam, variant, bound approach)
MIO_UT = {
    (1, "study_0700"): {"NB": 2, "SB": 0, "EB": 4, "WB": 0},
    (1, "study_1600"): {"NB": 1, "SB": 0, "EB": 13, "WB": 0},
    (2, "study_0700"): {"NB": 0, "SB": 1, "EB": 2, "WB": 0},
    (2, "study_1100"): {"NB": 5, "SB": 2, "EB": 0, "WB": 0},
    (2, "study_1600"): {"NB": 0, "SB": 12, "EB": 1, "WB": 0},
    (3, "study_0600"): {"NB": 8, "SB": 0, "EB": 0, "WB": 0},
}
BOUND = {"S": "NB", "N": "SB", "E": "WB", "W": "EB"}
RULED = {123908: "REAL u-turn", 308574: "THEFT fast-through",
         296206: "THEFT box-creep"}
TS = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0)


def med_speed(seg):
    if len(seg) < 3:
        return None
    d = np.hypot(np.diff(seg[:, 2]), np.diff(seg[:, 3]))
    df = np.maximum(np.diff(seg[:, 1]), 1.0)
    return float(np.median(d / df))


def stats_for(seg):
    """(A: halves ratio, B: thirds max/min) or (None, None)."""
    h = len(seg) // 2
    a1, a2 = med_speed(seg[:h]), med_speed(seg[h:])
    A = (max(a1, a2) / max(min(a1, a2), 0.01)
         if a1 is not None and a2 is not None else None)
    t = len(seg) // 3
    parts = [med_speed(seg[:t]), med_speed(seg[t:2 * t]),
             med_speed(seg[2 * t:])]
    parts = [p for p in parts if p is not None]
    B = (max(parts) / max(min(parts), 0.01) if len(parts) == 3 else None)
    return A, B


def main() -> int:
    rows_by_win = {}
    for cam, var in WINDOWS:
        db = ARM / f"ff_cam{cam}_{var}.db"
        if not db.exists():
            print(f"cam{cam} {var}: no working DB, skipped")
            continue
        con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                              uri=True)
        chash, fps = con.execute(
            "SELECT content_hash, fps FROM videos WHERE camera_id=?",
            (cam,)).fetchone()
        legs = dict(con.execute(
            "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
            (cam,)))
        con.close()
        fps = float(fps)
        geom = leg_geometry_for_camera(PROJ, cam)
        gates = build_gates(
            {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
            list_paths_for_camera(PROJ, cam),
            {lg: g.get("heading") for lg, g in geom.items()},
            leg_gates={lg: g["gate"] for lg, g in geom.items()
                       if g.get("gate")})
        td = tracks_dir(parquet_path(PROJ, cam, chash, var))
        n = int((Path(td) / "count.txt").read_text())
        dump = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])
        order = np.lexsort((dump[:, 1], dump[:, 0]))
        d = dump[order]
        uniq, starts = np.unique(d[:, 0], return_index=True)
        ends = np.r_[starts[1:], len(d)]
        index = {int(u): (s, e) for u, s, e in zip(uniq, starts, ends)}

        s = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        evs = list(s.execute(
            "SELECT vehicle_track_id, origin_leg_id FROM vehicle_events "
            "WHERE camera_id=? AND rejected=0 AND movement='u_turn'",
            (cam,)))
        s.close()

        recs = []
        for tid, oleg in evs:
            tid = int(tid)
            if tid not in index:
                continue
            s0, e0 = index[tid]
            trk = d[s0:e0]
            if len(trk) < 12:
                continue
            pts = [(float(r[1]), float(r[2]),
                    float(r[3]) + float(r[5]) / 2) for r in trk]
            xs = all_crossings(pts, gates, fps)
            ent = [x for x in xs if x[2]]
            ex = [x for x in xs if not x[2]]
            if not ent:
                continue
            after = [x for x in ex if x[0] > ent[0][0]]
            if not after:
                continue
            seg = trk[(trk[:, 1] >= ent[0][0]) & (trk[:, 1] <= after[0][0])]
            A, B = stats_for(seg)
            if A is None:
                continue
            recs.append((tid, BOUND.get(legs.get(oleg), "?"), A, B))
        rows_by_win[(cam, var)] = recs
        print(f"cam{cam} {var}: {len(recs)} measurable u-turns "
              f"(of {len(evs)} events)")

    print("\n--- operator-ruled anchors ---")
    for recs in rows_by_win.values():
        for tid, ap, A, B in recs:
            if tid in RULED:
                print(f"   {tid}  {RULED[tid]:<20} A={A:>5.1f}  "
                      f"B={B if B else 0:>5.1f}")

    for stat, idx in (("A halves", 2), ("B thirds", 3)):
        print(f"\n=== statistic {stat}: survivors at each threshold ===")
        print(f"{'window':16}{'appr':>5}{'Mio':>5}{'now':>5}" +
              "".join(f"{f'T={t}':>8}" for t in TS))
        tot = defaultdict(lambda: [0] * (len(TS) + 2))
        for (cam, var), recs in rows_by_win.items():
            per = defaultdict(list)
            for tid, ap, A, B in recs:
                per[ap].append(A if idx == 2 else (B or A))
            for ap in sorted(per):
                mio = MIO_UT.get((cam, var), {}).get(ap, "?")
                vals = per[ap]
                line = f"cam{cam} {var:11}{ap:>5}{str(mio):>5}{len(vals):>5}"
                for t in TS:
                    line += f"{sum(1 for v in vals if v < t):>8}"
                print(line)
                if isinstance(mio, int):
                    key = "ZERO" if mio == 0 else "POSITIVE"
                    tot[key][0] += mio
                    tot[key][1] += len(vals)
                    for i, t in enumerate(TS):
                        tot[key][2 + i] += sum(1 for v in vals if v < t)
        print(f"\n{'group':16}{'':>5}{'Mio':>5}{'now':>5}" +
              "".join(f"{f'T={t}':>8}" for t in TS))
        for key in ("ZERO", "POSITIVE"):
            r = tot[key]
            print(f"{'Mio-' + key:16}{'':>5}{r[0]:>5}{r[1]:>5}" +
                  "".join(f"{v:>8}" for v in r[2:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
