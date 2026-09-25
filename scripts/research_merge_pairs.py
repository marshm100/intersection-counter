"""What does the turn merge remove? (2026-09-25, arms mg0/mg1)

Reads each window's merge-pair sidecar (<stem>_cam{c}_{variant}.merge_pairs.json,
written by merge_replay_turns) and the arm DB + dump, and classifies every
absorption the merge made:
  CONTINUATION  the absorbed track is born after the root track died (the
                chain rule's -0.48 s allowance) and nearer the root's END
                than its START: one vehicle, tracked in two pieces.
  FOLLOWER      born nearer the root's START while the root had already
                moved on (root displacement > MERGE_PX): the next car at the
                same spot, a real vehicle the merge deleted.
  OTHER         neither (e.g. a root that never moved).
Diagnostics only; the thresholds here decide nothing in production.

Usage: .venv\\Scripts\\python.exe -X utf8 scripts/research_merge_pairs.py STEM
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
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.track_chains import STITCH_MOVE_GAP_S  # noqa: E402
from backend.services.turn_merge import MERGE_PX  # noqa: E402

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"),
           (2, "study_1100"), (2, "study_1600"), (3, "study_0600"),
           (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
           (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mg0"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    fleet = Counter()
    for cam, variant in WINDOWS:
        side = BASE / f"{stem}_cam{cam}_{variant}.merge_pairs.json"
        if not side.exists():
            print(f"cam{cam} {variant}: no sidecar")
            continue
        pairs = json.loads(side.read_text())["pairs"]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?",
                                 (cam,)).fetchone()
        fps = float(fps)
        legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
                                (cam,)))
        db = sqlite3.connect(f"file:{BASE / f'{stem}_cam{cam}_{variant}.db'}?mode=ro", uri=True)
        tid_of = dict(db.execute("SELECT event_id, vehicle_track_id FROM vehicle_events "
                                 "WHERE camera_id=?", (cam,)))
        rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
        order = np.argsort(rows[:, 0], kind="stable")
        rs, tids = rows[order], rows[order][:, 0]

        def ends(tid):
            lo, hi = np.searchsorted(tids, tid, "left"), np.searchsorted(tids, tid, "right")
            if hi <= lo:
                return None
            sel = rs[lo:hi]
            sel = sel[np.argsort(sel[:, 1])]
            return (float(sel[0, 1]), float(sel[0, 2]), float(sel[0, 3]),
                    float(sel[-1, 1]), float(sel[-1, 2]), float(sel[-1, 3]))

        by_cell = defaultdict(Counter)
        for p in pairs:
            r, a = ends(tid_of.get(p["root"], -1)), ends(tid_of.get(p["absorbed"], -1))
            cell = f"{legs.get(p['cell'][0])}->{legs.get(p['cell'][1])} {p['cell'][2]}"
            status = "applied" if p["applied"] else "declined"
            if r is None or a is None:
                by_cell[cell][f"{status}:unknown"] += 1
                continue
            rb_f, rb_x, rb_y, rd_f, rd_x, rd_y = r
            ab_f, ab_x, ab_y = a[0], a[1], a[2]
            to_end = math.hypot(ab_x - rd_x, ab_y - rd_y)
            to_start = math.hypot(ab_x - rb_x, ab_y - rb_y)
            moved = math.hypot(rd_x - rb_x, rd_y - rb_y)
            if ab_f >= rd_f + STITCH_MOVE_GAP_S[0] * fps and to_end <= to_start:
                kind = "continuation"
            elif to_start < to_end and moved > MERGE_PX:
                kind = "follower"
            else:
                kind = "other"
            by_cell[cell][f"{status}:{kind}"] += 1
            fleet[f"{status}:{kind}"] += 1
        tot = Counter()
        for c in by_cell.values():
            tot.update(c)
        print(f"cam{cam} {variant}: {len(pairs)} absorptions  {dict(tot)}")
        for cell, c in sorted(by_cell.items(), key=lambda kv: -sum(kv[1].values()))[:4]:
            print(f"    {cell:18} {dict(c)}")
    print(f"\nFLEET: {dict(fleet)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
