"""Twins: two tracker ids on one vehicle at the same time (the double-box class
named by the miss log, 2026-09-19; operator: "lets do that" - measure first).

Truth for "one vehicle" = a yardstick chain (research_tracker_break extract_all).
Every hit of every chain is labelled with ALL dump ids whose box overlaps it by
IoU >= LABEL_IOU (not just the best one). A TWIN SPAN = two ids both on the same
chain for >= MIN_RUN consecutive hits. For each span the YOUNGER id (born later;
its birth = its first non-back-filled row) is the newborn and the OLDER is the
holder, and the record says HOW the twin was born:
  holder state at the birth frame: on the vehicle (a row that frame) / lost k
    frames (its last row k frames before) / absent (> LOST_MAX frames)
  the geometry at birth: IoU(newborn box, holder box), coverage of the newborn
    inside the holder and of the holder inside the newborn, width ratio, the
    centre offset in holder widths (stacked vs side-by-side), the newborn's conf
    and class vs the holder's class
  the twin's life: frames both on the chain, which id the chain ends with
    (the survivor), where (x band)
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_twins.py PROJ CAM VARIANT
Writes runs/v2_week1/twins_<proj>_<cam>_<variant>.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from research_tracker_break import base_variant  # noqa: E402
from research_thefts import iou_mat, tlbr  # noqa: E402

LABEL_IOU = 0.3
MIN_RUN = 5
LOST_MAX = 50


def coverage(a, b):
    """share of box a inside box b."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))


def main() -> int:
    proj, cam, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    d = tracks_dir(parquet_path(proj, cam, chash, variant))
    rows = np.asarray(load_dump(d), dtype=np.float64)
    rows = rows[np.argsort(rows[:, 1], kind="stable")]
    ufr, s_ = np.unique(rows[:, 1], return_index=True)
    e_ = np.append(s_[1:], len(rows))
    fidx = dict(zip(ufr.astype(int), zip(s_, e_)))
    by_id = defaultdict(dict)          # id -> {frame: row}
    for r in rows:
        by_id[int(r[0])][int(r[1])] = r
    backfill = set()
    bf = d / "backfill.npy"
    if bf.exists():
        backfill = {(int(r[0]), int(r[1])) for r in np.load(bf)}
    birth = {}
    for tid, fr in by_id.items():
        live = [f for f in fr if (tid, f) not in backfill]
        birth[tid] = min(live) if live else min(fr)
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json").read_text())
    print(f"{proj} cam{cam} {variant}: {len(rows)} dump rows, {len(by_id)} tracks, {len(veh)} yardstick vehicles, "
          f"{len(backfill)} back-fill rows")

    # multi-label every hit
    spans = []
    f_lo, f_hi = float(rows[:, 1].min()) + 60 * fps, float(rows[:, 1].max()) - 60 * fps
    for vi, v in enumerate(veh):
        labels = []                    # per hit: (frame, det, set of ids)
        for h in v:
            f = int(h[0]); det = np.asarray([h[1:5]], dtype=np.float64)
            ab = fidx.get(f)
            ids = set()
            if ab is not None:
                sub = rows[ab[0]:ab[1]]
                m = iou_mat(det, np.stack([tlbr(r) for r in sub]))[0]
                ids = {int(sub[j, 0]) for j in np.nonzero(m >= LABEL_IOU)[0]}
            labels.append((f, h[1:5], ids))
        # runs of pairs
        active: dict = {}              # pair -> [start index, length]
        for k, (f, det, ids) in enumerate(labels + [(None, None, set())]):
            pairs = {tuple(sorted(p)) for p in
                     [(a, b) for a in ids for b in ids if a < b]}
            for p in list(active):
                if p not in pairs:
                    st, n = active.pop(p)
                    if n >= MIN_RUN:
                        spans.append((vi, p, st, k - 1))
            for p in pairs:
                if p in active:
                    active[p][1] += 1
                else:
                    active[p] = [k, 1]
    print(f"  twin spans (two ids on one chain >= {MIN_RUN} consecutive hits): {len(spans)} "
          f"on {len({s[0] for s in spans})} vehicles")

    events = []
    for vi, (a, b), k0, k1 in spans:
        young, old = (a, b) if birth[a] > birth[b] else (b, a)
        if birth[young] == birth[old]:
            kind_birth = "same frame"
        fb = birth[young]
        hits = veh[vi]
        f_first, f_last = int(hits[k0][0]), int(hits[k1][0])
        yb = by_id[young].get(fb)
        if yb is None:
            continue
        ybox = tlbr(yb)
        ob = by_id[old].get(fb)
        prev = [f for f in by_id[old] if f < fb]
        if ob is not None:
            holder = "on the vehicle"; lost_k = 0
            obox = tlbr(ob)
        elif prev and fb - max(prev) <= LOST_MAX:
            lost_k = fb - max(prev); holder = "lost"
            obox = tlbr(by_id[old][max(prev)])
        else:
            holder = "absent"; lost_k = -1
            obox = tlbr(by_id[old][min(by_id[old])])
        ow = max(1.0, obox[2] - obox[0]); yw = max(1.0, ybox[2] - ybox[0])
        off = float(np.hypot((ybox[0] + ybox[2]) / 2 - (obox[0] + obox[2]) / 2,
                             (ybox[1] + ybox[3]) / 2 - (obox[1] + obox[3]) / 2)) / ow
        # the survivor: which id the chain ends with (the last hit labelled with either)
        tail = None
        for h in reversed(hits):
            f = int(h[0]); det = np.asarray([h[1:5]])
            cand = [(t, by_id[t].get(f)) for t in (young, old)]
            cand = [(t, r) for t, r in cand if r is not None]
            if cand:
                m = [float(iou_mat(det, np.asarray([tlbr(r)]))[0, 0]) for _, r in cand]
                if max(m) >= LABEL_IOU:
                    tail = cand[int(np.argmax(m))][0]
                    break
        events.append({"veh": vi, "young": young, "old": old, "birth": fb, "f_first": f_first, "f_last": f_last,
                       "twin_frames": k1 - k0 + 1, "holder": holder, "lost_k": lost_k,
                       "iou": round(float(iou_mat(np.asarray([ybox]), np.asarray([obox]))[0, 0]), 3),
                       "cov_young_in_old": round(coverage(ybox, obox), 3), "cov_old_in_young": round(coverage(obox, ybox), 3),
                       "w_ratio": round(yw / ow, 3), "offset_w": round(off, 3),
                       "conf_young": round(float(yb[6]), 2), "cls_young": int(yb[7]), "cls_old": int(ob[7] if ob is not None else by_id[old][max(prev)][7] if prev else -1),
                       "x": float(obox[2]), "w_old": round(ow, 1), "survivor": ("young" if tail == young else "old" if tail == old else None),
                       "young_life": len(by_id[young]), "old_life": len(by_id[old]),
                       "young_box": [round(float(v), 1) for v in ybox], "old_box": [round(float(v), 1) for v in obox],
                       "clear_of_ends": bool(f_lo <= fb <= f_hi), "young_backfilled": bool((young, min(by_id[young])) in backfill)})
    print(f"  {len(events)} twin events with the newborn's birth row in the dump")
    hs = Counter(e["holder"] for e in events)
    print("  holder at the newborn's birth: " + ", ".join(f"{k} {v}" for k, v in hs.most_common()))
    lost = [e["lost_k"] for e in events if e["holder"] == "lost"]
    if lost:
        print(f"     lost k frames: median {np.median(lost):.0f}, <=5: {sum(1 for k in lost if k <= 5)}, >5: {sum(1 for k in lost if k > 5)}")
    on = [e for e in events if e["holder"] == "on the vehicle"]
    if on:
        h, _ = np.histogram([e["iou"] for e in on], bins=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1.01])
        print("     holder ON the vehicle: IoU(newborn, holder) at birth: " +
              " ".join(f"{lo:.1f}:{n}" for lo, n in zip([0, .1, .2, .3, .4, .5, .6, .7], h)))
        c = [max(e["cov_young_in_old"], e["cov_old_in_young"]) for e in on]
        h2, _ = np.histogram(c, bins=[0, 0.3, 0.5, 0.7, 0.9, 1.01])
        print("        max coverage either way: " + " ".join(f"{lo}:{n}" for lo, n in zip([0, .3, .5, .7, .9], h2)) +
              f";  offset median {np.median([e['offset_w'] for e in on]):.2f} holder widths; width ratio median "
              f"{np.median([e['w_ratio'] for e in on]):.2f}; newborn conf median {np.median([e['conf_young'] for e in on]):.2f}")
        rel = Counter(("same class" if e["cls_young"] == e["cls_old"] else "cross class") for e in on)
        print("        class: " + ", ".join(f"{k} {v}" for k, v in rel.most_common()))
    print(f"  twin life (frames both on the chain): median {np.median([e['twin_frames'] for e in events]):.0f}, "
          f">= 20: {sum(1 for e in events if e['twin_frames'] >= 20)}, >= 50: {sum(1 for e in events if e['twin_frames'] >= 50)}")
    print("  survivor: " + ", ".join(f"{k} {v}" for k, v in Counter(e["survivor"] for e in events).most_common()))
    print(f"  newborn's whole life median {np.median([e['young_life'] for e in events]):.0f} frames; "
          f"newborn back-filled (weak-box inheritance) {sum(1 for e in events if e['young_backfilled'])}")
    xs = [e["x"] for e in events]
    print("  where (x of the holder's box): " + "  ".join(
        f"{lo}-{lo + 128}:{sum(1 for x in xs if lo <= x < lo + 128)}" for lo in range(0, 640, 128)))
    out = Path(f"runs/v2_week1/twins_{proj}_{cam}_{variant}.json")
    out.write_text(json.dumps(events))
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
