"""The track QC check (plan ok-plan-it-out-wobbly-rose, Phase 0d, 2026-10-09).

Step 4 of the operator's loop: along every track, at every point, does the car
before look like the car after (appearance), and is the step between them a
believable motion (no jump in speed or heading without a ramp)? Measured here,
label-free, against the yardstick chains, before any loop is built.

Per track (production dump), at each row i (a candidate cut between row i-1 and i),
from the track's OWN detector boxes (each dump row is joined to the parquet row it
was built from: same frame, best IoU >= JOIN_IOU; appearance from the .app sidecar,
scripts/build_appearance_sidecar.py):
  app_os    osnet cosine distance, mean over the APP_S seconds before vs after
  app_hist  Lab-histogram Bhattacharyya distance, same windows (colour)
  mot_dv    |velocity after - velocity before| over MOT_S seconds each side, in
            box widths per second (detector box centres, least squares)
  mot_jump  the gap at the cut between the before-line and the after-line, in box widths
Flags = local maxima (one per +-APP_S) of a score above a threshold.
Truth = the theft census (research_thefts.py) on the same dump: a flag is TRUE if it
lies within TOL_S of a THEFT / EMERGENCE / A ENDS switch of that track, NEUTRAL near
a CHAIN SEAM, else FALSE. Recall is over switches with enough boxes either side.
Rules: each signal alone, and app AND mot. The operating point is chosen on the first
window given (study_1600) and then applied unchanged to the others (the gate:
recall >= 0.40 at precision >= 0.50 on every window, one operating point).
Read-only. Usage:
  .venv/Scripts/python.exe -X utf8 scripts/research_track_qc.py PROJ CAM VARIANT [VARIANT ...]
Writes runs/v2_week1/track_qc_<proj>_<cam>_<variant>.json
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
from research_thefts import iou_mat, tlbr  # noqa: E402

JOIN_IOU = 0.7
APP_S = 1.0
MOT_S = 0.5
TOL_S = 0.5
MIN_SIDE = 3
BINS = 8
WRONG = ("THEFT", "EMERGENCE", "A ENDS")
SIGNALS = ("app_os", "app_hist", "mot_dv", "mot_jump")


def join_rows(rows: np.ndarray, pqp: Path) -> np.ndarray:
    """Parquet row index for every dump row (-1 if none overlaps >= JOIN_IOU)."""
    t = pq.read_table(pqp, columns=["frame_idx", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2"])
    fr = t.column("frame_idx").to_numpy().astype(np.int64)
    bb = np.stack([t.column(c).to_numpy() for c in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2")],
                  axis=1).astype(np.float64)
    pf, ps = np.unique(fr, return_index=True)
    pe = np.append(ps[1:], len(fr))
    out = np.full(len(rows), -1, dtype=np.int64)
    order = np.argsort(rows[:, 1], kind="stable")
    rf = rows[order, 1].astype(np.int64)
    uf, s_ = np.unique(rf, return_index=True)
    e_ = np.append(s_[1:], len(rf))
    pos = np.searchsorted(pf, uf)
    for f, a, b, p in zip(uf, s_, e_, pos):
        if p >= len(pf) or pf[p] != f:
            continue
        R = np.stack([tlbr(r) for r in rows[order[a:b]]])
        m = iou_mat(R, bb[ps[p]:pe[p]])
        k = m.argmax(axis=1)
        ok = m[np.arange(len(k)), k] >= JOIN_IOU
        out[order[a:b][ok]] = ps[p] + k[ok]
    return out, bb


def line_fit(t: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Least-squares x = a + v t for 2-d x; returns (a at t=0, v)."""
    A = np.stack([np.ones_like(t), t], axis=1)
    coef, *_ = np.linalg.lstsq(A, x, rcond=None)
    return coef[0], coef[1]


def score_track(fr: np.ndarray, cen: np.ndarray, w: np.ndarray, emb: np.ndarray | None,
                hist: np.ndarray | None, fps: float) -> dict:
    """Signals at each row i (cut between i-1 and i); NaN where a side is too thin."""
    n = len(fr)
    out = {s: np.full(n, np.nan) for s in SIGNALS}
    wa, wm = APP_S * fps, MOT_S * fps
    for i in range(1, n):
        f = fr[i]
        lo_a, hi_a = np.searchsorted(fr, f - wa), np.searchsorted(fr, f + wa)
        if emb is not None:
            ba, aa = emb[lo_a:i], emb[i:hi_a]
            ba, aa = ba[np.isfinite(ba[:, 0])], aa[np.isfinite(aa[:, 0])]
            if len(ba) >= MIN_SIDE and len(aa) >= MIN_SIDE:
                mb, ma = ba.mean(axis=0), aa.mean(axis=0)
                out["app_os"][i] = 1.0 - mb @ ma / max(np.linalg.norm(mb) * np.linalg.norm(ma), 1e-9)
        if hist is not None:
            hb, ha = hist[lo_a:i], hist[i:hi_a]
            hb, ha = hb[np.isfinite(hb[:, 0])], ha[np.isfinite(ha[:, 0])]
            if len(hb) >= MIN_SIDE and len(ha) >= MIN_SIDE:
                pb, pa = hb.mean(axis=0), ha.mean(axis=0)
                out["app_hist"][i] = 1.0 - np.mean([np.sum(np.sqrt(pb[c * BINS:(c + 1) * BINS] *
                                                                   pa[c * BINS:(c + 1) * BINS]))
                                                    for c in range(3)])
        lo_m, hi_m = np.searchsorted(fr, f - wm), np.searchsorted(fr, f + wm)
        if i - lo_m >= MIN_SIDE and hi_m - i >= MIN_SIDE:
            tb, ta = (fr[lo_m:i] - f) / fps, (fr[i:hi_m] - f) / fps
            a0, vb = line_fit(tb, cen[lo_m:i])
            a1, va = line_fit(ta, cen[i:hi_m])
            bw = max(float(np.median(w[lo_m:hi_m])), 1.0)
            out["mot_dv"][i] = float(np.linalg.norm(va - vb)) / bw
            out["mot_jump"][i] = float(np.linalg.norm(a1 - a0)) / bw
    return out


def flags_at(fr: np.ndarray, s: np.ndarray, thr: float, sep: float) -> list[int]:
    """Local maxima of s above thr, at least sep frames apart (greedy, highest first)."""
    idx = np.flatnonzero(np.nan_to_num(s, nan=-np.inf) >= thr)
    picked: list[int] = []
    for i in idx[np.argsort(-s[idx])]:
        if all(abs(fr[i] - fr[j]) > sep for j in picked):
            picked.append(int(i))
    return picked


def window(proj: str, cam: int, variant: str) -> dict:
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    pqp = parquet_path(proj, cam, chash, variant)
    rows = np.array(load_dump(tracks_dir(pqp)), dtype=np.float64, copy=True)
    app = pqp.with_name(pqp.stem + ".app")
    emb_mm = np.load(app / "emb.npy", mmap_mode="r")
    col_mm = np.load(app / "col.npy", mmap_mode="r")
    ev = json.loads(Path(f"runs/v2_week1/thefts_{proj}_{cam}_{variant}.json").read_text())
    join, bb = join_rows(rows, pqp)
    print(f"{variant}: {len(rows)} dump rows, joined to a detector box {np.mean(join >= 0):.3f}; "
          f"census switches {len(ev)}", flush=True)

    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows, join = rows[order], join[order]
    ut, st_ = np.unique(rows[:, 0], return_index=True)
    en_ = np.append(st_[1:], len(rows))
    tracks = {}
    for tid, a, b in zip(ut.astype(int), st_, en_):
        if b - a < 2 * MIN_SIDE:
            continue
        j = join[a:b]
        ok = j >= 0
        fr = rows[a:b, 1].astype(np.int64)
        box = np.where(ok[:, None], bb[np.maximum(j, 0)], np.stack([tlbr(r) for r in rows[a:b]]))
        cen = np.stack([(box[:, 0] + box[:, 2]) / 2, (box[:, 1] + box[:, 3]) / 2], axis=1)
        w = box[:, 2] - box[:, 0]
        emb = np.full((b - a, emb_mm.shape[1]), np.nan, dtype=np.float32)
        hist = np.full((b - a, col_mm.shape[1] - 3), np.nan, dtype=np.float32)
        if ok.any():
            e = np.asarray(emb_mm[j[ok]], dtype=np.float32)
            e[np.linalg.norm(e, axis=1) == 0] = np.nan
            emb[ok] = e
            hist[ok] = np.asarray(col_mm[j[ok], 3:], dtype=np.float32)
        tracks[tid] = (fr, score_track(fr, cen, w, emb, hist, fps))
    by_track = {}
    for e in ev:
        by_track.setdefault(int(e["track"]), []).append(e)
    return {"variant": variant, "fps": fps, "tracks": tracks, "events": by_track, "n_events": Counter(
        e["kind"] for e in ev), "n_swaps": sum(1 for e in ev if e["kind"] == "THEFT" and e["swap_with"])}


def evaluate(W: dict, rule: tuple) -> dict:
    """rule = ((signal, thr), ...) AND-ed; flags placed on the first signal's maxima."""
    fps = W["fps"]
    tol, sep = TOL_S * fps, APP_S * fps
    tp = fp = neutral = 0
    caught: Counter = Counter()
    eligible: Counter = Counter()
    for tid, (fr, sig) in W["tracks"].items():
        s = sig[rule[0][0]].copy()
        for name, thr in rule:
            s[~(np.nan_to_num(sig[name], nan=-np.inf) >= thr)] = np.nan
        fl = flags_at(fr, s, -np.inf, sep) if np.isfinite(s).any() else []
        evs = W["events"].get(tid, [])
        hit_ev = set()
        for i in fl:
            f = fr[i]
            near = [k for k, e in enumerate(evs) if e["f_last_A"] - tol <= f <= e["f_first_B"] + tol]
            if any(evs[k]["kind"] in WRONG for k in near):
                tp += 1
                hit_ev.update(k for k in near if evs[k]["kind"] in WRONG)
            elif near:
                neutral += 1
            else:
                fp += 1
        for k, e in enumerate(evs):
            if e["kind"] not in WRONG:
                continue
            i = np.searchsorted(fr, e["f_first_B"])
            elig = 0 < i < len(fr) and any(np.isfinite(sig[n][max(i - 2, 0):i + 3]).any() for n, _ in rule)
            key = "SWAP" if e["kind"] == "THEFT" and e["swap_with"] else e["kind"]
            if elig:
                eligible[key] += 1
                if k in hit_ev:
                    caught[key] += 1
    n_el = sum(eligible.values())
    return {"rule": [list(r) for r in rule], "tp": tp, "fp": fp, "neutral": neutral,
            "precision": tp / max(tp + fp, 1), "recall": sum(caught.values()) / max(n_el, 1),
            "caught": dict(caught), "eligible": dict(eligible)}


def quantiles(W: dict, name: str) -> np.ndarray:
    v = np.concatenate([sig[name][np.isfinite(sig[name])] for _, sig in W["tracks"].values()])
    return np.quantile(v, [0.90, 0.95, 0.98, 0.99, 0.995, 0.998, 0.999])


def fmt(r: dict) -> str:
    return (f"P {r['precision']:.2f}  R {r['recall']:.2f}  tp {r['tp']} fp {r['fp']} nt {r['neutral']}  "
            "caught " + " ".join(f"{k} {r['caught'].get(k, 0)}/{r['eligible'].get(k, 0)}"
                                 for k in ("THEFT", "SWAP", "EMERGENCE", "A ENDS")))


def main() -> int:
    proj, cam, variants = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    Ws = [window(proj, cam, v) for v in variants]
    W0 = Ws[0]
    q = {s: quantiles(W0, s) for s in SIGNALS}
    print(f"\n== {W0['variant']} (operating point chosen here) ==")
    for s in SIGNALS:
        print(f"  {s} quantiles 90..99.9: " + " ".join(f"{x:.3f}" for x in q[s]))
    results = []
    for s in SIGNALS:
        for t in q[s]:
            results.append(evaluate(W0, ((s, float(t)),)))
    for a in ("app_os", "app_hist"):
        for m in ("mot_dv", "mot_jump"):
            for ta in q[a][:5]:
                for tm in q[m][:5]:
                    results.append(evaluate(W0, ((a, float(ta)), (m, float(tm)))))
    for r in results:
        print("  " + " & ".join(f"{n}>={t:.3f}" for n, t in r["rule"]).ljust(42) + fmt(r))
    ok = [r for r in results if r["precision"] >= 0.5]
    best = max(ok, key=lambda r: r["recall"]) if ok else max(results, key=lambda r: r["precision"])
    print(f"\n  OPERATING POINT ({'meets P>=0.5' if ok else 'NO rule reaches P>=0.5; best precision'}): "
          + " & ".join(f"{n}>={t:.3f}" for n, t in best["rule"]))
    rule = tuple((n, t) for n, t in best["rule"])
    verdict = []
    for W in Ws:
        r = evaluate(W, rule)
        passed = r["precision"] >= 0.5 and r["recall"] >= 0.40
        verdict.append(passed)
        print(f"  {W['variant']}: {fmt(r)}  -> {'PASS' if passed else 'FAIL'}")
        out = Path(f"runs/v2_week1/track_qc_{proj}_{cam}_{W['variant']}.json")
        out.write_text(json.dumps({"operating_point": r, "chosen_on": W0["variant"],
                                   "grid": results if W is W0 else None}, indent=1))
    print(f"\nGATE (recall >= 0.40 at precision >= 0.50, every window): {'PASS' if all(verdict) else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
