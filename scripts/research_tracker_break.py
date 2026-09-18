"""Why does the tracker break the near-lane vehicle? (operator ask 2026-09-12)

Ground truth for "one vehicle" = a detection chain entering over the bottom
edge and reaching x=550 (probe_cam4_nb_emergence). Subcommands:
  extract  VARIANT      save those vehicles' full detection sequences
                        (frame, x1,y1,x2,y2, conf) -> runs/v2_week1/vehicles_<variant>.json
  timeline VARIANT      per vehicle: which dump track covers each detection;
                        ids per vehicle, first-track delay, gaps; at every
                        track break the tracker's OWN box vs the real detection
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_tracker_break.py CMD VARIANT
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

PROJ, CAM = "97a7849a", 4
FRAME_W, FRAME_H = 640, 480


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def _load(variant):
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (CAM,)).fetchone()
    pqp = parquet_path(PROJ, CAM, chash, variant)
    meta = json.load(open(pqp.with_suffix(".meta.json")))
    f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
    return pqp, f0, f1, fps


def base_variant(variant: str) -> str:
    """cr_l1_study_0700 -> l1_study_0700 for FM51 (its base is l1_), study_* elsewhere."""
    tail = variant.split("study_")[-1]
    return ("l1_study_" if "_l1_study_" in variant or variant.startswith("l1_study_") else "study_") + tail


def extract(variant):
    from probe_cam4_nb_emergence import XFAR, XNEAR, dedup, link
    pqp, f0, f1, fps = _load(variant)
    t = pq.read_table(pqp).to_pandas()
    fr = t.frame_idx.values; x1 = t.bbox_x1.values; y1 = t.bbox_y1.values
    x2 = t.bbox_x2.values; y2 = t.bbox_y2.values; cf = t.confidence.values
    keep = dedup(fr, x1, y1, x2, y2, cf) & (cf >= 0.10) & (fr >= f0) & (fr <= f1)
    idx = np.flatnonzero(keep); idx = idx[np.argsort(fr[idx], kind="stable")]
    chains = link(fr[idx], ((x1 + x2) / 2)[idx], y2[idx], (x2 - x1)[idx], cf[idx], f0, f1)
    out = []
    for tk in chains:
        xs = np.asarray(tk["xs"])
        if xs[-1] - xs[0] >= 40 and ((xs[:-1] < XFAR) & (xs[1:] >= XFAR)).any() and xs[0] > XNEAR:
            g = [int(idx[i]) for i in tk["ix"]]
            out.append([[int(fr[i]), float(x1[i]), float(y1[i]), float(x2[i]), float(y2[i]), float(cf[i])] for i in g])
    p = Path(f"runs/v2_week1/vehicles_{variant}.json")
    p.write_text(json.dumps(out))
    print(f"{len(out)} bottom-edge vehicles saved -> {p}; hits median {np.median([len(v) for v in out]):.0f}")


def extract_all(variant, proj=PROJ, cam=CAM):
    """Generic yardstick for ANY window: every deduped chain with >= 15 hits and
    >= 120 px of net travel is one moving vehicle. Saves
    runs/v2_week1/vehicles_all_<proj>_<cam>_<variant>.json."""
    from probe_cam4_nb_emergence import dedup, link
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
    pqp = parquet_path(proj, cam, chash, variant)
    meta = json.load(open(pqp.with_suffix(".meta.json")))
    f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
    t = pq.read_table(pqp).to_pandas()
    fr = t.frame_idx.values; x1 = t.bbox_x1.values; y1 = t.bbox_y1.values
    x2 = t.bbox_x2.values; y2 = t.bbox_y2.values; cf = t.confidence.values
    keep = dedup(fr, x1, y1, x2, y2, cf) & (cf >= 0.10) & (fr >= f0) & (fr <= f1)
    idx = np.flatnonzero(keep); idx = idx[np.argsort(fr[idx], kind="stable")]
    chains = link(fr[idx], ((x1 + x2) / 2)[idx], y2[idx], (x2 - x1)[idx], cf[idx], f0, f1)
    out = []
    for tk in chains:
        if len(tk["xs"]) < 15:
            continue
        travel = float(np.hypot(tk["xs"][-1] - tk["xs"][0], tk["ys"][-1] - tk["ys"][0]))
        if travel < 120:
            continue
        g = [int(idx[i]) for i in tk["ix"]]
        out.append([[int(fr[i]), float(x1[i]), float(y1[i]), float(x2[i]), float(y2[i]), float(cf[i])] for i in g])
    p = Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json")
    p.write_text(json.dumps(out))
    print(f"{len(out)} moving vehicles (chains >= 15 hits, >= 120 px) saved -> {p}; hits median {np.median([len(v) for v in out]):.0f}")


def timeline(variant, proj=PROJ, cam=CAM, generic=False):
    global PROJ, CAM
    PROJ, CAM = proj, cam
    pqp, f0, f1, fps = _load(variant)
    vf = (f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json" if generic
          else f"runs/v2_week1/vehicles_{base_variant(variant)}.json")
    veh = json.loads(Path(vf).read_text())
    rows = np.asarray(load_dump(tracks_dir(pqp)))
    rows = rows[np.argsort(rows[:, 1], kind="stable")]
    ufr, s_ = np.unique(rows[:, 1], return_index=True); e_ = np.append(s_[1:], len(rows))
    fidx = dict(zip(ufr.astype(int), zip(s_, e_)))
    ids_per, delay, gaps, deaths = [], [], [], []
    # per track id: sorted frames (for the hand-off diagnosis)
    tid_frames = {}
    for tid_, grp in zip(*np.unique(rows[:, 0], return_inverse=True)):
        pass
    order_t = np.lexsort((rows[:, 1], rows[:, 0]))
    rt = rows[order_t]
    ut, st_ = np.unique(rt[:, 0], return_index=True); en_ = np.append(st_[1:], len(rt))
    for t_, a_, b_ in zip(ut, st_, en_):
        tid_frames[int(t_)] = rt[a_:b_, 1].astype(int)
    handoff = Counter(); handoff_age = []; stale_examples = []
    for v in veh:
        tl = []
        for (f, a, b, c, d, s) in v:
            det = (a, b, c, d); best = (0.0, None, None)
            ab = fidx.get(f)
            if ab is not None:
                for r in rows[ab[0]:ab[1]]:
                    tb = (r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2)
                    v_ = iou(det, tb)
                    if v_ > best[0]:
                        best = (v_, int(r[0]), tb)
            ok = best[0] >= 0.1
            tl.append((f, det, s, best[1] if ok else None, best[2] if ok else None))
        ids = [x[3] for x in tl if x[3] is not None]
        ids_per.append(len(set(ids)))
        first = next((k for k, x in enumerate(tl) if x[3] is not None), None)
        delay.append(first if first is not None else len(tl))
        for k in range(len(tl) - 1):
            cur, nxt = tl[k], tl[k + 1]
            if cur[3] is not None and nxt[3] != cur[3]:
                tb, det_now, det_next = cur[4], cur[1], nxt[1]
                deaths.append({
                    "x": det_now[2], "touch_bottom": det_now[3] >= FRAME_H - 2,
                    "track_w_over_det_w": (tb[2] - tb[0]) / max(1, det_now[2] - det_now[0]),
                    "track_h_over_det_h": (tb[3] - tb[1]) / max(1, det_now[3] - det_now[1]),
                    "iou_track_vs_next_det": iou(tb, det_next),
                    "iou_det_vs_next_det": iou(det_now, det_next),
                    "next_conf": nxt[2],
                    "w_ratio_next": (det_next[2] - det_next[0]) / max(1, det_now[2] - det_now[0]),
                    "w_now": det_now[2] - det_now[0],
                    "kind": "handoff" if nxt[3] is not None else "gap"})
                if nxt[3] is not None:
                    fr_other = tid_frames.get(nxt[3])
                    if fr_other is not None:
                        if fr_other[0] == nxt[0]:
                            handoff["new id born on the next frame"] += 1
                        else:
                            prev = fr_other[fr_other < nxt[0]]
                            age = int(nxt[0] - prev[-1]) if len(prev) else -1
                            handoff_age.append(age)
                            # twin test: was the other id's box on THIS frame already on top of our vehicle?
                            twin = False
                            ab2 = fidx.get(cur[0])
                            if ab2 is not None:
                                for r in rows[ab2[0]:ab2[1]]:
                                    if int(r[0]) == nxt[3]:
                                        ob = (r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2)
                                        twin = iou(ob, det_now) >= 0.5
                            if twin:
                                handoff["twin (other id already on this vehicle, IoU>=0.5)"] += 1
                                continue
                            own = nxt[3] in {x[3] for x in tl[:k] if x[3] is not None}
                            kind = ("existing id, tracked last frame" if age == 1 else
                                    ("existing id, lost 2-5 frames" if 2 <= age <= 5 else
                                     "existing id, lost > 5 frames"))
                            if age > 1:
                                kind += " [OWN earlier id returns]" if own else " [ANOTHER vehicle's id]"
                                if not own and age > 5:
                                    stale_examples.append((nxt[0], nxt[3], cur[3], age, nxt[1]))
                            handoff[kind] += 1
        run = 0
        for x in tl:
            if x[3] is None:
                run += 1
            elif run:
                gaps.append(run); run = 0
    # never-tracked vehicles: what did the detector give them?
    zero = [v for v, n in zip(veh, ids_per) if n == 0]
    if zero:
        maxc = [max(h[5] for h in v) for v in zero]
        n_hi = [sum(1 for h in v if h[5] >= 0.25) for v in zero]
        n_birth = [sum(1 for h in v if h[5] >= 0.35) for v in zero]
        def longest_run(v, thr):
            best = run_ = 0
            for k in range(len(v)):
                run_ = run_ + 1 if v[k][5] >= thr and (k == 0 or v[k][0] == v[k - 1][0] + 1) else (1 if v[k][5] >= thr else 0)
                best = max(best, run_)
            return best
        runs = [longest_run(v, 0.25) for v in zero]
        hits = [len(v) for v in zero]
        print(f"  NEVER-TRACKED vehicles: {len(zero)}; hits median {np.median(hits):.0f}; max conf median {np.median(maxc):.2f}; "
              f"hits >= 0.25 median {np.median(n_hi):.0f}; hits >= 0.35 (birth bar) median {np.median(n_birth):.0f}; "
              f"longest consecutive run >= 0.25: median {np.median(runs):.0f}, share with run >= 2: {np.mean([r >= 2 for r in runs]):.0%}; "
              f"first box width median {np.median([v[0][3] - v[0][1] for v in zero]):.0f} px")
    print(f"[{variant}] {len(veh)} vehicles")
    print("  track ids per vehicle: " + "  ".join(f"{k}:{n}" for k, n in sorted(Counter(min(i, 5) for i in ids_per).items())) + "   (5 = 5+)")
    print(f"  detections before the first track covers it: median {np.median(delay):.0f}, p75 {np.percentile(delay, 75):.0f}")
    print(f"  untracked gaps inside a vehicle: {len(gaps)}, median length {np.median(gaps) if gaps else 0:.0f} frames")
    d = deaths
    print(f"  track breaks along these vehicles: {len(d)} ({sum(1 for x in d if x['kind'] == 'gap')} into a gap, "
          f"{sum(1 for x in d if x['kind'] == 'handoff')} straight to another id)")

    if handoff:
        print("    hand-offs, who took the vehicle: " + "; ".join(f"{k}: {n}" for k, n in handoff.most_common()))
    if stale_examples:
        ex = Path(f"runs/v2_week1/stale_handoffs_{PROJ}_{CAM}_{variant}.json")
        ex.write_text(json.dumps(stale_examples[:200]))
        ages = [e[3] for e in stale_examples]
        xs = [(e[4][0] + e[4][2]) / 2 for e in stale_examples]; ys = [e[4][3] for e in stale_examples]
        print(f"    stale hand-offs by ANOTHER vehicle's id (lost > 5 f): {len(stale_examples)}; lost age median {np.median(ages):.0f} f; "
              f"where: x median {np.median(xs):.0f}, bottom y median {np.median(ys):.0f}; examples -> {ex}")

    def med(k, sub=d):
        return np.median([x[k] for x in sub]) if sub else 0

    print(f"    at the break: tracker box / real box  width x{med('track_w_over_det_w'):.2f}  height x{med('track_h_over_det_h'):.2f} (median)")
    print(f"    IoU(tracker box, next real box) median {med('iou_track_vs_next_det'):.2f}   vs IoU(real box, next real box) "
          f"{med('iou_det_vs_next_det'):.2f}   next conf {med('next_conf'):.2f}   next/now width {med('w_ratio_next'):.2f}")
    wide = [x for x in d if x["track_w_over_det_w"] > 1.5]
    print(f"    breaks where the tracker's box is >1.5x wider than the real one: {len(wide)} ({len(wide) / max(1, len(d)):.0%}); "
          f"of those, real box touching the bottom edge: {sum(1 for x in wide if x['touch_bottom'])}")
    # which ByteTrack stage refuses the next real box (supervision: stage 1 = IoU x conf >= 0.2 for conf >= 0.25;
    # stage 2 = plain IoU >= 0.5 for 0.1 <= conf < 0.25; a box under 0.25 can never start a track)
    stage = Counter()
    for x in d:
        v, c = x["iou_track_vs_next_det"], x["next_conf"]
        if c >= 0.25:
            stage["conf>=0.25, fused IoU*conf < 0.2 (stage-1 refuses)" if v * c < 0.2 else "conf>=0.25, fused >= 0.2 (should match; taken by another id)"] += 1
        else:
            stage["conf<0.25, IoU < 0.5 (stage-2 refuses; and cannot re-birth)" if v < 0.5 else "conf<0.25, IoU >= 0.5 (stage 2 should match)"] += 1
    print("    the next real box at the break, by tracker stage:")
    for k, n in stage.most_common():
        print(f"      {n:5}  {k}")
    far = [x for x in d if x["x"] >= 550]
    print(f"    breaks at x>=550: {len(far)}; their next conf median {med('next_conf', far):.2f}; share with next conf < 0.25: "
          f"{sum(1 for x in far if x['next_conf'] < 0.25) / max(1, len(far)):.0%}; real-box width at those breaks median "
          f"{np.median([x['w_now'] for x in far]) if far and 'w_now' in far[0] else 0:.0f} px")
    xs = [x["x"] for x in d]
    print("    break x: " + "  ".join(f"{lo}-{lo + 50}:{sum(1 for x in xs if lo <= x < lo + 50)}" for lo in range(350, 650, 50)))


if __name__ == "__main__":
    cmd, variant = sys.argv[1], sys.argv[2]
    proj = sys.argv[3] if len(sys.argv) > 3 else PROJ
    cam = int(sys.argv[4]) if len(sys.argv) > 4 else CAM
    if cmd == "extract":
        extract(variant)
    elif cmd == "extract_all":
        extract_all(variant, proj, cam)
    elif cmd == "timeline":
        timeline(variant)
    elif cmd == "timeline_all":
        timeline(variant, proj, cam, generic=True)
