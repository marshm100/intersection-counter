"""B-VAL — retrospective validation of the blind flag queue
(docs/plan_flagqueue_B_2026-07-09.md, the §1b trust step).

Runs rebuild_flags over a project's intersections, then scores the resulting
OPEN queue against the KNOWN GT-validated misses (targets T1-T7). Ground truth
was used once, offline, to define the target list; the queue itself runs blind.
The deliverable is the coverage map: which known-miss CLASSES the current
feeders surface, at what worklist rank, at what operator load — including the
honest misses (S1/S2 are structurally blind to uniform losses; that is what
justifies the planned S3/S4/S5 feeders).

Usage:
  py scripts/flagqueue_retrospective.py --project 97a7849a
  py scripts/flagqueue_retrospective.py --project 0acb12c0 --no-rebuild
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time as _time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import get_connection
from backend.services.flag_feeders import rebuild_flags

# Known GT-validated misses. approach = BOUND letter (flags store bound).
# window = video-time second ranges where the miss lives (None = anywhere).
# guard=True → the target must stay QUIET (a fixed bug re-flagging = noise).
TARGETS = [
    dict(id="T1", project="97a7849a", intersection_id=2, approach="S", movement="right",
         windows=[(25200, 27000)], note="cam2 SB-right 58% recall (uniform; only 30min of events live)"),
    dict(id="T2", project="97a7849a", intersection_id=2, approach="E", movement="through",
         windows=[(25200, 27000)], note="cam2 EB-thru bank hole (31 real vs 4 counted / 30min)"),
    dict(id="T3", project="97a7849a", intersection_id=5, approach="E", movement="right",
         windows=[(25200, 32400), (57600, 64800)], note="cam5 EB-right -41%"),
    dict(id="T4", project="97a7849a", intersection_id=1, approach="N", movement="left",
         windows=[(25200, 32400), (57600, 64800)], note="cam1 NB-left merge-borderline (+38 blind)"),
    dict(id="T5", project="97a7849a", intersection_id=2, approach="N", movement="left",
         windows=[(25200, 27000)], note="cam2 NB-left -66"),
    dict(id="T6", project="0acb12c0", intersection_id=2, approach="N", movement=None,
         windows=[(59400, 64800)], note="FM51 NB PM detection sag (-12..-20%/interval 16:30-18:00)"),
    dict(id="T7", project="0acb12c0", intersection_id=2, approach="W", movement=None,
         windows=None, guard=True, note="FM51 WB side-road overcount FIXED — must stay quiet"),
]


def _overlaps(f_lo, f_hi, windows) -> bool:
    if windows is None or f_lo is None:
        return True          # un-intervaled flag (event flag) or untargeted window
    return any(not (f_hi <= lo or f_lo >= hi) for lo, hi in windows)


def _matches(flag: dict, tgt: dict) -> bool:
    if flag["intersection_id"] != tgt["intersection_id"]:
        return False
    if flag["approach"] and tgt["approach"] and flag["approach"][0].upper() != tgt["approach"]:
        return False
    if flag["movement"] and tgt["movement"] and flag["movement"] != tgt["movement"]:
        return False
    return _overlaps(flag["interval_start_seconds"], flag["interval_end_seconds"],
                     tgt.get("windows"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--no-rebuild", action="store_true",
                    help="score the queue as it stands (skip rebuild_flags)")
    args = ap.parse_args()
    proj = args.project

    conn = get_connection(proj)
    inter_ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT c.intersection_id FROM cameras c "
        "JOIN vehicle_events e ON e.camera_id = c.camera_id AND e.rejected = 0")]
    conn.close()

    if not args.no_rebuild:
        for iid in sorted(inter_ids):
            t0 = _time.time()
            res = rebuild_flags(proj, iid)
            print(f"rebuild intersection {iid}: {res.get('created', 0)} flags "
                  f"({_time.time() - t0:.1f}s)")

    conn = get_connection(proj)
    conn.row_factory = sqlite3.Row
    flags = [dict(r) for r in conn.execute(
        "SELECT * FROM review_flags WHERE status = 'open'")]
    # active footage: 900s bins with any event, across cameras
    bins = conn.execute(
        "SELECT COUNT(DISTINCT camera_id || '/' || CAST(timestamp_video / 900 AS INTEGER)) "
        "FROM vehicle_events WHERE rejected = 0 AND timestamp_video IS NOT NULL").fetchone()[0]
    conn.close()
    hours = bins * 900 / 3600.0

    print(f"\n=== {proj}: {len(flags)} open flags over {hours:.1f} camera-hours "
          f"({len(flags) / hours * 2 if hours else 0:.1f} flags per 2 camera-hours)")
    by_sub: dict[str, int] = {}
    for f in flags:
        by_sub[f["subtype"]] = by_sub.get(f["subtype"], 0) + 1
    for s, n in sorted(by_sub.items(), key=lambda kv: -kv[1]):
        print(f"    {s:<24}{n}")

    # impact-ordered rank within each intersection's worklist
    order: dict[int, list[int]] = {}
    for iid in inter_ids:
        fl = sorted((f for f in flags if f["intersection_id"] == iid),
                    key=lambda f: -f["impact"])
        order[iid] = [f["flag_id"] for f in fl]

    # CAUGHT requires a suspected_gap flag — a single low-confidence EVENT in the
    # right cell is an anecdote, not detection of a systemic miss.
    print(f"\n{'tgt':<5}{'result':<12}{'best flag (subtype, rank/list, impact)':<48}note")
    for tgt in TARGETS:
        if tgt["project"] != proj:
            continue
        hits = [f for f in flags if _matches(f, tgt)]
        if tgt.get("guard"):
            gap_hits = [f for f in hits if f["kind"] == "suspected_gap"]
            verdict = "QUIET" if not gap_hits else f"NOISY({len(gap_hits)})"
            print(f"{tgt['id']:<5}{verdict:<12}{'-':<48}{tgt['note']}")
            continue
        gap_hits = [f for f in hits if f["kind"] == "suspected_gap"]
        ev_hits = [f for f in hits if f["kind"] == "uncertain_event"]
        if gap_hits:
            best = max(gap_hits, key=lambda f: f["impact"])
            verdict = "CAUGHT"
        elif ev_hits:
            best = max(ev_hits, key=lambda f: f["impact"])
            verdict = "ANECDOTAL"
        else:
            print(f"{tgt['id']:<5}{'MISSED':<12}{'-':<48}{tgt['note']}")
            continue
        lst = order[tgt["intersection_id"]]
        rank = lst.index(best["flag_id"]) + 1
        desc = f"{best['subtype']}, rank {rank}/{len(lst)}, impact {best['impact']:.0f}"
        print(f"{tgt['id']:<5}{verdict:<12}{desc:<48}{tgt['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
