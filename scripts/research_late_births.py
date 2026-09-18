"""Why do confident boxes not start a track? (2026-09-12, late-birth class)

Runs the default tracker in-process over a window's detection cache with the
birth and unconfirmed-death logs on (same input step as run_pass1 for the
default recipe), then, for every yardstick vehicle whose first 0.5 s+ is not
covered by any output track, classifies each of its uncovered confident hits
(conf >= 0.35):
  deferred  - a birth was refused by the stacked-box guard on that frame
  born-died - a track was born on it and removed unconfirmed the next frame
              (with the next box's IoU / centre distance in box widths)
  no-birth  - neither (the box was consumed by another track's match, etc.)
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_late_births.py PROJ CAM VARIANT VEHICLES_JSON
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.tracker import ByteTrackBackend  # noqa: E402


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
    chash, fps, w, h = con.execute("SELECT content_hash, fps, width, height FROM videos WHERE camera_id=?", (cam,)).fetchone()
    pqp = parquet_path(proj, cam, chash, variant)
    meta = json.load(open(pqp.with_suffix(".meta.json")))
    f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
    t = pq.read_table(pqp).to_pandas()
    t = t[(t.frame_idx >= f0) & (t.frame_idx <= f1)]
    by = {int(f): g for f, g in t.groupby("frame_idx")}
    be = ByteTrackBackend(track_activation_threshold=0.25, lost_track_buffer=150,
                          minimum_matching_threshold=0.8, frame_rate=int(fps), frame_size=(w, h),
                          collect_backfill=True)
    bt = be.byte_track
    bt.birth_log, bt.unconfirmed_death_log = [], []
    out = defaultdict(list)     # abs frame -> [tlbr]
    out_obs = defaultdict(list) # abs frame -> [tlbr], observed box where matched this frame
    out_ids = defaultdict(list) # abs frame -> [(id, tlbr)]
    for f in range(f0, f1 + 1):
        g = by.get(f)
        dets = [] if g is None else [
            {"bbox": [float(a), float(b), float(c), float(d)], "confidence": float(s), "class_id": int(k)}
            for a, b, c, d, s, k in zip(g.bbox_x1.values, g.bbox_y1.values, g.bbox_x2.values,
                                        g.bbox_y2.values, g.confidence.values, g.class_id.values)]
        for r in be.update(dets, f):
            out[f].append(tuple(r["bbox"]))
            out_ids[f].append((r["track_id"], tuple(r["bbox"])))
        for r in be.pop_backfill():          # weak-box birth back-fill, at its true frames
            cx, cy = r["center"]; bw, bh = r["bbox_width"], r["bbox_height"]
            bb = (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
            out[r["frame"]].append(bb); out_obs[r["frame"]].append(bb)
            out_ids[r["frame"]].append((r["track_id"], bb))
        # the same tracks, but the box each MATCHED this frame (the observation)
        for tr in bt.tracked_tracks:
            if tr.is_activated and tr.frame_id == bt.frame_id and getattr(tr, "last_obs_tlbr", None) is not None:
                out_obs[f].append(tuple(float(v) for v in tr.last_obs_tlbr))
            elif tr.is_activated:
                out_obs[f].append(tuple(float(v) for v in tr.tlbr))
    births = defaultdict(list); deaths = defaultdict(list)
    for (fi, tid, tb, sc) in bt.birth_log:
        births[f0 + fi - 1].append((tid, tb, sc))
    for (fi, tid, tb, near, ns) in bt.unconfirmed_death_log:
        deaths[f0 + fi - 1].append((tid, tb, near, ns))
    print(f"{proj} cam{cam} {variant}: births {sum(1 for b in bt.birth_log if b[1] >= 0)}, deferred by the stacked guard "
          f"{sum(1 for b in bt.birth_log if b[1] < 0)}, newborns removed unconfirmed {len(bt.unconfirmed_death_log)}")

    veh = json.loads(Path(vfile).read_text())
    half = max(2, int(round(0.5 * fps)))
    for name, src in (("output box (Kalman estimate)", out), ("matched box (observation)", out_obs)):
        n_late = 0; covered_hits = 0; tot_hits = 0
        for v in veh:
            k0 = next((k for k, hh in enumerate(v) if any(iou(tuple(hh[1:5]), ob) >= 0.3 for ob in src.get(int(hh[0]), []))), None)
            if k0 is None or k0 >= half:
                n_late += 1
            for hh in v:
                tot_hits += 1
                covered_hits += any(iou(tuple(hh[1:5]), ob) >= 0.3 for ob in src.get(int(hh[0]), []))
        print(f"  {name}: late or never covered {n_late} of {len(veh)} ({n_late / len(veh):.0%}); "
              f"hits covered >= 0.3 overall {covered_hits / max(1, tot_hits):.1%}")
    cls = Counter(); next_iou = []; next_dist = []; late = 0
    align = Counter(); born_to_out = []
    for v in veh:
        k0 = next((k for k, hh in enumerate(v) if any(iou(tuple(hh[1:5]), ob) >= 0.3 for ob in out.get(int(hh[0]), []))), None)
        if k0 is None or k0 < half:
            continue
        late += 1
        seen = Counter()
        for hh in v[:k0]:
            f, box, sc = int(hh[0]), tuple(hh[1:5]), hh[5]
            if sc < 0.35:
                continue
            bs = [b for b in births.get(f, []) if iou(b[1], box) >= 0.5]
            if any(b[0] < 0 for b in bs):
                seen["deferred by the stacked guard"] += 1
            elif bs:
                tid = next(b[0] for b in bs if b[0] >= 0)
                d = [x for x in deaths.get(f + 1, []) if x[0] == tid]
                if d:
                    seen["born, removed unconfirmed next frame"] += 1
                    _, tb, near, ns = d[0]
                    if near is not None:
                        next_iou.append(iou(tb, near))
                        cw = max(1.0, tb[2] - tb[0])
                        next_dist.append(np.hypot((near[0] + near[2]) / 2 - (tb[0] + tb[2]) / 2,
                                                  (near[1] + near[3]) / 2 - (tb[1] + tb[3]) / 2) / cw)
                else:
                    seen["born, then something else"] += 1
            else:
                seen["no birth attempted (box used elsewhere)"] += 1
        top = seen.most_common(1)[0][0] if seen else "only weak boxes"
        cls[top] += 1
        # how well do the output boxes line up with the car over the uncovered span?
        for hh in v[:k0]:
            obs = out.get(int(hh[0]), [])
            best = max((iou(tuple(hh[1:5]), ob) for ob in obs), default=0.0)
            align["0" if best <= 0 else ("(0, 0.1]" if best <= 0.1 else "(0.1, 0.3)")] += 1
        # the id born on it: when does it first appear in the output, and how aligned then?
        for hh in v[:k0]:
            bs = [b for b in births.get(int(hh[0]), []) if b[0] >= 0 and iou(b[1], tuple(hh[1:5])) >= 0.5]
            if bs:
                first_out = None
                for k in range(k0 + 1):
                    ff = int(v[k][0])
                    if ff < int(hh[0]):
                        continue
                    if any(iou(ob, tuple(v[k][1:5])) >= 0.1 for ob in out.get(ff, [])):
                        first_out = ff - int(hh[0]); break
                born_to_out.append(first_out if first_out is not None else -1)
                break
    # frame-by-frame trace of a few late-born vehicles
    import os
    n_trace = int(os.environ.get("TRACE_N", "0"))
    traced = 0
    for vi, v in enumerate(veh):
        if traced >= n_trace:
            break
        k0 = next((k for k, hh in enumerate(v) if any(iou(tuple(hh[1:5]), ob) >= 0.3 for ob in out.get(int(hh[0]), []))), None)
        if k0 is None or k0 < half or vi % 97:
            continue
        traced += 1
        print(f"  TRACE vehicle {vi}: {len(v)} hits, first covered at hit {k0}")
        for k in range(min(len(v), k0 + 3)):
            f, box, sc = int(v[k][0]), tuple(v[k][1:5]), v[k][5]
            near = sorted(((iou(box, ob), tid, ob) for tid, ob in out_ids.get(f, [])), reverse=True)[:2]
            bs = [(b[0], round(iou(b[1], box), 2)) for b in births.get(f, []) if iou(b[1], box) > 0]
            ds = [(d[0]) for d in deaths.get(f, []) if iou(d[1], box) > 0]
            print(f"    f{f} box x{box[0]:.0f}-{box[2]:.0f} y{box[1]:.0f}-{box[3]:.0f} w{box[2]-box[0]:.0f} conf {sc:.2f} | "
                  f"output near: {[(tid, round(o, 2), [round(x) for x in ob]) for o, tid, ob in near]} | born {bs} | died-unconfirmed {ds}")
    print(f"  late-born vehicles: {late}; dominant reason per vehicle:")
    for k, n in cls.most_common():
        print(f"    {n:5}  {k}")
    tot = sum(align.values())
    print("  uncovered hits of late-born vehicles, best overlap with ANY output box: " +
          "  ".join(f"{k}: {n} ({n / max(1, tot):.0%})" for k, n in sorted(align.items())))
    bo = np.asarray(born_to_out)
    if len(bo):
        print(f"  frames from the birth on the car to the first output box overlapping it >= 0.1: "
              f"median {np.median(bo[bo >= 0]) if (bo >= 0).any() else -1:.0f}; never within the span: {(bo < 0).sum()} of {len(bo)}")
    if next_iou:
        ni = np.asarray(next_iou); nd = np.asarray(next_dist)
        print(f"  newborns removed unconfirmed: next leftover box IoU median {np.median(ni):.2f} (share 0: {(ni <= 0).mean():.0%}), "
              f"centre distance median {np.median(nd):.2f} box widths (share < 0.9: {(nd < 0.9).mean():.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
