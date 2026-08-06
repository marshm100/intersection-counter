"""Pipeline-V2 D4 — movement events from assembled chains
(plan_v2_week1_derisk §D4).

Chains (greedy engine, frozen cost) -> concatenated point sequence ->
the SHARED entry_gates.classify (identical geometry semantics to
production) -> full-journey events with movement via the production
derive_movement (rank-based, skew-robust). tag!="full" chains emit
nothing (natural counting-stage phantom filter). '--engine none' is the
no-assembly control: every tracklet counts alone.

Miovision is NEVER read here (D5 only).

Usage:
  py -X utf8 scripts/v2_assign.py runs/v2_week1/tracklets_cam2_study_0700.npz --engine greedy
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import fit_motion_residual, load_table  # noqa: E402
from backend.services.entry_gates import classify      # noqa: E402
from backend.services.trajectory_classifier import derive_movement  # noqa: E402

REC_START = "2026-05-12T00:00:02"     # corridor recording start (videos table)


def load_legs(project_id: str, camera_id: int) -> dict[int, dict]:
    conn = sqlite3.connect(f"file:data/projects/{project_id}/project.db?mode=ro",
                           uri=True)
    conn.row_factory = sqlite3.Row
    legs = {r["leg_id"]: dict(r) for r in conn.execute(
        "SELECT leg_id, label, cardinal_direction, reference_heading "
        "FROM legs WHERE camera_id=?", (camera_id,))}
    conn.close()
    return legs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--engine", default="greedy", choices=["greedy", "none"])
    args = ap.parse_args()

    t = load_table(args.table)
    fps = t["fps"]
    stem = Path(args.table).stem.replace("tracklets_", "")
    camera_id = int(stem.split("_")[0].replace("cam", ""))
    legs = load_legs(args.project, camera_id)
    all_legs = list(legs.values())
    gates = {int(k): (tuple(v[0]), tuple(v[1]), tuple(v[2]))
             for k, v in t["meta"]["gates"].items()}

    if args.engine == "greedy":
        from v2_baseline_greedy import stitch_greedy
        cal = fit_motion_residual(t)
        _links, chains = stitch_greedy(t, cal)
    else:
        chains = [[i] for i in range(t["n"])]

    rec0 = datetime.fromisoformat(REC_START)
    events, tags = [], {"full": 0, "entry_only": 0, "exit_only": 0,
                        "no_crossing": 0}
    for ch in chains:
        parts = [t["rows"][int(t["starts"][i]):int(t["ends"][i])] for i in ch]
        tr = np.concatenate(parts)
        tr = tr[np.argsort(tr[:, 1])]
        track = [(float(f), float(x), float(y))
                 for f, x, y in zip(tr[:, 1], tr[:, 2], tr[:, 3])]
        o, d, ofr, dfr, _op, _dp, tag = classify(track, gates, fps)
        tags[tag] += 1
        if tag != "full":
            continue
        mv = derive_movement(legs[o], legs[d], all_legs)
        wall = rec0 + timedelta(seconds=float(dfr) / fps)
        events.append({"origin_leg": int(o), "dest_leg": int(d),
                       "movement": mv, "frame": float(dfr),
                       "wallclock": wall.isoformat(),
                       "chain_len": len(ch)})

    out = Path("runs/v2_week1") / f"events_{stem}_{args.engine}.json"
    out.write_text(json.dumps({"camera": camera_id, "engine": args.engine,
                               "chains": len(chains), "tags": tags,
                               "events": events}, indent=0))
    ml = sum(1 for e in events if e["chain_len"] > 1)
    print(f"[D4] {stem} engine={args.engine}: chains={len(chains)} "
          f"tags={tags} events={len(events)} (from multi-tracklet "
          f"chains: {ml}) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
