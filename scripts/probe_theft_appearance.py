"""Thefts, Step 2 of plan ok-plan-it-out-wobbly-rose (2026-10-09): does WHAT THE CAR
LOOKS LIKE separate a theft from a good match AT THE MOMENT OF THE MATCH, same depth?

G-TH-1 (2026-09-11, scripts/theft_appearance.py) measured osnet as a break along 17
ruled tracks and missed. Never measured: COLOUR, and a per-match comparison over
hundreds of chain-labelled matches. This probe does both, label-free.

Population (one window): the THEFT switches of research_thefts.py
(runs/v2_week1/thefts_<proj>_<cam>_<variant>.json, with the stage that made the match
onto B), against GOOD matches of the same stage from an in-process re-run of the dump's
tracker (research_thefts.stage_run): the box the id takes is on the chain it has been on
for the last second and stays on for the next MIN_RUN labelled frames.
Per sample: the id's OWN boxes in the second before (up to N_REF, dropping any that
overlap another id's box, IoU > 0.05 - the 07-28 spike's anti-confound) against the box
it takes. Signals: colour (Lab over the central 60% of the box: mean-Lab distance,
chroma-only (a, b) distance, 8-bin histogram Bhattacharyya) and osnet cosine distance.
Gate (pre-declared in the plan): on s25, theft-vs-good AUC >= 0.85 AND an operating point
that refuses <= 1 good match per theft stopped (scaled to the full good population).
s1 reported separately (the chains misread about half of those, theft reel 2026-09-13).
Read-only. Usage:
  .venv/Scripts/python.exe -X utf8 scripts/probe_theft_appearance.py PROJ CAM VARIANT [--n-good N]
Writes runs/v2_week1/probe_appearance_<proj>_<cam>_<variant>.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from research_thefts import LABEL_IOU, MIN_RUN, iou_mat, stage_run, tlbr  # noqa: E402
from research_tracker_break import base_variant  # noqa: E402

N_REF = 5
CLEAN_IOU = 0.05
CENTRE = 0.6
BINS = 8
STAGES = (("s25", True), ("s25", False), ("s1", False), ("s1", True))


def group(stage, lost) -> str:
    return f"{stage}/{'lost' if lost else 'tracked'}"


def colour_desc(img: np.ndarray, b) -> np.ndarray | None:
    """[mean L, a, b] + 3 x BINS histogram over the central CENTRE of the box."""
    x1, y1, x2, y2 = b
    mx, my = (x2 - x1) * (1 - CENTRE) / 2, (y2 - y1) * (1 - CENTRE) / 2
    xa, ya = int(max(0, np.floor(x1 + mx))), int(max(0, np.floor(y1 + my)))
    xb, yb = int(min(img.shape[1], np.ceil(x2 - mx))), int(min(img.shape[0], np.ceil(y2 - my)))
    if xb - xa < 2 or yb - ya < 2:
        return None
    lab = cv2.cvtColor(img[ya:yb, xa:xb].astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB).reshape(-1, 3)
    rng = ((0.0, 100.0), (-128.0, 128.0), (-128.0, 128.0))
    h = [np.histogram(lab[:, c], bins=BINS, range=rng[c])[0].astype(np.float64) for c in range(3)]
    h = [x / max(x.sum(), 1.0) for x in h]
    return np.concatenate([lab.mean(axis=0), *h])


def distances(ref_c: list, take_c, ref_e: list, take_e) -> dict:
    out = {}
    if ref_c and take_c is not None:
        r = np.mean(ref_c, axis=0)
        out["dLab"] = float(np.linalg.norm(r[:3] - take_c[:3]))
        out["dAB"] = float(np.linalg.norm(r[1:3] - take_c[1:3]))
        bc = [np.sum(np.sqrt(r[3 + c * BINS:3 + (c + 1) * BINS] * take_c[3 + c * BINS:3 + (c + 1) * BINS]))
              for c in range(3)]
        out["dHist"] = float(1.0 - np.mean(bc))
    if ref_e and take_e is not None:
        r = np.mean(ref_e, axis=0)
        out["dOsnet"] = float(1.0 - r @ take_e / (np.linalg.norm(r) or 1.0))
    return out


def auc(pos: list, neg: list) -> float:
    """P(theft distance > good distance), ties half."""
    if not pos or not neg:
        return float("nan")
    allv = np.concatenate([pos, neg])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(len(allv)); ranks[order] = np.arange(1, len(allv) + 1)
    for v in np.unique(allv):           # average ranks of ties
        m = allv == v
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def best_point(pos: list, neg: list, n_theft: int, n_good: int) -> tuple:
    """The threshold stopping the most thefts while refusing <= 1 good match (scaled
    to the full good population) per theft stopped: (thr, stopped, refused)."""
    best = (float("nan"), 0.0, 0.0)
    for t in sorted(set(pos)):
        stopped = np.mean(np.asarray(pos) >= t) * n_theft
        refused = np.mean(np.asarray(neg) >= t) * n_good
        if stopped > 0 and refused <= stopped and stopped > best[1]:
            best = (t, stopped, refused)
    return best


def main() -> int:
    proj, cam, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    n_good_s = int(sys.argv[sys.argv.index("--n-good") + 1]) if "--n-good" in sys.argv else 1500
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, chash, fps, vw, vh = con.execute(
        "SELECT path, content_hash, fps, width, height FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    d = tracks_dir(parquet_path(proj, cam, chash, variant))
    meta = json.loads((d / "meta.json").read_text())
    rows = np.array(load_dump(d), dtype=np.float64, copy=True)
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json").read_text())
    events = json.loads(Path(f"runs/v2_week1/thefts_{proj}_{cam}_{variant}.json").read_text())

    # label every dump row with its chain (as research_thefts)
    cf = defaultdict(list)
    for vi, v in enumerate(veh):
        for h in v:
            cf[int(h[0])].append((vi, h[1], h[2], h[3], h[4]))
    rows = rows[np.argsort(rows[:, 1], kind="stable")]
    lab = np.full(len(rows), -1, dtype=np.int64)
    boxes = np.stack([tlbr(r) for r in rows])
    uf, s_ = np.unique(rows[:, 1], return_index=True); e_ = np.append(s_[1:], len(rows))
    frame_rows = {}
    for f, a, b in zip(uf.astype(int), s_, e_):
        frame_rows[f] = (a, b)
        c = cf.get(f)
        if not c:
            continue
        m = iou_mat(boxes[a:b], np.asarray([x[1:] for x in c], dtype=np.float64))
        k = m.argmax(axis=1)
        ok = m[np.arange(len(k)), k] >= LABEL_IOU
        lab[a:b][ok] = np.asarray([c[j][0] for j in k[ok]])
    # per track: (frames, row indices), frame-ordered
    by_tid = defaultdict(list)
    for i, t in enumerate(rows[:, 0].astype(int)):
        by_tid[t].append(i)
    by_tid = {t: np.asarray(ix) for t, ix in by_tid.items()}

    def row_at(tid: int, f: int):
        ix = by_tid.get(tid)
        if ix is None:
            return None
        j = np.searchsorted(rows[ix, 1], f)
        return int(ix[j]) if j < len(ix) and rows[ix[j], 1] == f else None

    def clean(i: int) -> bool:
        a, b = frame_rows[int(rows[i, 1])]
        if b - a <= 1:
            return True
        m = iou_mat(boxes[i:i + 1], boxes[a:b])[0]
        m[i - a] = 0.0
        return bool(m.max() <= CLEAN_IOU)

    def refs(tid: int, chain: int, f_end: int) -> list[int]:
        ix = by_tid[tid]
        fr = rows[ix, 1]
        sel = ix[(fr <= f_end) & (fr > f_end - fps)]
        sel = [int(i) for i in sel if lab[i] == chain and clean(int(i))]
        if len(sel) > N_REF:
            sel = [sel[int(round(k))] for k in np.linspace(0, len(sel) - 1, N_REF)]
        return sel

    samples = []          # {cls, group, take: row idx, refs: [row idx]}
    n_theft = defaultdict(int)
    for e in events:
        if e["kind"] != "THEFT" or e.get("stage") not in ("s25", "s1"):
            continue
        g = group(e["stage"], e.get("was_lost", False))
        tk = row_at(e["track"], e["f_first_B"])
        if tk is None:
            continue
        n_theft[g] += 1
        samples.append({"cls": "theft", "group": g, "take": tk, "refs": refs(e["track"], e["A"], e["f_last_A"]),
                        "f": e["f_first_B"], "track": e["track"]})
    print(f"{proj} cam{cam} {variant}: thefts by stage " + ", ".join(f"{g} {n}" for g, n in n_theft.items()))

    # good matches: the in-process tracker's match log, mapped to dump ids by box
    by_box, log = stage_run(proj, cam, variant, meta, (int(vw), int(vh)) if vw and vh else None)
    theft_at = {(s["track"], s["f"]) for s in samples}
    good = defaultdict(list)
    for (f, pid), rec in log.items():
        if rec[2] not in ("s25", "s1") or f not in frame_rows:
            continue
        mine = [bb for bb, p in by_box.get(f, []) if p == pid]
        if not mine:
            continue
        a, b = frame_rows[f]
        m = iou_mat(np.asarray(mine[:1], dtype=np.float64), boxes[a:b])[0]
        j = int(m.argmax())
        if m[j] <= 0.95:
            continue
        i = a + j
        A, tid = int(lab[i]), int(rows[i, 0])
        if A < 0 or (tid, f) in theft_at:
            continue
        ix = by_tid[tid]; fr = rows[ix, 1]; lb = lab[ix]
        before = lb[(fr < f) & (fr >= f - fps)]
        after = lb[(fr > f)][:MIN_RUN]
        before, after = before[before >= 0], after[after >= 0]
        if len(before) < 3 or (before != A).any() or len(after) < 3 or (after != A).any():
            continue
        good[group(rec[2], rec[3])].append((i, tid, f, A))
    n_good = {g: len(v) for g, v in good.items()}
    print("  good matches by stage " + ", ".join(f"{g} {n}" for g, n in n_good.items()))
    rng = np.random.default_rng(0)
    for g, v in good.items():
        pick = rng.choice(len(v), size=min(n_good_s, len(v)), replace=False)
        for k in pick:
            i, tid, f, A = v[int(k)]
            samples.append({"cls": "good", "group": g, "take": i, "refs": refs(tid, A, f - 1), "f": f, "track": tid})
    samples = [s for s in samples if s["refs"]]

    # crops: decode once, in order
    need = defaultdict(set)
    for s in samples:
        for i in [s["take"], *s["refs"]]:
            need[int(rows[i, 1])].add(i)
    from boxmot.reid.core.reid import ReID
    model = ReID(weights="osnet_x0_25_msmt17.pt", device="cuda:0").model
    col, emb = {}, {}
    cap = cv2.VideoCapture(vpath)
    lo, hi = min(need), max(need)
    cap.set(cv2.CAP_PROP_POS_FRAMES, lo)
    f = lo
    while f <= hi:
        if f in need:
            ok, img = cap.read()
            if not ok:
                break
            idx = sorted(need[f])
            bb = np.clip(boxes[idx], 0, [img.shape[1] - 1, img.shape[0] - 1, img.shape[1] - 1, img.shape[0] - 1])
            good_bb = (bb[:, 2] - bb[:, 0] >= 4) & (bb[:, 3] - bb[:, 1] >= 4)
            if good_bb.any():
                feats = np.asarray(model.get_features(bb[good_bb].astype(np.float32), img), dtype=np.float64)
                for i, ft in zip(np.asarray(idx)[good_bb], feats):
                    emb[int(i)] = ft / (np.linalg.norm(ft) or 1.0)
            for i, b in zip(idx, bb):
                c = colour_desc(img, b)
                if c is not None:
                    col[i] = c
        elif not cap.grab():
            break
        f += 1
    cap.release()

    for s in samples:
        s.update(distances([col[i] for i in s["refs"] if i in col], col.get(s["take"]),
                           [emb[i] for i in s["refs"] if i in emb], emb.get(s["take"])))
        s["w"] = float(rows[s["take"], 4])

    metrics = ("dLab", "dAB", "dHist", "dOsnet")
    print(f"  samples: {sum(s['cls'] == 'theft' for s in samples)} thefts, {sum(s['cls'] == 'good' for s in samples)} good")
    print(f"  {'group':14} {'thefts':>6} {'good(all)':>9} {'w th/gd':>9}  " +
          "  ".join(f"{m + ' AUC':>11}" for m in metrics) + "   best point (<= 1 good refused per theft stopped)")
    summary = {}
    for st, lost in STAGES:
        g = group(st, lost)
        th = [s for s in samples if s["group"] == g and s["cls"] == "theft"]
        gd = [s for s in samples if s["group"] == g and s["cls"] == "good"]
        if not th or not gd:
            continue
        row = {"thefts": n_theft.get(g, 0), "good_all": n_good.get(g, 0)}
        aucs, pts = [], []
        for m in metrics:
            p = [s[m] for s in th if m in s]; q = [s[m] for s in gd if m in s]
            a = auc(p, q)
            t, stopped, refused = best_point(p, q, n_theft.get(g, 0), n_good.get(g, 0))
            row[m] = {"auc": a, "thr": t, "stopped": stopped, "refused": refused}
            aucs.append(f"{a:>11.3f}")
            pts.append(f"{m} {stopped:.0f}/{n_theft.get(g, 0)} for {refused:.0f}")
        summary[g] = row
        print(f"  {g:14} {len(th):>6} {n_good.get(g, 0):>9} {np.median([s['w'] for s in th]):>4.0f}/"
              f"{np.median([s['w'] for s in gd]):<4.0f}  " + "  ".join(aucs) + "   " + "; ".join(pts))
    s25 = [summary[g] for g in ("s25/lost", "s25/tracked") if g in summary]
    best_auc = max((r[m]["auc"] for r in s25 for m in metrics), default=float("nan"))
    print(f"  GATE (s25): best AUC {best_auc:.3f} -> {'PASS' if best_auc >= 0.85 else 'FAIL'} on the AUC clause "
          f"(the operating-point clause is the 'best point' column)")
    out = Path(f"runs/v2_week1/probe_appearance_{proj}_{cam}_{variant}.json")
    out.write_text(json.dumps({"summary": summary, "samples": [
        {k: v for k, v in s.items() if k not in ("refs",)} for s in samples]}, default=float))
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
