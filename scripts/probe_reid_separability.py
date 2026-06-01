"""Stage 0 ReID go/no-go: is an appearance embedding DISCRIMINATIVE at this scene's
20-40px vehicle size? (docs/reid_project_plan_2026-06-01.md)

If ReID can't tell "same car next frame" from "different car same minute" at this
resolution, the whole ReID project is dead — so measure that FIRST, cheaply, before
any tracker integration.

Method:
  1. Greedy-link cached detections with a TIGHT gate -> high-purity same-vehicle
     sequences (trusted positives).
  2. Decode the REAL video, crop each (frame,bbox), embed with osnet_x0_25.
  3. SAME pairs = consecutive-frame embeddings within a track. DIFFERENT pairs =
     embeddings of distinct tracks CO-PRESENT in the same frame (hard negatives:
     identical lighting/time — the realistic confuser).
  4. Per bbox-size bucket (20-30 / 30-40 / >40 px), report cosine-distance medians
     and the same-vs-different ROC-AUC.

GATE (per the plan): AUC >= ~0.85 in 30-40px AND >= ~0.75 in 20-30px -> proceed.
Below -> STOP, ReID signal too weak here.

Usage:  py scripts/probe_reid_separability.py --max-tracks 250
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
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path)
from detection_vs_tracking_probe import link_detections
from groundtruth import VIDEO_START


def _auc(pos, neg):
    """Mann-Whitney ROC-AUC: P(score(same) > score(diff)). score = similarity."""
    if not pos or not neg:
        return float("nan")
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    rank = 0.0
    i = 0
    n = len(allv)
    ranks = [0.0] * n
    while i < n:
        j = i
        while j < n and allv[j][0] == allv[i][0]:
            j += 1
        r = (i + 1 + j) / 2.0           # average rank for ties (1-based)
        for k in range(i, j):
            ranks[k] = r
        i = j
    sum_pos = sum(ranks[k] for k in range(n) if allv[k][1] == 1)
    np_, nn = len(pos), len(neg)
    return (sum_pos - np_ * (np_ + 1) / 2.0) / (np_ * nn)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate-px", type=float, default=22.0, help="tight greedy gate (high purity)")
    ap.add_argument("--max-gap", type=int, default=3)
    ap.add_argument("--min-pts", type=int, default=5)
    ap.add_argument("--max-tracks", type=int, default=250)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--max-neg", type=int, default=20000)
    args = ap.parse_args()

    conn = sqlite3.connect("data/projects/97a7849a/project.db")
    v = conn.execute("SELECT path,file_size_bytes,total_frames,fps FROM videos "
                     "WHERE camera_id=1 ORDER BY sort_order LIMIT 1").fetchone()
    conn.close()
    vpath, fsize, total_frames, fps = v[0], v[1], v[2], float(v[3])
    ch, _ = compute_video_content_hash(vpath, file_size_bytes=fsize, total_frames=total_frames)
    pq = parquet_path("97a7849a", 1, ch, DEFAULT_VARIANT)

    # window in ABSOLUTE video frames
    from datetime import datetime
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    start_sec = (t0 - VIDEO_START).total_seconds()
    f_lo = int(start_sec * fps)
    f_hi = f_lo + int(args.minutes * 60 * fps)

    # --- build per-frame centers (+ center->bbox map), vehicles only, in window ---
    by_frame = {}
    bbox_of = {}   # (frame, (cx,cy)) -> bbox
    for fidx, dets in DetectionCacheReader(pq).iter_frames():
        if fidx < f_lo or fidx >= f_hi:
            continue
        pts = []
        for d in dets:
            if not d.get("is_vehicle"):
                continue
            cx, cy = d["center"]
            pts.append((cx, cy))
            bbox_of[(fidx, (cx, cy))] = d["bbox"]
        if pts:
            by_frame[fidx] = pts
    print(f"window frames {f_lo}-{f_hi}  ({len(by_frame)} frames with vehicles)")

    tracks = link_detections(by_frame, gate_px=args.gate_px, max_gap=args.max_gap)
    tracks = [t for t in tracks if len(t["pts"]) >= args.min_pts]
    tracks.sort(key=lambda t: -len(t["pts"]))
    tracks = tracks[:args.max_tracks]
    print(f"high-purity tracks (gate={args.gate_px}px, >={args.min_pts}pts): {len(tracks)}")

    # collect needed crops: frame -> [(tid, bbox), ...]
    need = defaultdict(list)
    for tid, t in enumerate(tracks):
        for (cx, cy), f in zip(t["pts"], t["frames"]):
            bb = bbox_of.get((f, (cx, cy)))
            if bb is not None:
                need[f].append((tid, bb))
    n_needed_frames = len(need)
    print(f"decoding {n_needed_frames} frames for crops...")

    # --- decode video, embed crops ---
    from boxmot.reid.core.reid import ReID
    reid = ReID(weights="osnet_x0_25_msmt17.pt", device=args.device)
    model = reid.model

    cap = cv2.VideoCapture(vpath)
    cap.set(cv2.CAP_PROP_POS_FRAMES, min(need) if need else f_lo)
    # embeddings: list per detection of (tid, frame, width, emb)
    emb_by_track = defaultdict(list)   # tid -> list of (frame, width, emb)
    emb_by_frame = defaultdict(list)   # frame -> list of (tid, width, emb)
    decoded = 0
    while need:
        ret, img = cap.read()
        if not ret:
            break
        actual = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if actual > max(need):
            break
        items = need.pop(actual, None)
        if not items:
            continue
        boxes = np.array([bb for _, bb in items], dtype=np.float32)
        feats = np.asarray(model.get_features(boxes, img), dtype=np.float32)
        feats /= (np.linalg.norm(feats, axis=1, keepdims=True) + 1e-9)
        for (tid, bb), emb in zip(items, feats):
            w = bb[2] - bb[0]
            emb_by_track[tid].append((actual, w, emb))
            emb_by_frame[actual].append((tid, w, emb))
        decoded += 1
    cap.release()
    print(f"embedded crops over {decoded} frames")

    def bucket(w):
        if w < 30: return "20-30px"
        if w < 40: return "30-40px"
        return ">40px"

    # SAME pairs: consecutive-frame within a track (easy positive, upper bound)
    same = defaultdict(list)   # bucket -> [similarity]
    # SAME-GAP pairs: within a track but GAP_LO..GAP_HI frames apart — the REALISTIC
    # re-association case (the turn coast / occlusion gap ReID must bridge).
    same_gap = defaultdict(list)
    GAP_LO, GAP_HI = 5, 15
    for tid, seq in emb_by_track.items():
        seq.sort()
        for a, b in zip(seq, seq[1:]):
            sim = float(np.dot(a[2], b[2]))
            same[bucket(min(a[1], b[1]))].append(sim)
        for i in range(len(seq)):
            for j in range(i + 1, len(seq)):
                gap = seq[j][0] - seq[i][0]
                if gap < GAP_LO:
                    continue
                if gap > GAP_HI:
                    break
                same_gap[bucket(min(seq[i][1], seq[j][1]))].append(
                    float(np.dot(seq[i][2], seq[j][2])))
    # DIFFERENT pairs: distinct tracks co-present in same frame (hard negatives)
    diff = defaultdict(list)
    rng = np.random.default_rng(0)
    n_diff = 0
    for f, items in emb_by_frame.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if items[i][0] == items[j][0]:
                    continue
                sim = float(np.dot(items[i][2], items[j][2]))
                diff[bucket(min(items[i][1], items[j][1]))].append(sim)
                n_diff += 1
        if n_diff > args.max_neg:
            break

    def table(title, pos):
        print(f"\n{title}")
        print(f"{'bucket':<10}{'pos_n':>8}{'diff_n':>8}{'pos_med':>9}{'diff_med':>10}{'AUC':>8}")
        res = {}
        op, od = [], []
        for b in ("20-30px", "30-40px", ">40px"):
            s, d = pos.get(b, []), diff.get(b, [])
            op += s; od += d
            auc = _auc(s, d); res[b] = auc
            sm = float(np.median(s)) if s else float("nan")
            dm = float(np.median(d)) if d else float("nan")
            print(f"{b:<10}{len(s):>8}{len(d):>8}{sm:>9.3f}{dm:>10.3f}{auc:>8.3f}")
        print(f"{'ALL':<10}{len(op):>8}{len(od):>8}"
              f"{(np.median(op) if op else float('nan')):>9.3f}"
              f"{(np.median(od) if od else float('nan')):>10.3f}{_auc(op, od):>8.3f}")
        return res

    table("=== SAME = consecutive frame (easy positive / upper bound) ===", same)
    res_gap = table(f"=== SAME = {GAP_LO}-{GAP_HI}-frame gap (REALISTIC re-association) ===", same_gap)

    # --- GATE verdict (judged on the REALISTIC cross-gap case) ---
    print("\n=== GATE (plan: 30-40px AUC>=0.85 AND 20-30px AUC>=0.75, on cross-gap) ===")
    a30 = res_gap.get("30-40px", float("nan"))
    a20 = res_gap.get("20-30px", float("nan"))
    print(f"  cross-gap 30-40px AUC = {a30:.3f}   20-30px AUC = {a20:.3f}")
    go = (a30 >= 0.85 and a20 >= 0.75)
    print(f"  VERDICT: {'GO — appearance discriminative across gaps, proceed to Stage 1' if go else 'NO-GO / MARGINAL — ReID signal weak at this resolution'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
