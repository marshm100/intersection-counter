"""Pipeline-V2 — pair-geometry diagnostic for same-cell co-temporal full
journeys (day-5 open thread: what do the EB duplicates actually look
like?). Prints, per cell, the distribution of mean common-frame distance
and entry-time deltas for overlapping full-journey pairs — the dedup
criterion gets set from the measured bimodality, not assumption.

Usage: py -X utf8 scripts/v2_pair_geometry.py runs/v2_week1/tracklets_cam2_v2c_study_0700.npz
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import load_table, track_points         # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("--min-overlap", type=float, default=0.5)
    args = ap.parse_args()
    t = load_table(args.table)
    fps = t["fps"]
    full = np.where(t["tag"] == 0)[0]
    key: dict[tuple, list[int]] = {}
    for i in full:
        key.setdefault((int(t["origin_leg"][i]), int(t["dest_leg"][i])),
                       []).append(int(i))
    for cell, members in sorted(key.items()):
        if len(members) < 2:
            continue
        members.sort(key=lambda i: t["f0"][i])
        f0s = np.array([t["f0"][i] for i in members])
        f1s = np.array([t["f1"][i] for i in members])
        dists, dts = [], []
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                if f0s[b] > f1s[a]:
                    break
                ov = min(f1s[a], f1s[b]) - max(f0s[a], f0s[b])
                shorter = min(f1s[a] - f0s[a], f1s[b] - f0s[b]) or 1.0
                if ov / shorter < args.min_overlap:
                    continue
                rx = track_points(t, members[a])
                ry = track_points(t, members[b])
                fy = {int(r[1]): r for r in ry}
                ds = [float(np.hypot(r[2] - fy[int(r[1])][2],
                                     r[3] - fy[int(r[1])][3]))
                      for r in rx if int(r[1]) in fy]
                if len(ds) < 5:
                    continue
                dists.append(float(np.mean(ds)))
                dts.append(abs(float(t["o_frame"][members[a]])
                               - float(t["o_frame"][members[b]])) / fps)
        if not dists:
            continue
        d = np.array(dists)
        hist = {f"<{b}": int((d < b).sum()) for b in (15, 25, 40, 60, 100)}
        hist[">=100"] = int((d >= 100).sum())
        print(f"cell {cell}: n_pairs={len(d)} mean-dist deciles="
              f"{np.percentile(d, [10, 25, 50, 75, 90]).round(0).tolist()} "
              f"cum_hist={hist} entry_dt_med={np.median(dts):.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
