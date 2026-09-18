"""At the frame where a bottom-edge NB track DIES, what did the detector offer
next frame, and why would ByteTrack not take it? (2026-09-12)
For each covering track (probe_cam4_nb_emergence tids json, base dump): the
track's last box vs the emergence chain's detection on the next frame(s):
IoU, the detection's conf, size ratio. Tabulates the failure class:
  conf < 0.25 & IoU < 0.5  -> low-score stage needs IoU>=0.5 (scale)
  conf >= 0.25 & IoU*conf < 0.2 -> fused score below match (conf/scale)
  IoU >= 0.2 & conf >= 0.25 -> should have matched (id taken by another?)
  no detection next frame -> detector gap
Usage: .venv/Scripts/python.exe -X utf8 scripts/probe_cam4_nb_death_point.py [VARIANT]
"""
from __future__ import annotations
import json, sqlite3, sys
from collections import Counter
from pathlib import Path
import numpy as np, pyarrow.parquet as pq
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services.detection_cache import parquet_path
from backend.services.pass2_replay import load_dump, tracks_dir
from probe_cam4_nb_emergence import dedup, link, XFAR, XNEAR
PROJ, CAM = "97a7849a", 4
VARIANT = sys.argv[1] if len(sys.argv) > 1 else "study_1600"

def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0: return 0.0
    return inter / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter)

con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (CAM,)).fetchone()
pqp = parquet_path(PROJ, CAM, chash, VARIANT)
meta = json.load(open(pqp.with_suffix(".meta.json"))); f0, f1 = meta["windows"][0]
t = pq.read_table(pqp).to_pandas()
fr = t.frame_idx.values; x1 = t.bbox_x1.values; y1 = t.bbox_y1.values; x2 = t.bbox_x2.values; y2 = t.bbox_y2.values; cf = t.confidence.values
keep = dedup(fr, x1, y1, x2, y2, cf) & (cf >= 0.10) & (fr >= f0) & (fr <= f1)
idx = np.flatnonzero(keep); idx = idx[np.argsort(fr[idx], kind="stable")]
by_frame = {}
for i in idx: by_frame.setdefault(int(fr[i]), []).append(i)
rows = np.asarray(load_dump(tracks_dir(pqp))); rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
tids, st = np.unique(rows[:, 0], return_index=True); en = np.append(st[1:], len(rows))
seg = {int(t_): (a, b) for t_, a, b in zip(tids, st, en)}
cov = json.loads(Path(f"runs/v2_week1/probe_cam4_nb_emergence_{VARIANT}_tids.json").read_text())["covering"]
cls = Counter(); ious = []; confs = []; ratios = []; life = []
for c in cov:
    tid = int(c["tid"]); a, b = seg[tid]; trk = rows[a:b]
    last = trk[-1]; fd = int(last[1]); life.append(len(trk))
    lb = (last[2]-last[4]/2, last[3]-last[5]/2, last[2]+last[4]/2, last[3]+last[5]/2)
    if last[2] > 600: cls["died at the right edge (left the frame)"] += 1; continue
    best = None
    for i in by_frame.get(fd + 1, []):
        db = (x1[i], y1[i], x2[i], y2[i])
        # candidate = detection nearest the track's last centre, moving right
        d = abs((db[0]+db[2])/2 - last[2]) + abs(db[3] - lb[3])
        if (db[0]+db[2])/2 >= last[2] - 5 and (best is None or d < best[0]): best = (d, i, db)
    if best is None or best[0] > 1.5 * last[4]: cls["no detection next frame near the track"] += 1; continue
    i, db = best[1], best[2]; v = iou(lb, db); s = float(cf[i]); r = (db[2]-db[0]) / max(1, last[4])
    ious.append(v); confs.append(s); ratios.append(r)
    if s < 0.25 and v < 0.5: cls["conf<0.25 and IoU<0.5: low-score stage refuses (scale)"] += 1
    elif s < 0.25: cls["conf<0.25, IoU>=0.5: low-score stage should match"] += 1
    elif v * s < 0.2: cls["conf>=0.25 but IoU*conf<0.2: fused score refuses"] += 1
    elif v < 0.2: cls["conf>=0.25, IoU<0.2: geometry refuses"] += 1
    else: cls["conf>=0.25, IoU>=0.2, fused>=0.2: should have matched"] += 1
print(f"cam4 {VARIANT}: {len(cov)} covering tracks; life median {np.median(life):.0f} pts")
for k, n in cls.most_common(): print(f"  {n:5}  {k}")
if ious: print(f"  next-frame IoU median {np.median(ious):.2f}, conf median {np.median(confs):.2f}, width ratio median {np.median(ratios):.2f}")
