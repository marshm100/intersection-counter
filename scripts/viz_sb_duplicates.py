"""Visual gate for the SB-through overcount: are OC-SORT's extra SB-through
track-IDs DUPLICATES of one vehicle, or distinct vehicles?

For each flagged overlapping-duplicate pair (two SB-through track-IDs co-located
within `sep` px over >= `ovl` shared frames), render the video frame at the
overlap midpoint with:
  - both tracks' full polylines (red / blue),
  - each track's bbox AT that frame (red / blue),
  - the RAW cached YOLO detections at that frame (yellow).
If two track-boxes sit on ONE yellow detection => proven duplicate ID (one car,
two tracks). Two boxes on two separate detections => two real vehicles.

Outputs a montage to screenshots/. Usage:  py scripts/viz_sb_duplicates.py
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import (
    DetectionCacheReader, compute_video_content_hash, parquet_path, DEFAULT_VARIANT,
)
from backend.services.tracker import create_tracker_backend


def is_sb_through(pts):
    if len(pts) < 5:
        return False
    x0, y0 = pts[0][1], pts[0][2]
    x1, y1 = pts[-1][1], pts[-1][2]
    ys = [p[2] for p in pts]
    return (x1 < x0 - 120) and (abs(y1 - y0) < 80) and (180 <= np.median(ys) <= 275)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--activation", type=float, default=0.25)
    ap.add_argument("--sep", type=float, default=35.0)
    ap.add_argument("--ovl", type=int, default=5)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--out", default="screenshots/sb_duplicates_7am.png")
    args = ap.parse_args()

    conn = sqlite3.connect(str(Path("data/projects") / args.project / "project.db"))
    vp = conn.execute("SELECT path,file_size_bytes,total_frames FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
                      (args.camera,)).fetchone()
    conn.close()
    chash, _ = compute_video_content_hash(vp[0], file_size_bytes=vp[1], total_frames=vp[2])
    pq = parquet_path(args.project, args.camera, chash, DEFAULT_VARIANT)
    frames = list(DetectionCacheReader(pq).iter_frames())
    dets_by_frame = {f: [d["bbox"] for d in ds] for f, ds in frames}

    be = create_tracker_backend("ocsort", track_activation_threshold=args.activation)
    trajs = defaultdict(list)   # tid -> [(f, cx, cy, bbox)]
    for fidx, dets in frames:
        for tk in be.update(dets, fidx):
            cx, cy = tk["center"]
            trajs[tk["track_id"]].append((fidx, float(cx), float(cy), list(tk["bbox"])))
    sb = {tid: t for tid, t in trajs.items() if is_sb_through(t)}
    print(f"OC-SORT SB-through tracks: {len(sb)}")

    # find overlapping-duplicate pairs
    items = list(sb.items())
    pairs = []
    for i in range(len(items)):
        ai = {f: (x, y, bb) for f, x, y, bb in items[i][1]}
        for j in range(i + 1, len(items)):
            bj = {f: (x, y, bb) for f, x, y, bb in items[j][1]}
            common = sorted(set(ai) & set(bj))
            if len(common) < args.ovl:
                continue
            seps = [math.hypot(ai[f][0]-bj[f][0], ai[f][1]-bj[f][1]) for f in common]
            if np.median(seps) <= args.sep:
                pairs.append((len(common), float(np.median(seps)), items[i][0], items[j][0], common))
    pairs.sort(key=lambda p: -p[0])
    print(f"overlapping-duplicate pairs (sep<={args.sep}px, overlap>={args.ovl}f): {len(pairs)}")

    cap = cv2.VideoCapture(vp[0])
    tiles = []
    for k, (nov, msep, ta, tb, common) in enumerate(pairs[:args.n]):
        focus = common[len(common) // 2]
        cap.set(cv2.CAP_PROP_POS_FRAMES, focus)
        ok, frame = cap.read()
        if not ok:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # raw detections at focus frame (yellow)
        for bb in dets_by_frame.get(focus, []):
            x1, y1, x2, y2 = map(int, bb)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 1)
        # full polylines + focus-frame boxes
        for tid, col in ((ta, (0, 0, 255)), (tb, (255, 0, 0))):
            pts = np.array([(x, y) for _, x, y, _ in sb[tid]], dtype=np.int32)
            cv2.polylines(frame, [pts], False, col, 2, cv2.LINE_AA)
            box = next((bb for f, x, y, bb in sb[tid] if f == focus), None)
            if box:
                x1, y1, x2, y2 = map(int, box)
                cv2.rectangle(frame, (x1, y1), (x2, y2), col, 2)
        # zoom: crop +/-70px around the two focus boxes' centroid, upscale 5x so
        # the raw yellow detection(s) under the red/blue track boxes are countable.
        boxes = [next((bb for f, x, y, bb in sb[t] if f == focus), None) for t in (ta, tb)]
        cxs = [ (b[0]+b[2])/2 for b in boxes if b ]; cys = [ (b[1]+b[3])/2 for b in boxes if b ]
        cx0 = int(np.mean(cxs)) if cxs else 320; cy0 = int(np.mean(cys)) if cys else 240
        H, W = frame.shape[:2]
        x1 = max(0, cx0-70); y1 = max(0, cy0-70); x2 = min(W, cx0+70); y2 = min(H, cy0+70)
        crop = frame[y1:y2, x1:x2]
        crop = cv2.resize(crop, (crop.shape[1]*5, crop.shape[0]*5), interpolation=cv2.INTER_NEAREST)
        n_dets_near = sum(1 for bb in dets_by_frame.get(focus, [])
                          if x1 <= (bb[0]+bb[2])/2 <= x2 and y1 <= (bb[1]+bb[3])/2 <= y2)
        cv2.putText(crop, f"{ta}(R)/{tb}(B) f={focus} ovl={nov} sep={msep:.0f}px dets_here={n_dets_near}",
                    (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(crop, f"{ta}(R)/{tb}(B) f={focus} ovl={nov} sep={msep:.0f}px dets_here={n_dets_near}",
                    (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(crop)
    cap.release()
    # pad tiles to a common size for the grid
    if tiles:
        mh = max(t.shape[0] for t in tiles); mw = max(t.shape[1] for t in tiles)
        tiles = [cv2.copyMakeBorder(t, 0, mh-t.shape[0], 0, mw-t.shape[1], cv2.BORDER_CONSTANT) for t in tiles]

    if tiles:
        cols = 2
        rows = (len(tiles) + cols - 1) // cols
        h, w = tiles[0].shape[:2]
        grid = np.zeros((rows * h, cols * w, 3), dtype=np.uint8)
        for idx, t in enumerate(tiles):
            r, c = divmod(idx, cols)
            grid[r*h:(r+1)*h, c*w:(c+1)*w] = t
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(args.out, grid)
        print(f"wrote {args.out}  ({cols*w}x{rows*h}, {len(tiles)} duplicate-pair examples)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
