"""Stage C — cam5 fate ledger on the REPLAY path (plan_cam5_eb_bankhole_2026-07-27).

Wraps ProcessingPipeline._finalize_vehicle_data at CLASS level (the
diagnose_ebright_loss pattern, lifted so it works through replay_camera's
internally-constructed pipe) and replays one stock window. For every
finalized track records: nearest-leg start/end (geometric cell), points,
entry origin (None = the no-origin gate), final origin/destination/movement,
insufficient-data drop. Then two tallies:

  1. FORWARD  — for each geometric cell of interest: what the pipeline DID
     with those tracks (event cell distribution, drop reasons).
  2. REVERSE  — for each attributed event cell: which geometric cells fed it.

Usage: py scripts/cam5_wall_fate.py [--window study_0700]
Evidence -> runs/cam5_wall/fate_<window>.json. Basis: replayed-minutes
(replay-only, no merge), same as phase 0.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.pass2_replay import replay_camera
from backend.services.pipeline import ProcessingPipeline

PROJECT = "97a7849a"
CAM = 5
SCRATCH = Path(r"C:\Users\onkar\AppData\Local\Temp\ic_scratch_97a7849a")

RECORDS: list[dict] = []
_LEGS: dict[int, tuple[float, float]] = {}


def _nearest(pt):
    if not _LEGS:
        return None
    return min(_LEGS, key=lambda l: math.hypot(pt[0] - _LEGS[l][0],
                                               pt[1] - _LEGS[l][1]))


_ORIG = ProcessingPipeline._finalize_vehicle_data


def _wrap(self, track_id, vehicle, frame_number):
    traj = vehicle.get("trajectory", [])
    sl = _nearest(traj[0]) if len(traj) >= 2 else None
    el = _nearest(traj[-1]) if len(traj) >= 2 else None
    entry_origin = vehicle.get("origin_leg_id")
    ins0 = self.n_insufficient_data
    _ORIG(self, track_id, vehicle, frame_number)
    RECORDS.append({
        "tid": track_id, "sl": sl, "el": el, "npts": len(traj),
        "entry_origin": entry_origin,
        "final_origin": vehicle.get("origin_leg_id"),
        "dropped_insuf": self.n_insufficient_data > ins0,
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="study_0700")
    args = ap.parse_args()

    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    for lid, oz in conn.execute(
            "SELECT leg_id, origin_zone FROM legs WHERE camera_id=?", (CAM,)):
        if oz:
            z = json.loads(oz)
            _LEGS[lid] = (z[0][0], z[0][1]) if isinstance(z[0], (list, tuple)) \
                else (z[0], z[1])
    conn.close()
    print(f"[legs] anchors: { {k: [round(x) for x in v] for k, v in _LEGS.items()} }",
          flush=True)

    ProcessingPipeline._finalize_vehicle_data = _wrap
    try:
        out = SCRATCH / f"cam5wall_fate_{args.window}.db"
        st = replay_camera(PROJECT, CAM, variant=args.window, out_db=out)
    finally:
        ProcessingPipeline._finalize_vehicle_data = _ORIG
    print(f"[C] {args.window}: events={st['events']} tracks={st.get('tracks')} "
          f"finalized_records={len(RECORDS)}", flush=True)

    # Join finalized tracks to the events the replay actually wrote — the
    # pipeline computes destination locally and never mutates the vehicle
    # dict, so the DB rows are the only truth (join on vehicle_track_id,
    # the autopsies-doc pattern; finalize-gap ID reuse = single-digit noise).
    c = sqlite3.connect(str(out))
    ev_by_tid: dict[int, list] = defaultdict(list)
    for tid, o, d, mv in c.execute(
            "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
            "movement FROM vehicle_events WHERE camera_id=? AND "
            "COALESCE(rejected,0)=0", (CAM,)):
        ev_by_tid[tid].append((o, d, mv))
    c.close()

    sub = [r for r in RECORDS if r["npts"] >= 4]

    fwd = {}
    for cell in sorted({(r["sl"], r["el"]) for r in sub}):
        rs = [r for r in sub if (r["sl"], r["el"]) == cell]
        ev = Counter()
        n_kept = 0
        for r in rs:
            evs = ev_by_tid.get(r["tid"], [])
            if evs:
                n_kept += 1
                for (o, d, _mv) in evs:
                    ev[f"{o}>{d}"] += 1
        fwd[f"{cell[0]}>{cell[1]}"] = {
            "n": len(rs),
            "kept": n_kept,
            "no_origin": sum(1 for r in rs if r["entry_origin"] is None
                             and r["final_origin"] is None),
            "insuf": sum(r["dropped_insuf"] for r in rs),
            "event_cells": dict(ev.most_common(6)),
        }

    rev = {}
    geo_by_tid = {r["tid"]: f"{r['sl']}>{r['el']}" for r in sub}
    ev_cells = defaultdict(Counter)
    for tid, evs in ev_by_tid.items():
        for (o, d, _mv) in evs:
            ev_cells[f"{o}>{d}"][geo_by_tid.get(tid, "untracked")] += 1
    for cell, geo in sorted(ev_cells.items()):
        rev[cell] = {"n": sum(geo.values()),
                     "geo_cells": dict(geo.most_common(8))}

    outp = Path(f"runs/cam5_wall/fate_{args.window}.json")
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(
        {"window": args.window, "n_finalized": len(RECORDS),
         "n_ge4pts": len(sub),
         "n_tracks_with_events": len(ev_by_tid),
         "forward_geo_to_events": fwd, "reverse_events_to_geo": rev},
        indent=1))
    print(f"wrote {outp}", flush=True)

    for c in ("38>36", "39>36", "36>39", "38>39", "39>37", "37>39"):
        if c in fwd:
            print(f"[fwd] geo {c}: {json.dumps(fwd[c])}", flush=True)
    for c in ("39>37", "39>38", "38>39", "38>37"):
        if c in rev:
            print(f"[rev] event {c}: {json.dumps(rev[c])}", flush=True)
    print("FATE DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
