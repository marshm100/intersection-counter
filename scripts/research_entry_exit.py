"""Entry vs exit (operator 2026-10-09: "all that matters is the moment before the intersection and the
moment after; the detection far before the intersection is only guidance, not the law").

For every track of a production dump that crosses two DIFFERENT gate lines (ground point = bottom centre
of the box, the legs' drawn gate_segment), compare the car in the APP_S seconds before its first crossing
(entry) with the car in the APP_S seconds after its last crossing of another gate (exit). Truth = the
yardstick chain under the track at entry vs at exit (most common label in those windows): SAME or
DIFFERENT. Signals: osnet cosine distance and colour-histogram distance between the two windows' means
(the .app sidecar, scripts/build_appearance_sidecar.py), and the largest mot_jump between entry and exit
(research_track_qc.score_track). Reported: base rate, AUC, the best threshold on the first window
(precision >= 0.5, most recall) applied unchanged to the others; split through / turn.
Read-only. Usage:
  .venv/Scripts/python.exe -X utf8 scripts/research_entry_exit.py PROJ CAM VARIANT [VARIANT ...]
Writes runs/v2_week1/entry_exit_<proj>_<cam>_<variant>.json
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
from probe_theft_appearance import auc  # noqa: E402
from research_thefts import LABEL_IOU, iou_mat, tlbr  # noqa: E402
from research_track_qc import BINS, join_rows, score_track  # noqa: E402

APP_S = 1.0
MIN_SIDE = 3
SIGNALS = ("app_os", "app_hist", "mot_jump")
THROUGH = {("E", "W"), ("W", "E"), ("N", "S"), ("S", "N")}


def seg_cross(p: np.ndarray, q: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Does step p[i] -> q[i] cross segment a-b? (vectorised over i)"""
    def orient(u, v, w):
        return np.sign((v[..., 0] - u[..., 0]) * (w[..., 1] - u[..., 1])
                       - (v[..., 1] - u[..., 1]) * (w[..., 0] - u[..., 0]))
    return (orient(p, q, a) * orient(p, q, b) < 0) & (orient(a, b, p) * orient(a, b, q) < 0)


def chain_labels(rows: np.ndarray, veh: list) -> np.ndarray:
    """research_thefts' labelling: each dump row -> the chain it overlaps best (IoU >= LABEL_IOU)."""
    cf = defaultdict(list)
    for vi, v in enumerate(veh):
        for h in v:
            cf[int(h[0])].append((vi, *h[1:5]))
    lab = np.full(len(rows), -1, dtype=np.int64)
    order = np.argsort(rows[:, 1], kind="stable")
    rf = rows[order, 1].astype(np.int64)
    uf, s_ = np.unique(rf, return_index=True)
    e_ = np.append(s_[1:], len(rf))
    for f, a, b in zip(uf, s_, e_):
        c = cf.get(int(f))
        if not c:
            continue
        R = np.stack([tlbr(r) for r in rows[order[a:b]]])
        m = iou_mat(R, np.asarray([x[1:] for x in c], dtype=np.float64))
        k = m.argmax(axis=1)
        ok = m[np.arange(len(k)), k] >= LABEL_IOU
        lab[order[a:b][ok]] = np.asarray([c[j][0] for j in k[ok]])
    return lab


def window(proj: str, cam: int, variant: str) -> list[dict]:
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    gates = [(r[0], np.asarray(json.loads(r[1]), dtype=np.float64))
             for r in con.execute("SELECT cardinal_direction, gate_segment FROM legs WHERE camera_id=?", (cam,))
             if r[1]]
    fps = float(fps)
    pqp = parquet_path(proj, cam, chash, variant)
    rows = np.array(load_dump(tracks_dir(pqp)), dtype=np.float64, copy=True)
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{variant}.json").read_text())
    app = pqp.with_name(pqp.stem + ".app")
    emb_mm = np.load(app / "emb.npy", mmap_mode="r")
    col_mm = np.load(app / "col.npy", mmap_mode="r")
    join, bb = join_rows(rows, pqp)
    lab = chain_labels(rows, veh)
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows, join, lab = rows[order], join[order], lab[order]
    ut, st_ = np.unique(rows[:, 0], return_index=True)
    en_ = np.append(st_[1:], len(rows))
    wa = APP_S * fps
    out = []
    for tid, a, b in zip(ut.astype(int), st_, en_):
        if b - a < 2 * MIN_SIDE:
            continue
        r = rows[a:b]
        g = np.stack([r[:, 2], r[:, 3] + r[:, 5] / 2], axis=1)
        cross = []
        for card, seg in gates:
            cross += [(int(i), card) for i in np.flatnonzero(seg_cross(g[:-1], g[1:], seg[0], seg[1]))]
        if len(cross) < 2:
            continue
        cross.sort()
        ent_i, ent_g = cross[0]
        later = [c for c in cross if c[1] != ent_g]
        if not later:
            continue
        ext_i, ext_g = later[-1]
        fr = r[:, 1].astype(np.int64)
        fe, fx = int(fr[ent_i]), int(fr[ext_i + 1])
        bef = np.flatnonzero((fr <= fe) & (fr > fe - wa))
        aft = np.flatnonzero((fr >= fx) & (fr < fx + wa))
        rec = {"track": int(tid), "entry": ent_g, "exit": ext_g, "f_entry": fe, "f_exit": fx, "truth": None}
        lb, la = lab[a:b][bef], lab[a:b][aft]
        lb, la = lb[lb >= 0], la[la >= 0]
        if len(lb) and len(la):
            cb = Counter(lb.tolist()).most_common(1)[0][0]
            ca = Counter(la.tolist()).most_common(1)[0][0]
            rec["truth"] = "SAME" if cb == ca else "DIFFERENT"
        jb, ja = join[a:b][bef], join[a:b][aft]
        jb, ja = jb[jb >= 0], ja[ja >= 0]
        if len(jb) >= MIN_SIDE and len(ja) >= MIN_SIDE:
            eb = np.asarray(emb_mm[jb], dtype=np.float32)
            ea = np.asarray(emb_mm[ja], dtype=np.float32)
            eb, ea = eb[np.linalg.norm(eb, axis=1) > 0], ea[np.linalg.norm(ea, axis=1) > 0]
            if len(eb) and len(ea):
                mb, ma = eb.mean(axis=0), ea.mean(axis=0)
                rec["app_os"] = float(1 - mb @ ma / max(np.linalg.norm(mb) * np.linalg.norm(ma), 1e-9))
            hb = np.asarray(col_mm[jb, 3:], dtype=np.float32)
            ha = np.asarray(col_mm[ja, 3:], dtype=np.float32)
            hb, ha = hb[np.isfinite(hb[:, 0])], ha[np.isfinite(ha[:, 0])]
            if len(hb) and len(ha):
                pb, pa = hb.mean(axis=0), ha.mean(axis=0)
                rec["app_hist"] = float(1 - np.mean([np.sum(np.sqrt(pb[c * BINS:(c + 1) * BINS] *
                                                                     pa[c * BINS:(c + 1) * BINS]))
                                                      for c in range(3)]))
        # motion: the largest jump between entry and exit, from the detector boxes
        j = join[a:b]
        ok = j >= 0
        box = np.where(ok[:, None], bb[np.maximum(j, 0)], np.stack([tlbr(x) for x in r]))
        cen = np.stack([(box[:, 0] + box[:, 2]) / 2, (box[:, 1] + box[:, 3]) / 2], axis=1)
        seg = (fr >= fe - wa) & (fr <= fx + wa)
        sig = score_track(fr[seg], cen[seg], box[seg, 2] - box[seg, 0], None, None, fps)
        mj = sig["mot_jump"][(fr[seg] >= fe) & (fr[seg] <= fx)]
        if np.isfinite(mj).any():
            rec["mot_jump"] = float(np.nanmax(mj))
        out.append(rec)
    return out


def report(name: str, recs: list, thr: dict | None) -> dict:
    lab = [r for r in recs if r["truth"]]
    nd = sum(r["truth"] == "DIFFERENT" for r in lab)
    print(f"  {name}: journeys {len(recs)}, chain-labelled {len(lab)}, DIFFERENT {nd} "
          f"({nd / max(len(lab), 1):.1%})")
    best = {}
    for s in SIGNALS:
        L = [r for r in lab if s in r]
        pos = [r[s] for r in L if r["truth"] == "DIFFERENT"]
        neg = [r[s] for r in L if r["truth"] == "SAME"]
        if not pos or not neg:
            continue
        line = f"    {s}: AUC {auc(pos, neg):.2f} (n {len(pos)} / {len(neg)})"
        if thr is None:
            cands = []
            for t in sorted(set(pos)):
                tp = sum(p >= t for p in pos)
                fp = sum(n >= t for n in neg)
                if tp / (tp + fp) >= 0.5:
                    cands.append((tp / len(pos), tp / (tp + fp), t))
            if cands:
                rc, pr, t = max(cands)
                best[s] = t
                line += f"; best at P>=0.5: thr {t:.3f} P {pr:.2f} R {rc:.2f}"
            else:
                line += "; no threshold reaches P 0.5"
        elif s in thr:
            t = thr[s]
            tp = sum(p >= t for p in pos)
            fp = sum(n >= t for n in neg)
            pr, rc = tp / max(tp + fp, 1), tp / len(pos)
            line += f"; at thr {t:.3f}: P {pr:.2f} R {rc:.2f} -> {'PASS' if pr >= 0.5 and rc >= 0.4 else 'FAIL'}"
        print(line, flush=True)
    return best


def main() -> int:
    proj, cam, variants = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    thr = None
    for v in variants:
        recs = window(proj, cam, v)
        Path(f"runs/v2_week1/entry_exit_{proj}_{cam}_{v}.json").write_text(json.dumps(recs))
        print(f"== {v}{' (thresholds chosen here)' if thr is None else ''}", flush=True)
        b = report("all", recs, thr)
        report("through", [r for r in recs if (r["entry"], r["exit"]) in THROUGH], thr or b)
        report("turn", [r for r in recs if (r["entry"], r["exit"]) not in THROUGH], thr or b)
        if thr is None:
            thr = b
    return 0


if __name__ == "__main__":
    sys.exit(main())
