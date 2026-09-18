"""cam4 NB: where do the far-field northbound chains BEGIN? (2026-09-12)

The cross-section probe found the detector's rightward chains match
Miovision at the far end (x=550: 2412 vs 2439) but not the near end
(x=200: 1966). If ~450 NB vehicles have no near-field chain of their
own, they must EMERGE mid-frame — from behind/beside another vehicle
(near-field occlusion: one box for two side-by-side vehicles that
separate with distance). This probe, tracker-independent:
  1. links deduped detections (conf >= 0.10) into chains;
  2. for every chain crossing x=550 rightward, records its first x;
  3. for chains beginning past x=350 ("emergences"), looks for a
     companion chain alive at the emergence frame within 1.5 box widths
     that is also moving right — the occluder;
  4. renders frame strips of the first K emergences for the eye.
Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/probe_cam4_nb_emergence.py [VARIANT] [K]
"""
from __future__ import annotations

import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import parquet_path  # noqa: E402

PROJ, CAM = "97a7849a", 4
_MAIN = Path(sys.argv[0]).name == Path(__file__).name
VARIANT = sys.argv[1] if _MAIN and len(sys.argv) > 1 else "study_1600"
K = int(sys.argv[2]) if _MAIN and len(sys.argv) > 2 else 4
XFAR, XNEAR = 550, 350


def dedup(fr, x1, y1, x2, y2, cf, iou=0.6):
    keep = np.zeros(len(fr), dtype=bool)
    order_all = np.lexsort((-cf, fr))
    bounds = np.flatnonzero(np.diff(fr[order_all])) + 1
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
                if inter / (a + b - inter) > iou:
                    ok = False; break
            if ok:
                kept.append(i)
        keep[kept] = True
    return keep


def link(F, CX, CY, BW, CF, f0, f1):
    starts = np.searchsorted(F, np.arange(f0, f1 + 1))
    ends = np.searchsorted(F, np.arange(f0, f1 + 1), side="right")
    active, finished = [], []
    for fi in range(f0, f1 + 1):
        a, b = starts[fi - f0], ends[fi - f0]
        dets = [(float(CX[i]), float(CY[i]), float(BW[i]), float(CF[i]), i) for i in range(a, b)]
        still = []
        for tk in active:
            (finished if fi - tk["last_f"] > 5 else still).append(tk)
        active = still
        cand = []
        for ti, tk in enumerate(active):
            gap = fi - tk["last_f"]
            px = tk["last"][0] + tk["vel"][0] * gap; py = tk["last"][1] + tk["vel"][1] * gap
            gate = max(15.0, 0.9 * tk["bw"])
            for di, (x, y, w, c, _i) in enumerate(dets):
                d = math.hypot(x - px, y - py)
                if d < gate:
                    cand.append((d, ti, di))
        cand.sort()
        taken_t, used = set(), set()
        for d, ti, di in cand:
            if ti in taken_t or di in used:
                continue
            tk = active[ti]; x, y, w, c, ii = dets[di]; gap = fi - tk["last_f"]
            tk["vel"] = ((x - tk["last"][0]) / gap, (y - tk["last"][1]) / gap)
            tk["last"] = (x, y); tk["last_f"] = fi; tk["bw"] = w
            tk["xs"].append(x); tk["ys"].append(y); tk["ws"].append(w); tk["cs"].append(c); tk["fs"].append(fi); tk["ix"].append(ii)
            taken_t.add(ti); used.add(di)
        for di, (x, y, w, c, ii) in enumerate(dets):
            if di not in used:
                active.append({"xs": [x], "ys": [y], "ws": [w], "cs": [c], "fs": [fi], "ix": [ii], "last": (x, y),
                               "vel": (0.0, 0.0), "last_f": fi, "bw": w})
    finished.extend(active)
    return [tk for tk in finished if len(tk["xs"]) >= 3]


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    vpath, chash = con.execute("SELECT path, content_hash FROM videos WHERE camera_id=?", (CAM,)).fetchone()
    pqp = parquet_path(PROJ, CAM, chash, VARIANT)
    import json
    meta = json.load(open(pqp.with_suffix(".meta.json")))
    f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
    tbl = pq.read_table(pqp, columns=["frame_idx", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "confidence"])
    fr = tbl.column("frame_idx").to_numpy(); cf = tbl.column("confidence").to_numpy()
    x1 = tbl.column("bbox_x1").to_numpy(); x2 = tbl.column("bbox_x2").to_numpy()
    y1 = tbl.column("bbox_y1").to_numpy(); y2 = tbl.column("bbox_y2").to_numpy()
    keep = dedup(fr, x1, y1, x2, y2, cf) & (cf >= 0.10) & (fr >= f0) & (fr <= f1)
    idx = np.flatnonzero(keep); idx = idx[np.argsort(fr[idx], kind="stable")]
    F = fr[idx]; CX = ((x1 + x2) / 2)[idx]; CY = y2[idx]; BW = (x2 - x1)[idx]; CF = cf[idx]
    chains = link(F, CX, CY, BW, CF, f0, f1)
    print(f"cam4 {VARIANT}: {len(chains)} chains (>=3 hits) from {len(idx)} deduped dets")

    far = []
    for tk in chains:
        xs = np.asarray(tk["xs"])
        if xs[-1] - xs[0] < 40:
            continue
        if ((xs[:-1] < XFAR) & (xs[1:] >= XFAR)).any():
            far.append(tk)
    print(f"chains crossing x={XFAR} rightward: {len(far)}")
    first_x = np.asarray([tk["xs"][0] for tk in far])
    h, e = np.histogram(first_x, bins=[0, 100, 200, 300, 350, 400, 450, 500, 550])
    print("  first x of those chains:", "  ".join(f"{int(lo)}-{int(hi)}:{c}" for c, lo, hi in zip(h, e[:-1], e[1:])))
    emerg = [tk for tk in far if tk["xs"][0] > XNEAR]
    print(f"  EMERGENCES (first x > {XNEAR}): {len(emerg)}; median first box w "
          f"{np.median([tk['ws'][0] for tk in emerg]):.1f} px, median first conf {np.median([tk['cs'][0] for tk in emerg]):.2f}, "
          f"median first y {np.median([tk['ys'][0] for tk in emerg]):.0f}")
    # companions: another chain alive at the emergence frame, centre within 1.5 box widths, moving right
    by_frame = {}
    for ci, tk in enumerate(chains):
        for k, f in enumerate(tk["fs"]):
            by_frame.setdefault(f, []).append((ci, k))
    comp = Counter()
    for tk in emerg:
        f, x, y, w = tk["fs"][0], tk["xs"][0], tk["ys"][0], tk["ws"][0]
        found = "none"
        for ci, k in by_frame.get(f, []):
            o = chains[ci]
            if o is tk or k == 0:
                continue
            ox, oy, ow = o["xs"][k], o["ys"][k], o["ws"][k]
            if math.hypot(ox - x, oy - y) < 1.5 * max(w, ow):
                vx = o["xs"][k] - o["xs"][max(0, k - 3)]
                found = "companion moving right" if vx > 5 else ("companion moving left" if vx < -5 else "companion still")
                break
        comp[found] += 1
    print("  companion at the emergence frame:", dict(comp))
    per_bin = Counter(min(7, (tk["fs"][0] - f0) // 9000) for tk in emerg)
    print("  emergences per 15-min bin:", [per_bin[i] for i in range(8)])

    # frame strips for the eye: emergences with a rightward companion, first conf >= 0.25
    picks = [tk for tk in emerg if tk["cs"][0] >= 0.25 and 400 <= tk["xs"][0] <= 520][:K]
    cap = cv2.VideoCapture(vpath)
    det_by_frame = {}
    for i in idx:
        det_by_frame.setdefault(int(fr[i]), []).append((x1[i], y1[i], x2[i], y2[i], cf[i]))
    for n, tk in enumerate(picks, 1):
        fe = tk["fs"][0]
        tiles = []
        for f in range(fe - 8, fe + 5, 2):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f); ok, img = cap.read()
            if not ok:
                continue
            for (a, b, c, d, s) in det_by_frame.get(f, []):
                col = (0, 200, 255) if s >= 0.25 else (255, 0, 255)
                cv2.rectangle(img, (int(a), int(b)), (int(c), int(d)), col, 1)
            for k, ff in enumerate(tk["fs"]):
                if ff == f:
                    x, y, w = tk["xs"][k], tk["ys"][k], tk["ws"][k]
                    cv2.circle(img, (int(x), int(y)), 6, (0, 255, 0), 2)
            cv2.putText(img, f"f{f} ({f - fe:+d})", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            tiles.append(img)
        if tiles:
            grid = np.vstack([np.hstack(tiles[i:i + 2]) if i + 1 < len(tiles) else np.hstack([tiles[i], np.zeros_like(tiles[i])])
                              for i in range(0, len(tiles), 2)])
            out = f"screenshots/cam4_{VARIANT}_emergence_{n}.png"
            cv2.imwrite(out, grid)
            print(f"  strip {n}: chain first at f{fe} x={tk['xs'][0]:.0f} y={tk['ys'][0]:.0f} w={tk['ws'][0]:.0f} "
                  f"conf={tk['cs'][0]:.2f}, {len(tk['xs'])} hits, ends x={tk['xs'][-1]:.0f} -> {out}")
    return 0


if __name__ == "__main__" and not (len(sys.argv) > 3 and sys.argv[3] == "coverage"):
    raise SystemExit(main())


def coverage(variant: str = VARIANT) -> None:
    """For each emergence chain: where along it does a pass-1 dump track first cover it?"""
    from backend.services.pass2_replay import load_dump, tracks_dir
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (CAM,)).fetchone()
    pqp = parquet_path(PROJ, CAM, chash, variant)
    import json
    meta = json.load(open(pqp.with_suffix(".meta.json")))
    f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
    tbl = pq.read_table(pqp, columns=["frame_idx", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "confidence"])
    fr = tbl.column("frame_idx").to_numpy(); cf = tbl.column("confidence").to_numpy()
    x1 = tbl.column("bbox_x1").to_numpy(); x2 = tbl.column("bbox_x2").to_numpy()
    y1 = tbl.column("bbox_y1").to_numpy(); y2 = tbl.column("bbox_y2").to_numpy()
    keep = dedup(fr, x1, y1, x2, y2, cf) & (cf >= 0.10) & (fr >= f0) & (fr <= f1)
    idx = np.flatnonzero(keep); idx = idx[np.argsort(fr[idx], kind="stable")]
    F = fr[idx]; CX = ((x1 + x2) / 2)[idx]; CY = y2[idx]; BW = (x2 - x1)[idx]; CF = cf[idx]
    chains = link(F, CX, CY, BW, CF, f0, f1)
    rows = np.asarray(load_dump(tracks_dir(pqp)))
    rows = rows[np.argsort(rows[:, 1], kind="stable")]
    ufr, s_ = np.unique(rows[:, 1], return_index=True); e_ = np.append(s_[1:], len(rows))
    fidx = dict(zip(ufr.astype(int), zip(s_, e_)))
    emerg = []
    for tk in chains:
        xs = np.asarray(tk["xs"])
        if xs[-1] - xs[0] >= 40 and ((xs[:-1] < XFAR) & (xs[1:] >= XFAR)).any() and xs[0] > XNEAR:
            emerg.append(tk)
    first_cov_x, never, cover_tid = [], 0, []
    for tk in emerg:
        got = None
        for k, f in enumerate(tk["fs"]):
            ab = fidx.get(int(f))
            if ab is None:
                continue
            r = rows[ab[0]:ab[1]]
            d = np.hypot(r[:, 2] - tk["xs"][k], (r[:, 3] + r[:, 5] / 2) - tk["ys"][k])
            hit = np.flatnonzero(d < 0.5 * np.maximum(tk["ws"][k], r[:, 4]))
            if len(hit):
                got = (tk["xs"][k], tk["ws"][k], int(r[hit[0], 0]), k); break
        if got is None:
            never += 1
        else:
            first_cov_x.append(got)
    print(f"\nCOVERAGE of {len(emerg)} emergence chains by pass-1 tracks ({variant}):")
    print(f"  never covered by any track: {never}")
    if first_cov_x:
        xs = np.asarray([g[0] for g in first_cov_x]); ws = np.asarray([g[1] for g in first_cov_x]); ks = np.asarray([g[3] for g in first_cov_x])
        print(f"  covered: {len(xs)}; first covered at hit index median {np.median(ks):.0f} (0 = at emergence)")
        h, e = np.histogram(xs, bins=[300, 400, 450, 500, 550, 600, 641])
        print("  x where a track first covers the chain:", "  ".join(f"{int(lo)}-{int(hi)}:{c}" for c, lo, hi in zip(h, e[:-1], e[1:])))
        print(f"  box width at first coverage: median {np.median(ws):.0f} px; at emergence median {np.median([tk['ws'][0] for tk in emerg]):.0f} px")
        # was the covering track born there, or an older track (theft)?
        tid_birth = {}
        for tid in set(g[2] for g in first_cov_x):
            r = rows[rows[:, 0] == tid]
            tid_birth[tid] = (r[:, 1].min(), r[r[:, 1].argmin(), 2])
        born_here = sum(1 for g in first_cov_x if abs(tid_birth[g[2]][1] - g[0]) < 60)
        print(f"  covering track born within 60 px of that point: {born_here}; older track (id hand-off / theft): {len(first_cov_x) - born_here}")
        # counting fate of the covering tracks (production events)
        legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (CAM,)))
        ev = {}
        for tid, o, d, rej in con.execute(
                "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, COALESCE(rejected,0) FROM vehicle_events "
                "WHERE camera_id=? AND start_frame BETWEEN ? AND ?", (CAM, f0 - 3000, f1 + 3000)):
            ev.setdefault(int(tid), []).append((legs.get(o, "?"), legs.get(d, "?"), rej))
        fates = Counter()
        for g in first_cov_x:
            evs = ev.get(g[2], [])
            counted = [e for e in evs if e[2] == 0]
            if counted:
                fates["counted " + "/".join(f"{e[0]}->{e[1]}" for e in counted)] += 1
            elif evs:
                fates["rejected " + "/".join(f"{e[0]}->{e[1]}" for e in evs)] += 1
            else:
                fates["NO EVENT"] += 1
        import json as _json
        outp = Path(f"runs/v2_week1/probe_cam4_nb_emergence_{variant}_tids.json")
        outp.write_text(_json.dumps({
            "variant": variant, "never": never,
            "covering": [{"tid": g[2], "first_cov_x": g[0], "first_cov_w": g[1], "hit_index": int(g[3]),
                          "born_here": bool(abs(tid_birth[g[2]][1] - g[0]) < 60),
                          "fate": ("counted " + "/".join(f"{e[0]}->{e[1]}" for e in ev.get(g[2], []) if e[2] == 0))
                                  if any(e[2] == 0 for e in ev.get(g[2], [])) else
                                  ("rejected" if ev.get(g[2]) else "NO EVENT")}
                         for g in first_cov_x]}, indent=0))
        print(f"  wrote {outp}")
        print("  counting fate of the covering tracks:")
        for f, n in fates.most_common(10):
            print(f"    {n:5}  {f}")
        sn_single = fates.get("counted S->N", 0)
        print(f"  => emergences ending in exactly one counted S->N: {sn_single}; never tracked {never}; "
              f"hand-offs {len(first_cov_x) - born_here}; other fates {len(first_cov_x) - sn_single}")


if __name__ == "__main__" and len(sys.argv) > 3 and sys.argv[3] == "coverage":
    coverage(sys.argv[1])
