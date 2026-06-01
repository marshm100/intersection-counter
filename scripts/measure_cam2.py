"""Quick cam2 (N Belt Line Rd & E Town East Blvd) per-minute movement accuracy vs
its Miovision XML. cam2-specific shim while the full measurement stack is still
cam1-hardcoded (Phase D generalization pending). Maps our cam2 legs to cam2's
Miovision approach indices and compares.

cam2 Miovision approaches: idx0 WB, idx1 SB, idx2 EB, idx3 NB (E Town East / Belt Line).
our cam2 legs: L26 WB, L27 SB, L28 EB, L29 NB.

Usage:  py scripts/measure_cam2.py --start-hms 07:00:00 --minutes 5
"""
from __future__ import annotations
import argparse, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parse_miovision_xml as pmx
from parse_miovision_xml import camera_xml
from groundtruth import VIDEO_START, NORM_MVT

LEG_IDX = {26: 0, 27: 1, 28: 2, 29: 3}                 # our cam2 leg -> approach idx
IDX_NAME = {0: "WB", 1: "SB", 2: "EB", 3: "NB"}
MVT = {"T": "thru", "R": "right", "L": "left", "U": "uturn"}   # match groundtruth.NORM_MVT


def manual_per_minute_cam2():
    pmx.XML = camera_xml(2)                              # repoint parser to cam2
    data = pmx.parse()
    movements = data["movements"]                       # [(Name, in_idx, out_idx)]
    mv = defaultdict(lambda: defaultdict(int))
    for tm, vols in data["per_min"].items():
        dt = datetime.fromisoformat(tm)
        for i, v in enumerate(vols):
            name, in_i, _ = movements[i]
            mvt = MVT.get((name or "").upper()[:1], (name or "").lower())
            mv[dt][(in_i, mvt)] += v
    return mv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/projects/97a7849a/project.db")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=5.0)
    args = ap.parse_args()
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    start_sec = (t0 - VIDEO_START).total_seconds()
    mins = [t0 + timedelta(minutes=i) for i in range(int(args.minutes))]

    m_mv = manual_per_minute_cam2()
    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT origin_leg_id, movement, timestamp_video FROM vehicle_events "
        "WHERE camera_id=2 AND rejected=0 AND timestamp_video>=? AND timestamp_video<?",
        (start_sec, start_sec + args.minutes * 60)).fetchall()
    conn.close()
    o_mv = defaultdict(lambda: defaultdict(int))
    for ol, mvt_raw, ts in rows:
        ii = LEG_IDX.get(ol)
        if ii is None:
            continue
        mvt = NORM_MVT.get(mvt_raw, mvt_raw)
        minute = (VIDEO_START + timedelta(seconds=ts)).replace(second=0, microsecond=0)
        o_mv[minute][(ii, mvt)] += 1

    cells = set()
    for mn in mins:
        cells |= set(m_mv.get(mn, {})) | set(o_mv.get(mn, {}))
    print(f"cam2 baseline (bytetrack, no bank) — window {args.start_hms}+{args.minutes:.0f}min\n")
    print(f"{'cell':<14}{'manual':>7}{'ours':>6}{'net':>6}{'gross':>7}")
    tman = tnet = tg = 0
    for cell in sorted(cells, key=lambda c: -sum(abs(o_mv.get(mn,{}).get(c,0)-m_mv.get(mn,{}).get(c,0)) for mn in mins)):
        man = sum(m_mv.get(mn, {}).get(cell, 0) for mn in mins)
        ours = sum(o_mv.get(mn, {}).get(cell, 0) for mn in mins)
        g = sum(abs(o_mv.get(mn, {}).get(cell, 0) - m_mv.get(mn, {}).get(cell, 0)) for mn in mins)
        tman += man; tnet += abs(ours - man); tg += g
        if man == 0 and ours == 0:
            continue
        in_i, mvt = cell
        print(f"{IDX_NAME.get(in_i,in_i)+' '+mvt:<14}{man:>7}{ours:>6}{abs(ours-man):>6}{g:>7}")
    print(f"{'TOTAL':<14}{tman:>7}{'':>6}{tnet:>6}{tg:>7}")
    if tman:
        print(f"  net agg_err = {tnet/tman*100:.1f}%   per-min gross = {tg/tman*100:.1f}%")
    print(f"  (our cam2 events in window: {len(rows)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
