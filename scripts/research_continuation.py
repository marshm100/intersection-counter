"""Arm pc1 dry run (2026-09-25): what would THE PREDICTED-CONTINUATION RULE
reject on each window, and how much of it is chance?

Runs turn_merge.continuation_pairs over each window's dump against the
unrejected events of a basis arm DB (default gx2 == production). No pass 2.
The null re-runs the same test with each fragment's death moved +-10/20 s
(same position, same velocity): a dense queue hands out chance partners,
and the real-minus-null excess is what the rule can honestly claim.
The basis DB's events are post-merge, so the live rule (which runs before
the merge) sees slightly more events than this dry run does.

Usage: .venv\\Scripts\\python.exe -X utf8 scripts/research_continuation.py [STEM]
Gate (declared): chance above ~20% of the real pairs on any camera -> stop.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import TRACKER_RECOVERY_REACH  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.track_chains import (CHAIN_DIR_TOL_DEG,  # noqa: E402
                                           STITCH_MOVE_GAP_S)
from backend.services.track_cut import _bdiff  # noqa: E402
from backend.services.turn_merge import continuation_pairs  # noqa: E402
from backend.services.two_pass import _pinned_gates  # noqa: E402

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"),
           (2, "study_1100"), (2, "study_1600"), (3, "study_0600"),
           (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
           (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]
SHIFTS_S = (10.0, 20.0, -10.0, -20.0)


def arm_db(stem: str, cam: int, variant: str) -> Path:
    # cam4/cam5 arms ran on the vl3 dumps, promoted to study_* at the ship
    tag = f"vl3_{variant}" if cam in (4, 5) else variant
    return BASE / f"{stem}_cam{cam}_{tag}.db"


def fragments_with_partner(recs, fps, shift_f: float = 0.0) -> int:
    """How many exit-lacking fragments have ANY admissible partner when the
    fragment's death is moved by shift_f frames (0 = the real test, without
    the one-to-one greedy so real and null are counted alike)."""
    births = np.array([r["birth"][0] for r in recs], dtype=float)
    n = 0
    for a in recs:
        if a["tag"] not in ("entry_only", "no_crossing"):
            continue
        fa = a["death"][0] + shift_f
        xa, ya = a["death"][1], a["death"][2]
        lo = int(np.searchsorted(births, fa + STITCH_MOVE_GAP_S[0] * fps, "left"))
        hi = int(np.searchsorted(births, fa + STITCH_MOVE_GAP_S[1] * fps, "right"))
        for b in recs[lo:hi]:
            if b["tid"] == a["tid"] or b["death"][0] <= fa:
                continue
            if a["origin"] is None or b["origin"] != a["origin"]:
                continue
            g = b["birth"][0] - fa
            box = max(a["w_death"], b["w_birth"])
            if box <= 0:
                continue
            px, py = xa + a["vel"][0] * g, ya + a["vel"][1] * g
            if math.hypot(b["birth"][1] - px, b["birth"][2] - py) / box >= TRACKER_RECOVERY_REACH:
                continue
            ba, bb = a.get("b_end"), b.get("b_start")
            if ba is not None and bb is not None and _bdiff(ba, bb) > CHAIN_DIR_TOL_DEG:
                continue
            n += 1
            break
    return n


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "gx2"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    out = {}
    per_cam = defaultdict(lambda: [0, 0.0])
    print(f"basis {stem}; reach {TRACKER_RECOVERY_REACH} box, window {STITCH_MOVE_GAP_S} s")
    for cam, variant in WINDOWS:
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?",
                                 (cam,)).fetchone()
        fps = float(fps)
        legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
                                (cam,)))
        rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
        gates, skip = _pinned_gates(PROJ, cam, rows)
        if skip is not None:
            print(f"cam{cam} {variant}: {skip}")
            continue
        db = sqlite3.connect(f"file:{arm_db(stem, cam, variant)}?mode=ro", uri=True)
        ev = db.execute(
            "SELECT event_id, vehicle_track_id, origin_leg_id, movement FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0 AND vehicle_track_id IS NOT NULL "
            "AND vehicle_track_id>=0", (cam,)).fetchall()
        info = {e[0]: e for e in ev}
        recs, pairs = continuation_pairs([(e[0], e[1], e[2]) for e in ev], rows, fps, gates)
        real = fragments_with_partner(recs, fps)
        null = float(np.mean([fragments_with_partner(recs, fps, s * fps) for s in SHIFTS_S]))
        cells = Counter(f"{legs.get(info[a['eid']][2])} {info[a['eid']][3]}" for a, _b, _g, _r in pairs)
        tags = Counter(a["tag"] for a, _b, _g, _r in pairs)
        gaps = [g for _a, _b, g, _r in pairs]
        key = f"cam{cam}_{variant}"
        out[key] = {"events": len(ev), "rejects": len(pairs), "real_any": real,
                    "null_any": null, "cells": dict(cells), "tags": dict(tags)}
        per_cam[cam][0] += real
        per_cam[cam][1] += null
        print(f"{key:18} events {len(ev):6}  rejects {len(pairs):4}  "
              f"fragments w/ partner real {real:4} vs chance {null:6.1f} "
              f"({100 * null / max(real, 1):4.1f}%)  gap p50 "
              f"{np.median(gaps) if gaps else float('nan'):.2f}s  tags {dict(tags)}")
        print(f"{'':18} top rejected cells {cells.most_common(5)}")
    print("\nper camera, chance as a share of real:")
    for cam, (r, n) in sorted(per_cam.items()):
        print(f"  cam{cam}: real {r}  chance {n:.1f}  ({100 * n / max(r, 1):.1f}%)")
    Path("runs/v2_week1").mkdir(parents=True, exist_ok=True)
    Path(f"runs/v2_week1/research_continuation_{stem}.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
