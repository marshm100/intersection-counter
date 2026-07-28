"""SPIKE — ReID twin test (docs/spike_reid_twin_2026-07-28.md).

Question: do ReID appearance embeddings (osnet_x0_25, the shipped cam1
machinery, byte-identical call path) separate CONCURRENT-TWIN track pairs
(one vehicle, two tracks) from REAL-NEIGHBOR pairs at cam5's compressed
far band — where image-space geometry twice failed (2026-07-09,
lane+echo iteration 2)?

Populations (cam5 study_0700, event-carrying tracks):
  seq   — sequential direction-gated chain edges = SAME vehicle
          (calibration positive; conservative, tag-gated chaining).
  far   — co-temporal pairs at 150–400 px mean distance = DIFFERENT
          vehicles (calibration negative).
  near  — co-temporal pairs within 60 px that FAIL the CD twin test =
          the hard negative class (followers / adjacent-lane).
  twin? — the CD-caught pairs (IoU>=0.30 + lockstep<=10 for >=1 s) =
          the population to PLACE against the calibrated classes.

Anti-confound: overlapping boxes share pixels, so shared-frame crops are
trivially similar. Each track is embedded at up to 4 CLEAN frames —
outside co-life, or where the partner's same-frame box has IoU < 0.05 —
and a pair with no clean frames on either side is scored but flagged
(`clean=False`). Similarity = cosine of per-track mean embeddings over
clean frames.

Decision gate (declared in the spike doc before results): proceed to a
mechanism plan iff seq-vs-near separate at AUC >= 0.85 on clean-frame
similarity AND the twin? population places interpretably against the
calibrated classes. Evidence -> runs/cam5_wall/spike_reid_twin.json.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
import time as _clock
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.entry_gates import classify
from backend.services.track_chains import _end_speed
import lane_echo_phase0 as CE
from lane_echo_e_arm import chain_tracks_dirgated
from lane_echo_compound import _cd_same_vehicle, _iou

PROJECT = "97a7849a"
CAM = 5
WINDOW = "study_0700"
SCRATCH = Path(f"data/projects/{PROJECT}/_replay_scratch")
OUT = Path("runs/cam5_wall/spike_reid_twin.json")
N_PER_POP = 120
FRAMES_PER_TRACK = 4
CLEAN_IOU_MAX = 0.05
NEAR_MAX_DIST = 60.0
FAR_RANGE = (150.0, 400.0)
WEIGHTS = "osnet_x0_25_msmt17.pt"


def _pair_life(boxes_a, boxes_b):
    shared = sorted(set(boxes_a) & set(boxes_b))
    if not shared:
        return None
    ds = [math.hypot(boxes_a[f][0] - boxes_b[f][0],
                     boxes_a[f][1] - boxes_b[f][1]) for f in shared]
    return shared, sum(ds) / len(ds)


def _clean_frames(tid, other, boxes, k=FRAMES_PER_TRACK):
    """Frames for `tid` where `other`'s same-frame box (if any) has
    IoU < CLEAN_IOU_MAX with tid's — prefer frames outside co-life."""
    mine = boxes[tid]
    theirs = boxes.get(other, {})
    outside = [f for f in mine if f not in theirs]
    weak = [f for f in mine if f in theirs
            and _iou(mine[f], theirs[f]) < CLEAN_IOU_MAX]
    pool = outside + weak
    if not pool:
        return [], False
    pool = sorted(pool)
    step = max(1, len(pool) // k)
    return pool[::step][:k], True


def main() -> int:
    rows, fps = CE.load_rows(PROJECT, CAM, WINDOW)
    gates, _ = CE.pinned_gates(PROJECT, CAM)
    tracks: dict[int, list] = {}
    boxes: dict[int, dict] = defaultdict(dict)
    for r in rows:
        tid = int(r[0])
        tracks.setdefault(tid, []).append((float(r[1]), float(r[2]), float(r[3])))
        if len(r) >= 8:
            boxes[tid][int(r[1])] = (float(r[2]), float(r[3]),
                                     float(r[4]), float(r[5]))
    recs, tags = [], {}
    for tid, pts in tracks.items():
        pts = sorted(pts)
        if len(pts) < 5:
            continue
        _o, _d, *_rest, tag = classify(pts, gates, fps)
        tags[tid] = tag
        recs.append({"tid": tid, "birth": (pts[0][0], pts[0][1], pts[0][2]),
                     "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
                     "tag": tag, "v_end": _end_speed(pts),
                     "bearing": CE._bearing(pts)})
    chains, _cut = chain_tracks_dirgated(recs, fps)

    db = SCRATCH / f"cam5wall_stock_{WINDOW}.db"
    ev_tids = set()
    c = sqlite3.connect(str(db))
    for (tid,) in c.execute(
            "SELECT DISTINCT vehicle_track_id FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0", (CAM,)):
        ev_tids.add(tid)
    c.close()
    ev_tids = {t for t in ev_tids if t in boxes}
    print(f"[S] tracks={len(tracks)} event-tracks={len(ev_tids)}", flush=True)

    # --- populations ------------------------------------------------------
    pairs = {"seq": [], "far": [], "near": [], "twin": []}
    for ch in chains:
        for a, b in zip(ch, ch[1:]):
            if a["tid"] in boxes and b["tid"] in boxes:
                pairs["seq"].append((a["tid"], b["tid"]))

    ev_list = sorted(ev_tids)
    spans = {t: (min(boxes[t]), max(boxes[t])) for t in ev_list}
    mpos = {t: (sum(b[0] for b in boxes[t].values()) / len(boxes[t]),
                sum(b[1] for b in boxes[t].values()) / len(boxes[t]))
            for t in ev_list}
    need_s = int(1.0 * fps)
    for i in range(len(ev_list)):
        for j in range(i + 1, len(ev_list)):
            a, b = ev_list[i], ev_list[j]
            if spans[a][1] < spans[b][0] or spans[b][1] < spans[a][0]:
                continue
            if math.hypot(mpos[a][0] - mpos[b][0],
                          mpos[a][1] - mpos[b][1]) > 450:
                continue
            life = _pair_life(boxes[a], boxes[b])
            if life is None or len(life[0]) < need_s:
                continue
            _, mean_d = life
            if mean_d <= NEAR_MAX_DIST:
                if _cd_same_vehicle(boxes[a], boxes[b], fps, 0.30, 10.0):
                    pairs["twin"].append((a, b))
                else:
                    pairs["near"].append((a, b))
            elif FAR_RANGE[0] <= mean_d <= FAR_RANGE[1]:
                pairs["far"].append((a, b))
    import random
    rng = random.Random(97)
    for k in pairs:
        if len(pairs[k]) > N_PER_POP:
            pairs[k] = rng.sample(pairs[k], N_PER_POP)
    print(f"[S] pairs: { {k: len(v) for k, v in pairs.items()} }", flush=True)

    # --- frame plan + decode + embed -------------------------------------
    plan = defaultdict(list)          # frame -> [(tid, xyxy)]
    pair_frames = {}
    for pop, plist in pairs.items():
        for (a, b) in plist:
            fa, ca = _clean_frames(a, b, boxes)
            fb, cb = _clean_frames(b, a, boxes)
            pair_frames[(a, b)] = (fa, fb, ca and cb)
            for tid, fl in ((a, fa), (b, fb)):
                for f in fl:
                    cx, cy, bw, bh = boxes[tid][f]
                    plan[f].append((tid, (cx - bw / 2, cy - bh / 2,
                                          cx + bw / 2, cy + bh / 2)))
    frames_needed = sorted(plan)
    print(f"[S] unique frames to decode: {len(frames_needed)}", flush=True)

    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    vpath = conn.execute(
        "SELECT path FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (CAM,)).fetchone()[0]
    conn.close()

    from boxmot.reid.core.reid import ReID
    model = ReID(weights=WEIGHTS, device="cpu").model
    embs: dict[tuple, np.ndarray] = {}    # (tid, frame) -> 512
    cap = cv2.VideoCapture(vpath)
    t0 = _clock.time()
    for n, f in enumerate(frames_needed):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, img = cap.read()
        if not ok:
            continue
        entries = plan[f]
        bbs = np.array([e[1] for e in entries], dtype=np.float32)
        feats = model.get_features(bbs, img)
        for (tid, _), v in zip(entries, feats):
            embs[(tid, f)] = np.asarray(v, dtype=np.float32)
        if n % 200 == 0:
            print(f"[S] embed {n}/{len(frames_needed)} "
                  f"({_clock.time() - t0:.0f}s)", flush=True)
    cap.release()
    print(f"[S] embedded {len(embs)} crops ({_clock.time() - t0:.0f}s)",
          flush=True)

    def track_mean(tid, fl):
        vs = [embs[(tid, f)] for f in fl if (tid, f) in embs]
        if not vs:
            return None
        m = np.mean(vs, axis=0)
        n = np.linalg.norm(m)
        return m / n if n > 0 else None

    sims = {k: [] for k in pairs}
    flagged = {k: 0 for k in pairs}
    for pop, plist in pairs.items():
        for (a, b) in plist:
            fa, fb, clean = pair_frames[(a, b)]
            va, vb = track_mean(a, fa), track_mean(b, fb)
            if va is None or vb is None:
                continue
            sims[pop].append(float(np.dot(va, vb)))
            if not clean:
                flagged[pop] += 1

    def q(xs):
        if not xs:
            return []
        s = sorted(xs)
        n = len(s)
        return [round(s[0], 3), round(s[n // 4], 3), round(s[n // 2], 3),
                round(s[3 * n // 4], 3), round(s[-1], 3)]

    # AUC seq (positive) vs near (hard negative)
    pos, neg = sims["seq"], sims["near"]
    auc = None
    if pos and neg:
        wins = sum(1 for p in pos for m in neg if p > m) + \
            0.5 * sum(1 for p in pos for m in neg if p == m)
        auc = round(wins / (len(pos) * len(neg)), 3)

    med_seq = sorted(sims["seq"])[len(sims["seq"]) // 2] if sims["seq"] else None
    med_near = sorted(sims["near"])[len(sims["near"]) // 2] if sims["near"] else None
    twin_hi = twin_lo = None
    if sims["twin"] and med_seq is not None and med_near is not None:
        mid = (med_seq + med_near) / 2
        twin_hi = sum(1 for s in sims["twin"] if s >= mid)
        twin_lo = len(sims["twin"]) - twin_hi

    result = {
        "window": WINDOW, "n_pairs_scored": {k: len(v) for k, v in sims.items()},
        "no_clean_frames_flagged": flagged,
        "similarity_quartiles": {k: q(v) for k, v in sims.items()},
        "auc_seq_vs_near": auc,
        "twin_split_at_midpoint": {"same_vehicle_side": twin_hi,
                                   "different_vehicle_side": twin_lo},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    for k in ("seq", "far", "near", "twin"):
        print(f"[S] {k:>5}: n={len(sims[k])} flagged={flagged[k]} "
              f"q={q(sims[k])}", flush=True)
    print(f"[S] AUC seq-vs-near = {auc}", flush=True)
    print(f"[S] twin split at midpoint: {twin_hi} same-side / {twin_lo} "
          f"different-side", flush=True)
    print(f"wrote {OUT}", flush=True)
    print("SPIKE DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
