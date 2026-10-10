"""Why the entry-vs-exit motion check misses and over-fires (2026-10-09, follow-up to
research_entry_exit.py; operator: lay out how and why it fails to catch every instance).

For every journey (entry gate -> exit gate) of a production dump:
  MISSES      exit car != entry car (chains) but the in-box jump < THR: what kind of switch was it
              (the theft census event inside the journey: THEFT / SWAP / EMERGENCE / A ENDS / CHAIN SEAM
              / none found), did the id go unseen across it, how far apart were the two cars' boxes, and
              how far apart were their headings.
  FALSE FLAGS same car (chains) but jump >= THR: what is going on at the jump - a gap in the track,
              the box changing size, another box overlapping, a turn, the far side of the frame.
Read-only. Usage: .venv/Scripts/python.exe -X utf8 scripts/research_entry_exit_why.py PROJ CAM VARIANT [...]
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
from research_entry_exit import APP_S, THROUGH, chain_labels, seg_cross  # noqa: E402
from research_thefts import iou_mat, tlbr  # noqa: E402
from research_track_qc import join_rows, score_track  # noqa: E402

THR = 0.19


def heading(c: np.ndarray, t: np.ndarray) -> float | None:
    if len(c) < 3 or t[-1] == t[0]:
        return None
    v = np.polyfit(t, c, 1)[0]
    return float(np.degrees(np.arctan2(v[1], v[0]))) if np.hypot(*v) > 1e-6 else None


def window(proj: str, cam: int, variant: str) -> list[dict]:
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps, vh = con.execute("SELECT content_hash, fps, height FROM videos WHERE camera_id=?", (cam,)).fetchone()
    gates = [(r[0], np.asarray(json.loads(r[1]), dtype=np.float64))
             for r in con.execute("SELECT cardinal_direction, gate_segment FROM legs WHERE camera_id=?", (cam,))
             if r[1]]
    fps = float(fps)
    pqp = parquet_path(proj, cam, chash, variant)
    rows = np.array(load_dump(tracks_dir(pqp)), dtype=np.float64, copy=True)
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{variant}.json").read_text())
    ev = json.loads(Path(f"runs/v2_week1/thefts_{proj}_{cam}_{variant}.json").read_text())
    ev_by = defaultdict(list)
    for e in ev:
        ev_by[int(e["track"])].append(e)
    join, bb = join_rows(rows, pqp)
    lab = chain_labels(rows, veh)
    # every dump box per frame, for "another box overlaps at the jump"
    by_f = defaultdict(list)
    for r in rows:
        by_f[int(r[1])].append((int(r[0]), tlbr(r)))
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows, join, lab = rows[order], join[order], lab[order]
    ut, st_ = np.unique(rows[:, 0], return_index=True)
    en_ = np.append(st_[1:], len(rows))
    wa = APP_S * fps
    out = []
    for tid, a, b in zip(ut.astype(int), st_, en_):
        if b - a < 6:
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
        lb = lab[a:b][(fr <= fe) & (fr > fe - wa)]
        la = lab[a:b][(fr >= fx) & (fr < fx + wa)]
        lb, la = lb[lb >= 0], la[la >= 0]
        if not len(lb) or not len(la):
            continue
        cb, ca = Counter(lb.tolist()).most_common(1)[0][0], Counter(la.tolist()).most_common(1)[0][0]
        rec = {"track": int(tid), "truth": "SAME" if cb == ca else "DIFFERENT",
               "turn": (ent_g, ext_g) not in THROUGH, "in_box_s": (fx - fe) / fps}
        j = join[a:b]
        ok = j >= 0
        box = np.where(ok[:, None], bb[np.maximum(j, 0)], np.stack([tlbr(x) for x in r]))
        cen = np.stack([(box[:, 0] + box[:, 2]) / 2, (box[:, 1] + box[:, 3]) / 2], axis=1)
        w = box[:, 2] - box[:, 0]
        seg = np.flatnonzero((fr >= fe - wa) & (fr <= fx + wa))
        sig = score_track(fr[seg], cen[seg], w[seg], None, None, fps)["mot_jump"]
        inside = (fr[seg] >= fe) & (fr[seg] <= fx)
        mj = np.where(inside, sig, np.nan)
        rec["jump"] = float(np.nanmax(mj)) if np.isfinite(mj).any() else None
        rec["jump_nan"] = bool(not np.isfinite(mj).any())
        if rec["jump"] is not None:
            k = seg[int(np.nanargmax(mj))]
            fj = int(fr[k])
            rec["gap_at_jump"] = int(fr[k] - fr[k - 1] - 1) if k > 0 else 0
            wb_ = np.median(w[max(k - 5, 0):k]) if k > 0 else w[k]
            wa_ = np.median(w[k:k + 5])
            rec["w_ratio"] = float(max(wa_, wb_) / max(min(wa_, wb_), 1.0))
            others = [x for t2, x in by_f.get(fj, []) if t2 != tid]
            rec["overlap"] = float(iou_mat(box[k][None], np.asarray(others)).max()) if others else 0.0
            rec["y"] = float(cen[k, 1])
            rec["w"] = float(w[k])
        # the census switch inside this journey, if any
        sw = [e for e in ev_by.get(int(tid), []) if fe - wa <= e["f_first_B"] <= fx + wa]
        if sw:
            e = max(sw, key=lambda e: e["kind"] != "CHAIN SEAM")
            rec["kind"] = "SWAP" if e["kind"] == "THEFT" and e["swap_with"] else e["kind"]
            rec["unseen"] = int(e["unseen"])
            ba, bb2 = np.asarray(e["box_A"]), np.asarray(e["box_B"])
            ca_, cb_ = (ba[:2] + ba[2:]) / 2, (bb2[:2] + bb2[2:]) / 2
            rec["ab_dist_w"] = float(np.hypot(*(ca_ - cb_)) / max(e["w"], 1.0))
            rec["iou_ab"] = float(e["iou_ab"])
            # headings of the two chains around the switch
            ha = hb = None
            for key, chain, f0 in (("A", e["A"], e["f_last_A"]), ("B", e["B"], e["f_first_B"])):
                h = np.asarray([x for x in veh[chain] if abs(x[0] - f0) <= fps], dtype=np.float64)
                if len(h) >= 3:
                    hd = heading(np.stack([(h[:, 1] + h[:, 3]) / 2, (h[:, 2] + h[:, 4]) / 2], axis=1), h[:, 0])
                    if key == "A":
                        ha = hd
                    else:
                        hb = hd
            if ha is not None and hb is not None:
                rec["dheading"] = float(abs((ha - hb + 180) % 360 - 180))
        else:
            rec["kind"] = "no census switch"
        out.append(rec)
    return out


def pct(n, d):
    return f"{n} ({n / max(d, 1):.0%})"


def main() -> int:
    proj, cam, variants = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    allm, allf = [], []
    for v in variants:
        recs = window(proj, cam, v)
        Path(f"runs/v2_week1/entry_exit_why_{proj}_{cam}_{v}.json").write_text(json.dumps(recs))
        diff = [r for r in recs if r["truth"] == "DIFFERENT"]
        same = [r for r in recs if r["truth"] == "SAME"]
        miss = [r for r in diff if r["jump"] is None or r["jump"] < THR]
        hit = [r for r in diff if r["jump"] is not None and r["jump"] >= THR]
        ff = [r for r in same if r["jump"] is not None and r["jump"] >= THR]
        allm += miss; allf += ff
        print(f"== {v}: DIFFERENT {len(diff)}: caught {len(hit)}, missed {len(miss)}; SAME {len(same)}: "
              f"false flags {len(ff)}", flush=True)
        for name, grp in (("caught", hit), ("missed", miss)):
            print(f"  {name} by kind: " + ", ".join(f"{k} {n}" for k, n in Counter(r['kind'] for r in grp).most_common()))
    print("\n== ALL WINDOWS: MISSES", len(allm))
    m = allm
    print("  no jump measurable (too few boxes each side of every point in the box):",
          pct(sum(r["jump_nan"] for r in m), len(m)))
    print("  by kind: " + ", ".join(f"{k} {pct(n, len(m))}" for k, n in Counter(r["kind"] for r in m).most_common()))
    real = [r for r in m if r["kind"] in ("THEFT", "SWAP", "EMERGENCE", "A ENDS")]
    if real:
        print(f"  of the {len(real)} real switches missed:")
        print("    unseen across the switch: 0 f " + pct(sum(r["unseen"] == 0 for r in real), len(real)) +
              ", 1-6 f " + pct(sum(0 < r["unseen"] <= 6 for r in real), len(real)) +
              ", > 6 f " + pct(sum(r["unseen"] > 6 for r in real), len(real)))
        d = [r["ab_dist_w"] for r in real]
        print("    distance between the two cars' boxes at the switch (box widths): median "
              f"{np.median(d):.2f}; < 0.5 {pct(sum(x < 0.5 for x in d), len(d))}, 0.5-1 "
              f"{pct(sum(0.5 <= x < 1 for x in d), len(d))}, >= 1 {pct(sum(x >= 1 for x in d), len(d))}")
        h = [r["dheading"] for r in real if "dheading" in r]
        if h:
            print(f"    heading difference between the two cars: < 20 deg {pct(sum(x < 20 for x in h), len(h))}, "
                  f"20-60 {pct(sum(20 <= x < 60 for x in h), len(h))}, >= 60 {pct(sum(x >= 60 for x in h), len(h))}")
        print("    on a turn journey: " + pct(sum(r["turn"] for r in real), len(real)))
    print("\n== ALL WINDOWS: FALSE FLAGS", len(allf))
    f = allf
    print("  gap in the track at the jump: " + pct(sum(r["gap_at_jump"] > 0 for r in f), len(f)) +
          f" (> 6 f {pct(sum(r['gap_at_jump'] > 6 for r in f), len(f))})")
    print("  box size changes >= 1.3x across the jump: " + pct(sum(r["w_ratio"] >= 1.3 for r in f), len(f)))
    print("  another box overlaps (IoU >= 0.1) at the jump: " + pct(sum(r["overlap"] >= 0.1 for r in f), len(f)))
    print("  none of the three: " + pct(sum(r["gap_at_jump"] == 0 and r["w_ratio"] < 1.3 and r["overlap"] < 0.1
                                            for r in f), len(f)))
    print("  on a turn journey: " + pct(sum(r["turn"] for r in f), len(f)))
    print("  a census switch inside the journey anyway (chains say same car at the ends): " +
          ", ".join(f"{k} {n}" for k, n in Counter(r["kind"] for r in f).most_common()))
    print(f"  box width at the jump: median {np.median([r['w'] for r in f]):.0f} px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
