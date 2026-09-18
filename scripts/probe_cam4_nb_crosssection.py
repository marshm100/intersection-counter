"""cam4 NB deficit: WHERE along the frame do northbound vehicles go missing? (2026-09-12)

cam4 looks along Belt Line: NB traffic enters at the left (S gate, near
field, big boxes) and travels rightward into the far field (N gate at
the vanishing point). Miovision NB_thru 2439 for study_1600; the default
counts 2025. This probe counts, for vertical cross-sections x = X:
  A. distinct pass-1 dump TRACKS whose bottom-centre crosses X rightward
     (the tracker's view of the NB flow at that depth), per 15-min bin;
  B. the counting FATE of those tracks (joined to production
     vehicle_events): counted S->N / other movement / rejected / no event;
  C. raw-DETECTION chains (greedy velocity-predicted linker over the
     parquet, tracker-independent) crossing X rightward, at conf >= 0.10
     and conf >= 0.25 (the tracker birth gate) — the detector's view.
If A ~ Mio at a near-field X and falls off toward the far field, the
tracker sees every NB vehicle and the loss is downstream (counting).
If A < Mio everywhere but C ~ Mio, the loss is track birth/association.
If C < Mio everywhere, the loss is detection.
Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/probe_cam4_nb_crosssection.py [VARIANT] [DB]
"""
from __future__ import annotations

import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

PROJ, CAM = "97a7849a", 4
VARIANT = sys.argv[1] if len(sys.argv) > 1 else "study_1600"
DB = sys.argv[2] if len(sys.argv) > 2 else f"data/projects/{PROJ}/project.db"
XS = [200, 250, 300, 350, 400, 450, 500, 550]
BIN_FRAMES = 9000  # 15 min at 10 fps
MIO_NB_THRU = {"study_1600": [305, 263, 347, 305, 341, 315, 325, 238],
               "study_0700": None, "study_1100": None}


def crossings_rightward(xs: np.ndarray) -> set[int]:
    """Set of X in XS crossed rightward by the ordered x sequence."""
    out = set()
    if len(xs) < 2:
        return out
    for X in XS:
        hit = np.nonzero((xs[:-1] < X) & (xs[1:] >= X))[0]
        if len(hit):
            out.add(X)
    return out


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (CAM,)).fetchone()
    legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (CAM,)))
    pqp = parquet_path(PROJ, CAM, chash, VARIANT)
    meta = __import__("json").load(open(pqp.with_suffix(".meta.json")))
    f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
    nbins = math.ceil((f1 - f0) / BIN_FRAMES)
    print(f"cam4 {VARIANT}: frames {f0}-{f1}, {nbins} bins, model {meta.get('model')}@{meta.get('imgsz')}")

    # ---- A/B: tracks ----------------------------------------------------
    rows = np.asarray(load_dump(tracks_dir(pqp)))
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    tids, st = np.unique(rows[:, 0], return_index=True)
    en = np.append(st[1:], len(rows))
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ev = defaultdict(list)
    for tid, o, d, rej, src in db.execute(
            "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, COALESCE(rejected,0), posterior_source "
            "FROM vehicle_events WHERE camera_id=? AND start_frame BETWEEN ? AND ?", (CAM, f0 - 3000, f1 + 3000)):
        ev[int(tid)].append((legs.get(o, "?"), legs.get(d, "?"), rej, src))

    per_x_bin = {X: Counter() for X in XS}
    fate_x = {X: Counter() for X in XS}
    death_x_hist = Counter()   # where NB-bearing tracks that crossed 300 die
    box_at_x = {X: [] for X in XS}
    for t, a, b in zip(tids, st, en):
        trk = rows[a:b]
        if len(trk) < 2:
            continue
        xs = trk[:, 2].astype(float)
        crossed = crossings_rightward(xs)
        if not crossed:
            continue
        bin_i = min(nbins - 1, max(0, int((trk[0, 1] - f0) // BIN_FRAMES)))
        evs = ev.get(int(t), [])
        counted = [e for e in evs if e[2] == 0]
        if counted:
            fate = "counted " + "/".join(f"{e[0]}->{e[1]}" for e in counted)
        elif evs:
            fate = "rejected " + "/".join(f"{e[0]}->{e[1]}" for e in evs)
        else:
            fate = "NO EVENT"
        for X in crossed:
            per_x_bin[X][bin_i] += 1
            fate_x[X][fate] += 1
            k = int(np.argmax(xs >= X))
            box_at_x[X].append(float(trk[k, 4]))
        if 300 in crossed:
            death_x_hist[int(xs[-1] // 50 * 50)] += 1

    mio = MIO_NB_THRU.get(VARIANT)
    print("\nA. distinct TRACKS crossing X rightward, per bin  (Mio NB_thru per bin on the last row)")
    print("   X   " + " ".join(f"b{i:<4}" for i in range(nbins)) + "  total  med_box_px")
    for X in XS:
        c = per_x_bin[X]
        tot = sum(c.values())
        med = np.median(box_at_x[X]) if box_at_x[X] else 0
        print(f"  {X:4} " + " ".join(f"{c[i]:5}" for i in range(nbins)) + f"  {tot:5}   {med:5.1f}")
    if mio:
        print("   Mio " + " ".join(f"{m:5}" for m in mio) + f"  {sum(mio):5}")

    print("\nB. counting FATE of tracks crossing X rightward (top 8 fates per X)")
    for X in XS:
        tot = sum(fate_x[X].values())
        sn = sum(n for f, n in fate_x[X].items() if f.startswith("counted") and "S->N" in f)
        print(f"  X={X}: {tot} tracks; {sn} carry a counted S->N")
        for f, n in fate_x[X].most_common(8):
            print(f"        {n:5}  {f}")

    print("\n   death x (50-px buckets) of tracks that crossed X=300 rightward:",
          sorted(death_x_hist.items()))

    # ---- C: raw detection chains ----------------------------------------
    tbl = pq.read_table(pqp, columns=["frame_idx", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "confidence"])
    fr = tbl.column("frame_idx").to_numpy()
    x1 = tbl.column("bbox_x1").to_numpy(); x2 = tbl.column("bbox_x2").to_numpy()
    y1 = tbl.column("bbox_y1").to_numpy(); y2 = tbl.column("bbox_y2").to_numpy()
    cf = tbl.column("confidence").to_numpy()
    print(f"\nC. raw detections: {len(fr)} rows")
    # class-agnostic NMS at IoU 0.6 per frame (the detector double-boxes one
    # vehicle car+truck in most frames; a chain per box would double count)
    keep = np.zeros(len(fr), dtype=bool)
    order_all = np.lexsort((-cf, fr))
    fr_s = fr[order_all]
    bounds = np.flatnonzero(np.diff(fr_s)) + 1
    for grp in np.split(order_all, bounds):
        kept = []
        for i in grp:
            ok = True
            for j in kept:
                ix = max(0.0, min(x2[i], x2[j]) - max(x1[i], x1[j]))
                iy = max(0.0, min(y2[i], y2[j]) - max(y1[i], y1[j]))
                inter = ix * iy
                if inter <= 0:
                    continue
                a = (x2[i] - x1[i]) * (y2[i] - y1[i]); b = (x2[j] - x1[j]) * (y2[j] - y1[j])
                if inter / (a + b - inter) > 0.6:
                    ok = False; break
            if ok:
                kept.append(i)
        keep[kept] = True
    print(f"   after class-agnostic NMS 0.6: {keep.sum()} rows ({keep.mean():.0%} kept)")
    # which detections are covered by a dump-track box on their frame
    ufr, s_ = np.unique(rows[:, 1], return_index=True); e_ = np.append(s_[1:], len(rows))
    rows_f = rows[np.argsort(rows[:, 1], kind="stable")]
    ufr, s_ = np.unique(rows_f[:, 1], return_index=True); e_ = np.append(s_[1:], len(rows_f))
    fidx = dict(zip(ufr.astype(int), zip(s_, e_)))
    covered = np.zeros(len(fr), dtype=bool)
    cx_all = (x1 + x2) / 2; cy_all = (y1 + y2) / 2; bw_all = x2 - x1
    for i in np.flatnonzero(keep):
        ab = fidx.get(int(fr[i]))
        if ab is None:
            continue
        r = rows_f[ab[0]:ab[1]]
        d = np.hypot(r[:, 2] - cx_all[i], r[:, 3] - cy_all[i])
        covered[i] = bool((d < 0.5 * np.maximum(bw_all[i], r[:, 4])).any())
    for lo, hi in ((0.10, 0.25), (0.25, 1.01)):
        m = keep & (cf >= lo) & (cf < hi) & (fr >= f0) & (fr <= f1)
        print(f"   deduped dets conf [{lo:.2f},{hi:.2f}): {m.sum():7}; untracked share by x band: " +
              " ".join(f"{b}:{(~covered[m & (cx_all >= b) & (cx_all < b + 100)]).mean():.0%}" for b in range(0, 600, 100)))
    cx = cx_all; bw = bw_all
    for label, m0 in (("conf >= 0.10 (deduped)", keep & (cf >= 0.10)),
                      ("conf >= 0.25 (deduped)", keep & (cf >= 0.25)),
                      ("UNTRACKED only, conf >= 0.10 (deduped)", keep & (cf >= 0.10) & ~covered)):
        m = m0 & (fr >= f0) & (fr <= f1)
        order = np.argsort(fr[m], kind="stable")
        F = fr[m][order]; CX = cx[m][order]; CY = y2[m][order]; BW = bw[m][order]
        starts = np.searchsorted(F, np.arange(f0, f1 + 1))
        ends = np.searchsorted(F, np.arange(f0, f1 + 1), side="right")
        active = []   # dicts: xs list, last (x, y), vel (vx, vy), last_f, bw
        finished = []
        for fi in range(f0, f1 + 1):
            a, b = starts[fi - f0], ends[fi - f0]
            dets = [(float(CX[i]), float(CY[i]), float(BW[i])) for i in range(a, b)]
            used = set()
            still = []
            for tk in active:
                if fi - tk["last_f"] > 5:
                    finished.append(tk)
                    continue
                still.append(tk)
            active = still
            # predicted position, greedy by distance
            cand = []
            for ti, tk in enumerate(active):
                gap = fi - tk["last_f"]
                px = tk["last"][0] + tk["vel"][0] * gap
                py = tk["last"][1] + tk["vel"][1] * gap
                gate = max(15.0, 0.9 * tk["bw"])
                for di, (x, y, w) in enumerate(dets):
                    d = math.hypot(x - px, y - py)
                    if d < gate:
                        cand.append((d, ti, di))
            cand.sort()
            taken_t = set()
            for d, ti, di in cand:
                if ti in taken_t or di in used:
                    continue
                tk = active[ti]
                x, y, w = dets[di]
                gap = fi - tk["last_f"]
                tk["vel"] = ((x - tk["last"][0]) / gap, (y - tk["last"][1]) / gap)
                tk["last"] = (x, y); tk["last_f"] = fi; tk["bw"] = w
                tk["xs"].append(x); tk["n"] += 1
                taken_t.add(ti); used.add(di)
            for di, (x, y, w) in enumerate(dets):
                if di not in used:
                    active.append({"xs": [x], "last": (x, y), "vel": (0.0, 0.0),
                                   "last_f": fi, "bw": w, "n": 1, "f0": fi})
        finished.extend(active)
        per_x = {X: Counter() for X in XS}
        for tk in finished:
            if tk["n"] < 3:
                continue
            xs = np.asarray(tk["xs"])
            if xs[-1] - xs[0] < 40:
                continue
            bin_i = min(nbins - 1, max(0, int((tk["f0"] - f0) // BIN_FRAMES)))
            for X in crossings_rightward(xs):
                per_x[X][bin_i] += 1
        print(f"\n   {label}: detection CHAINS (>=3 hits, >=40 px rightward) crossing X rightward")
        print("   X   " + " ".join(f"b{i:<4}" for i in range(nbins)) + "  total")
        for X in XS:
            c = per_x[X]
            print(f"  {X:4} " + " ".join(f"{c[i]:5}" for i in range(nbins)) + f"  {sum(c.values()):5}")
        if mio:
            print("   Mio " + " ".join(f"{m:5}" for m in mio) + f"  {sum(mio):5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
