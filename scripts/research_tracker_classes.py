"""Size the tracker classes the hand-off reel named (2026-09-12), read-only.

LATE BIRTH: per yardstick vehicle (chain), the hits before any tracker track
first covers it; a late birth = >= 0.5 s of hits uncovered at the start. Split
by the best confidence among those uncovered hits: all < det_thresh 0.35 (weak
boxes cannot start a track) vs some >= 0.35 (something else refused the birth).
RIGID PAIR (towed trailer candidates): two dump tracks whose boxes sit side by
side (vertical overlap > 0.5 of the smaller box, horizontal gap within -0.3 ..
+0.15 box widths) on >= 1 s of shared frames, both moving, with the centre
offset between them steady (std < 0.1 box widths). Unverified on film.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_tracker_classes.py PROJ CAM VARIANT VEHICLES_JSON
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def main() -> int:
    proj, cam, variant, vfile = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    rows = np.asarray(load_dump(tracks_dir(parquet_path(proj, cam, chash, variant))))
    rows_f = rows[np.argsort(rows[:, 1], kind="stable")]
    uf, s_ = np.unique(rows_f[:, 1], return_index=True); e_ = np.append(s_[1:], len(rows_f))
    fidx = dict(zip(uf.astype(int), zip(s_, e_)))
    veh = json.loads(Path(vfile).read_text())
    half_s = max(2, int(round(0.5 * fps)))

    late_weak = late_other = on_time = never = 0
    delays = []
    for v in veh:
        k0 = None
        for k, (f, a, b, c, d, s) in enumerate(v):
            ab = fidx.get(int(f))
            if ab is None:
                continue
            if any(iou((a, b, c, d), (r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2)) >= 0.3
                   for r in rows_f[ab[0]:ab[1]]):
                k0 = k
                break
        if k0 is None:
            never += 1
            continue
        if k0 < half_s:
            on_time += 1
            continue
        delays.append(k0)
        best = max(h[5] for h in v[:k0])
        if best < 0.35:
            late_weak += 1
        else:
            late_other += 1
    n = len(veh)
    print(f"{proj} cam{cam} {variant}: {n} vehicles on the yardstick")
    print(f"  LATE BIRTH (>= {half_s} hits = 0.5 s uncovered at the start): {late_weak + late_other} ({(late_weak + late_other) / n:.0%}); "
          f"all uncovered boxes < 0.35: {late_weak}; some >= 0.35: {late_other}; delay median {np.median(delays) if delays else 0:.0f} frames")
    print(f"  on time {on_time}; never covered {never}")

    # rigid pairs
    pair = defaultdict(list)   # (ta, tb) -> [(frame, dx_over_w)]
    speed = {}
    for t in np.unique(rows[:, 0]):
        r = rows[rows[:, 0] == t]
        if len(r) >= 3:
            speed[int(t)] = float(np.median(np.hypot(np.diff(r[:, 2]), np.diff(r[:, 3])) / np.maximum(1, np.diff(r[:, 1]))))
    for f, (a_, b_) in fidx.items():
        g = rows_f[a_:b_]
        if len(g) < 2:
            continue
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                A, B = g[i], g[j]
                if A[2] > B[2]:
                    A, B = B, A
                wa, wb = A[4], B[4]
                w = (wa + wb) / 2
                ay1, ay2 = A[3] - A[5] / 2, A[3] + A[5] / 2
                by1, by2 = B[3] - B[5] / 2, B[3] + B[5] / 2
                vov = max(0.0, min(ay2, by2) - max(ay1, by1)) / max(1e-6, min(A[5], B[5]))
                gap = (B[2] - wb / 2) - (A[2] + wa / 2)
                if vov > 0.5 and -0.3 * w <= gap <= 0.15 * w:
                    pair[(int(A[0]), int(B[0]))].append((f, (B[2] - A[2]) / w))
    rigid = []
    for (ta, tb), obs in pair.items():
        if len(obs) < fps:
            continue
        if speed.get(ta, 0) < 1.0 or speed.get(tb, 0) < 1.0:
            continue
        off = np.asarray([o[1] for o in obs])
        if off.std() < 0.1:
            rigid.append((ta, tb, len(obs), float(off.mean())))
    print(f"  RIGID PAIRS (side by side >= 1 s, both moving, steady offset): {len(rigid)} "
          f"(of {sum(1 for o in pair.values() if len(o) >= fps)} side-by-side pairs >= 1 s)")
    Path(f"runs/v2_week1/rigid_pairs_{proj}_{cam}_{variant}.json").write_text(json.dumps(rigid[:300]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
