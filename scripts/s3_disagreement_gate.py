"""S3 mini-gate — two-counter (live vs box-clip) disagreement feeder ablation
(docs/plan_flagqueue_B_2026-07-09.md B4-S3).

Compares the live event stream against the box-clip pass-2 replay per
(bound-approach, movement) cell x 15-min bin, over the window both cover.
Flag rule: |live - boxclip| >= max(FLOOR, FRAC * max(live, boxclip)).
The ablation grid measures, per (FLOOR, FRAC): does the rule fire on the
GT-known bad cells (cam2 SB-thru / EB-right / NB-left, cam5 EB-right), and how
many flags land on the PASSING cams (3/4) = the operator-noise price. GT is
used only HERE, offline, to pick the frozen constants (the S3 mini-gate);
the feeder itself never sees it.

Usage:  py scripts/s3_disagreement_gate.py --boxclip-dir <dir with s3_boxclip_camN.db>
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_cam2_reid_spike import load_events_db

PROJ_DB = "data/projects/97a7849a/project.db"
# comparison window per camera: what BOTH counters cover (cam2 live = 30 min only)
WINDOWS = {1: (7 * 60, 9 * 60), 2: (7 * 60, 7 * 60 + 30), 3: (7 * 60, 9 * 60),
           4: (7 * 60, 9 * 60), 5: (7 * 60, 9 * 60)}
# GT-known bad cells the rule MUST fire on (cell = (bound letter, movement))
TARGET_CELLS = {2: [("S", "thru"), ("E", "right"), ("N", "left")],
                5: [("E", "right")]}
PASSING_CAMS = (3, 4)


def bin_counts(db: str, cam: int) -> dict[tuple, int]:
    """{(bin_start_min, bound_letter, movement): n} for the camera's window."""
    lo, hi = WINDOWS[cam]
    per_min = load_events_db(db, cam)
    per_min.pop("_n_events", None)
    out: dict[tuple, int] = defaultdict(int)
    for t, cells in per_min.items():
        if not isinstance(t, time):
            continue
        m = t.hour * 60 + t.minute
        if not (lo <= m < hi):
            continue
        b = (m // 15) * 15
        for (d, mv), n in cells.items():
            out[(b, d[0].upper(), mv)] += n
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boxclip-dir", required=True)
    ap.add_argument("--cams", default="1,2,3,4,5")
    args = ap.parse_args()
    cams = [int(c) for c in args.cams.split(",")]

    live, box = {}, {}
    for cam in cams:
        live[cam] = bin_counts(PROJ_DB, cam)
        box[cam] = bin_counts(str(Path(args.boxclip_dir) / f"s3_boxclip_cam{cam}.db"), cam)

    print(f"{'grid':<22}{'target cells fired':<40}{'noise flags cam3/cam4 (per 2h)':<32}{'total flags all cams'}")
    for floor in (4, 6, 8):
        for frac in (0.20, 0.25, 0.35):
            fired: dict[int, set] = defaultdict(set)
            n_flags: dict[int, int] = defaultdict(int)
            for cam in cams:
                keys = set(live[cam]) | set(box[cam])
                for k in keys:
                    lv, bv = live[cam].get(k, 0), box[cam].get(k, 0)
                    if abs(lv - bv) >= max(floor, frac * max(lv, bv)):
                        n_flags[cam] += 1
                        fired[cam].add((k[1], k[2]))
            t_hit = []
            for cam, cells in TARGET_CELLS.items():
                if cam not in cams:
                    continue
                for c in cells:
                    mark = "Y" if c in fired[cam] else "n"
                    t_hit.append(f"cam{cam} {c[0]}-{c[1]}:{mark}")
            hits = sum(1 for s in t_hit if s.endswith(":Y"))
            noise = "/".join(str(n_flags[c]) for c in PASSING_CAMS if c in cams)
            print(f"floor={floor} frac={frac:<6}{hits}/{len(t_hit)}  "
                  f"{' '.join(t_hit):<48}{noise:<32}{sum(n_flags.values())}")
    # detail at the working point for inspection
    print("\nper-cell detail (floor=6, frac=0.25):")
    for cam in cams:
        keys = sorted(set(live[cam]) | set(box[cam]))
        rows = []
        for k in keys:
            lv, bv = live[cam].get(k, 0), box[cam].get(k, 0)
            if abs(lv - bv) >= max(6, 0.25 * max(lv, bv)):
                rows.append((abs(lv - bv), k, lv, bv))
        for d, k, lv, bv in sorted(rows, reverse=True):
            b, dd, mv = k
            print(f"  cam{cam} {dd}-{mv:<7} bin {b // 60:02d}:{b % 60:02d}  live {lv:>4}  boxclip {bv:>4}  |d|={d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
