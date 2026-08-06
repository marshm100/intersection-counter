"""Pipeline-V2 B1c — JOURNEY-LEVEL twin dedup (day-5: extension completes
both members of a concurrent twin pair, so duplicates now present as full
co-temporal journeys — far more evidence per decision than any dead
fragment-level channel).

Rule: two FULL-journey tracks are one vehicle iff
  same (origin_leg, dest_leg) AND |entry dt| <= 2 s AND |exit dt| <= 2 s
  AND mean common-frame distance <= 1.5 * zv_radius (twins ride together;
  a follower with the same gate pair rides a headway behind).
Keep the higher-evidence member (n_pts * mean_conf); drop the twin's rows.

Input: a D1 table (with gate features) + its dump. Output: v2d_ dump.

Usage:
  py -X utf8 scripts/v2_journey_dedup.py runs/v2_week1/tracklets_cam2_v2c_study_0700.npz
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import fit_motion_residual, load_table, track_points  # noqa: E402
from backend.services import two_pass as TP            # noqa: E402

DT_S = 2.0
DIST_MULT = 1.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("--project", default="97a7849a")
    args = ap.parse_args()
    t0 = time.time()

    t = load_table(args.table)
    fps = t["fps"]
    stem = Path(args.table).stem.replace("tracklets_", "")
    camera_id = int(stem.split("_")[0].replace("cam", ""))
    variant = "_".join(stem.split("_")[1:])          # e.g. v2c_study_0700
    cal = fit_motion_residual(t)
    max_d = DIST_MULT * cal["zv_radius"]

    full = np.where(t["tag"] == 0)[0]
    key = {}
    for i in full:
        key.setdefault((int(t["origin_leg"][i]), int(t["dest_leg"][i])),
                       []).append(int(i))

    parent = {int(i): int(i) for i in full}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    pairs = 0
    for cell, members in key.items():
        members.sort(key=lambda i: t["f0"][i])
        f0s = np.array([t["f0"][i] for i in members])
        f1s = np.array([t["f1"][i] for i in members])
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                if f0s[b] > f1s[a]:
                    break
                ov = min(f1s[a], f1s[b]) - max(f0s[a], f0s[b])
                shorter = min(f1s[a] - f0s[a], f1s[b] - f0s[b]) or 1.0
                if ov / shorter < 0.7:
                    continue
                x, y = members[a], members[b]
                rx, ry = track_points(t, x), track_points(t, y)
                fy = {int(r[1]): r for r in ry}
                ds = [float(np.hypot(r[2] - fy[int(r[1])][2],
                                     r[3] - fy[int(r[1])][3]))
                      for r in rx if int(r[1]) in fy]
                if len(ds) < 5 or float(np.mean(ds)) > max_d:
                    continue
                ra, rb = find(x), find(y)
                if ra != rb:
                    parent[rb] = ra
                    pairs += 1

    ev = t["n_pts"] * t["mean_conf"]
    groups: dict[int, list[int]] = {}
    for i in full:
        groups.setdefault(find(int(i)), []).append(int(i))
    drop = set()
    for members in groups.values():
        if len(members) > 1:
            members.sort(key=lambda i: -ev[i])
            drop.update(members[1:])

    keep_rows = [np.asarray(track_points(t, i)) for i in range(t["n"])
                 if i not in drop]
    rows = np.concatenate(keep_rows).astype(np.float32)
    rows = rows[np.lexsort((rows[:, 0], rows[:, 1]))]

    new_variant = variant.replace("v2c_", "v2d_")
    if new_variant == variant:
        new_variant = f"v2d_{variant}"
    dst = TP.tracks_dir(TP._camera_parquet(args.project, camera_id,
                                           new_variant))
    dst.mkdir(parents=True, exist_ok=True)
    meta = dict(t["meta"])
    meta["variant"] = new_variant
    meta["complete"] = True
    meta["v2d_journey_dedup"] = {"pairs": pairs, "dropped_tracks": len(drop),
                                 "dt_s": DT_S, "dist_mult": DIST_MULT}
    np.save(dst / "rows.npy", rows)
    (dst / "count.txt").write_text(str(len(rows)))
    (dst / "meta.json").write_text(json.dumps(
        {k: v for k, v in meta.items() if k != "gates"}))
    print(f"[dedup] {variant} -> {new_variant}: {pairs} twin pairs, "
          f"{len(drop)} tracks dropped -> {dst} ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
