"""cam2 SB-right follow-up: (a) does yolo26l@1280 lift the ENTRY region above the
0.25 birth gate (the diagnosis: region A conf ~0.30, 42% below gate — edge-clip)?
(b) are novel accurate dets in the SB-right zone moving vehicles or flicker?
Runs on the 1 Hz sampled accurate pass vs the balanced cache on matched frames."""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
os.chdir(REPO)

import numpy as np
import pandas as pd
from detector_zone_recall import ZONES, load_curves, in_zone

# the sampled accurate pass output (scripts/cam2_accurate_sampled_pass.py)
SAMPLED = (Path(sys.argv[1]) if len(sys.argv) > 1
           else REPO / "evaluations/cam2_accurate1280_sampled.parquet")
base = REPO / "data/projects/97a7849a/detections/2/9446ff1f8376a97e1d7f3021fd27ae69554f93301c8990268a584a8504de4419"

bal = pd.read_parquet(base / "balanced_960_skip1.parquet")
acc = pd.read_parquet(SAMPLED)
frames = np.intersect1d(bal.frame_idx.unique(), acc.frame_idx.unique())
bal = bal[bal.frame_idx.isin(frames)]
acc = acc[acc.frame_idx.isin(frames)]
print(f"matched frames: {len(frames)}")

name, kind, ids = ZONES[2]["failing"]
curves = load_curves(2, kind, ids)

# (a) entry-third confidence profile per config
for tag, df in (("balanced_960", bal), ("accurate_1280", acc)):
    mask, third = in_zone(df, curves, 30.0)
    z = df[mask].copy(); z["third"] = third[mask]
    e = z[(z.third == 0) & (z.confidence >= 0.10)]
    if len(e):
        below = (e.confidence < 0.25).mean() * 100
        print(f"{tag:<14} entry-third dets/frame {len(e)/len(frames):.3f}  "
              f"mean conf {e.confidence.mean():.3f}  median {e.confidence.median():.3f}  "
              f"below birth gate 0.25: {below:.0f}%")
    else:
        print(f"{tag:<14} entry-third: no dets")

# (b) novel accurate dets in-zone: moving or stationary? (1 Hz samples: a moving
# vehicle displaces 25-40 px between samples; chain radius 60 px, gap <= 2 samples)
mask, third = in_zone(acc, curves, 30.0)
a = acc[mask & (acc.confidence >= 0.25)].copy()
a["third"] = third[mask & (acc.confidence >= 0.25).to_numpy()]
b = bal[bal.confidence >= 0.10]
from collections import defaultdict
bmap = defaultdict(list)
for f, x1, y1, x2, y2 in zip(b.frame_idx.astype(int), b.bbox_x1, b.bbox_y1, b.bbox_x2, b.bbox_y2):
    bmap[f].append(((x1 + x2) / 2, (y1 + y2) / 2))
novel = []
for f, x1, y1, x2, y2, t in zip(a.frame_idx.astype(int), a.bbox_x1, a.bbox_y1,
                                a.bbox_x2, a.bbox_y2, a.third):
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    pts = bmap.get(f)
    if not pts or min(np.hypot(px - cx, py - cy) for px, py in pts) > 25:
        novel.append((f, cx, cy, t))
novel.sort()
n_entry = sum(1 for n in novel if n[3] == 0)
print(f"\nnovel accurate dets >=0.25 in-zone: {len(novel)} over {len(frames)} sampled frames"
      f" ({len(novel)/len(frames):.3f}/frame); entry-third: {n_entry} ({n_entry/len(frames):.3f}/frame)")
used = [False] * len(novel)
chains = []
for i in range(len(novel)):
    if used[i]:
        continue
    used[i] = True; ch = [novel[i]]
    for j in range(i + 1, len(novel)):
        if used[j]:
            continue
        f, x, y, _ = novel[j]; lf, lx, ly, _ = ch[-1]
        if f - lf > 50:  # 2 sampled frames
            break
        if f > lf and np.hypot(x - lx, y - ly) <= 60:
            used[j] = True; ch.append(novel[j])
    chains.append(ch)
multi = [c for c in chains if len(c) >= 3]  # seen >= 3 consecutive seconds
moving = [c for c in multi if np.hypot(c[-1][1] - c[0][1], c[-1][2] - c[0][2]) > 30]
print(f"chains >=3 samples: {len(multi)}  of which MOVING (>30px net): {len(moving)}"
      f"  -> moving novel vehicles/min ~{len(moving)/30:.2f}")
for c in moving[:12]:
    print(f"   f{c[0][0]}-{c[-1][0]}  ({c[0][1]:.0f},{c[0][2]:.0f})->({c[-1][1]:.0f},{c[-1][2]:.0f}) n={len(c)}")
