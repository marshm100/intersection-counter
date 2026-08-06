"""Pipeline-V2 D1b — the synthetic-fragmentation instrument
(plan_v2_week1_derisk §D1): the NO-GT progress meter for any stitcher.

Method: take the window's own confident both-gate tracklets (donors), cut
each into two fragments around a gap of {0.5, 2, 10, 60} seconds (60 s cut
at the donor's minimum-speed point — the red-light case), drop the gap
points, and put the fragments back into the FULL tracklet soup (all other
tracklets = live decoys). Run a stitcher over everything. Score:

  recall  — donor pairs correctly rejoined (A's chain continues into B),
  purity  — 1 - donor fragments welded to a NON-partner (over-merge; the
            global-solver failure mode; tripwire >= 0.98 per plan).

Usage:
  py -X utf8 scripts/v2_frag_instrument.py runs/v2_week1/tracklets_cam2_study_0700.npz --stitcher greedy
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import fit_motion_residual, load_table  # noqa: E402

GAP_CLASSES = (0.5, 2.0, 10.0, 60.0)
MIN_DONOR_DUR_S = 12.0
MIN_FRAG_S = 2.0
MIN_FRAG_PTS = 6
MAX_DONORS = 150
SEED = 42
KIN = 8


def pick_donors(t: dict, rng) -> np.ndarray:
    dur = (t["f1"] - t["f0"]) / t["fps"]
    q_len = np.quantile(t["n_pts"], 0.5)
    q_conf = np.quantile(t["mean_conf"], 0.5)
    ok = np.where((t["tag"] == 0) & (dur >= MIN_DONOR_DUR_S)
                  & (t["n_pts"] >= q_len) & (t["mean_conf"] >= q_conf))[0]
    if len(ok) > MAX_DONORS:
        ok = rng.choice(ok, MAX_DONORS, replace=False)
    return np.sort(ok)


def rolling_speed(tr: np.ndarray, fps: float) -> np.ndarray:
    xy = tr[:, 2:4]
    d = np.hypot(*np.diff(xy, axis=0).T) * fps
    return np.concatenate([[d[0] if len(d) else 0.0], d])


def cut_donor(tr: np.ndarray, fps: float, gap_s: float, rng):
    """-> (fragA_rows, fragB_rows) or None if the donor can't host this gap."""
    fr = tr[:, 1]
    dur = (fr[-1] - fr[0]) / fps
    if dur < gap_s + 2 * MIN_FRAG_S:
        return None
    if gap_s >= 30.0:
        sp = rolling_speed(tr, fps)
        lo = np.searchsorted(fr, fr[0] + MIN_FRAG_S * fps)
        hi = np.searchsorted(fr, fr[-1] - (gap_s + MIN_FRAG_S) * fps)
        if hi <= lo:
            return None
        c = lo + int(np.argmin(sp[lo:hi]))
    else:
        lo = np.searchsorted(fr, fr[0] + MIN_FRAG_S * fps)
        hi = np.searchsorted(fr, fr[-1] - (gap_s + MIN_FRAG_S) * fps)
        if hi <= lo:
            return None
        c = int(rng.integers(lo, hi))
    gap_end_f = fr[c] + gap_s * fps
    b0 = int(np.searchsorted(fr, gap_end_f))
    fragA, fragB = tr[:c], tr[b0:]
    if (len(fragA) < MIN_FRAG_PTS or len(fragB) < MIN_FRAG_PTS
            or (fragA[-1, 1] - fragA[0, 1]) < MIN_FRAG_S * fps
            or (fragB[-1, 1] - fragB[0, 1]) < MIN_FRAG_S * fps):
        return None
    return fragA, fragB


def rebuild_table(t: dict, donor_cuts: dict[int, tuple]) -> tuple[dict, dict]:
    """New table with each cut donor replaced by its two fragments.
    Returns (table2, fragmap) where fragmap[new_index] = (donor_idx, 'A'|'B')."""
    fps = t["fps"]
    pieces, fragmap, feat_rows = [], {}, []
    idx = 0
    for i in range(t["n"]):
        tr = t["rows"][int(t["starts"][i]):int(t["ends"][i])]
        if i in donor_cuts:
            for part, frag in zip("AB", donor_cuts[i]):
                pieces.append(frag)
                fragmap[idx] = (i, part)
                feat_rows.append(frag)
                idx += 1
        else:
            pieces.append(tr)
            feat_rows.append(tr)
            idx += 1
    rows = np.concatenate(pieces)
    starts, ends = [], []
    off = 0
    for p in pieces:
        starts.append(off)
        off += len(p)
        ends.append(off)
    t2 = {"rows": rows, "starts": np.array(starts), "ends": np.array(ends),
          "fps": fps, "meta": t["meta"], "n": len(pieces)}
    n = t2["n"]
    for k in ("track_id", "n_pts", "f0", "f1", "x0", "y0", "x1", "y1",
              "vx0", "vy0", "vx1", "vy1", "mean_conf", "mean_area"):
        t2[k] = np.zeros(n)
    for i, p in enumerate(pieces):
        fr, xy = p[:, 1], p[:, 2:4]
        t2["track_id"][i] = i
        t2["n_pts"][i] = len(p)
        t2["f0"][i], t2["f1"][i] = fr[0], fr[-1]
        t2["x0"][i], t2["y0"][i] = xy[0]
        t2["x1"][i], t2["y1"][i] = xy[-1]
        for head, (vk_x, vk_y) in ((True, ("vx0", "vy0")), (False, ("vx1", "vy1"))):
            k = min(KIN, len(fr))
            sl = slice(0, k) if head else slice(len(fr) - k, len(fr))
            f, q = fr[sl], xy[sl]
            if k >= 2 and f[-1] > f[0]:
                tt = (f - f[0]) / fps
                den = ((tt - tt.mean()) ** 2).sum() or 1e-9
                t2[vk_x][i] = ((tt - tt.mean()) * (q[:, 0] - q[:, 0].mean())).sum() / den
                t2[vk_y][i] = ((tt - tt.mean()) * (q[:, 1] - q[:, 1].mean())).sum() / den
        t2["mean_conf"][i] = p[:, 6].mean()
        t2["mean_area"][i] = (p[:, 4] * p[:, 5]).mean()
    return t2, fragmap


def score(chains: list[list[int]], fragmap: dict) -> dict:
    """recall: donor pairs rejoined. cut_precision: of links made AT the cut
    endpoints (A's end / B's start), the fraction that are the true rejoin —
    the over-merge tripwire. Ambient links at the fragments' ORIGINAL outer
    endpoints are the baseline linking rate, reported separately."""
    nxt, prv = {}, {}
    for ch in chains:
        for a, b in zip(ch, ch[1:]):
            nxt[a] = b
            prv[b] = a
    donors = sorted({d for d, _ in fragmap.values()})
    a_of = {d: i for i, (d, p) in fragmap.items() if p == "A"}
    b_of = {d: i for i, (d, p) in fragmap.items() if p == "B"}
    hits = cut_welds = 0
    for d in donors:
        A, B = a_of[d], b_of[d]
        got = nxt.get(A)
        if got == B:
            hits += 1
        elif got is not None:
            cut_welds += 1          # A's cut end welded elsewhere
        gin = prv.get(B)
        if gin is not None and gin != A:
            cut_welds += 1          # B's cut start received a stranger
    frag_ids = set(fragmap)
    ambient = sum(1 for ch in chains for a, b in zip(ch, ch[1:])
                  if (b in frag_ids and fragmap[b][1] == "A")
                  or (a in frag_ids and fragmap[a][1] == "B"))
    denom = hits + cut_welds
    return {"donors": len(donors),
            "recall": hits / len(donors) if donors else None,
            "cut_welds": cut_welds,
            "cut_precision": hits / denom if denom else 1.0,
            "ambient_outer_links": ambient}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("--stitcher", default="greedy",
                    choices=["greedy", "mcf", "assign"])
    args = ap.parse_args()
    t = load_table(args.table)
    rng = np.random.default_rng(SEED)
    donors = pick_donors(t, rng)
    cal = fit_motion_residual(t)

    if args.stitcher == "greedy":
        from v2_baseline_greedy import stitch_greedy
        def run(tbl):
            return stitch_greedy(tbl, cal)[1]
    elif args.stitcher == "mcf":
        from v2_assemble import stitch_mcf
        def run(tbl):
            return stitch_mcf(tbl, cal)[1]
    else:
        from v2_assemble import stitch_assign
        from v2_common import chains_from_links
        def run(tbl):
            links, _kept, _dropped = stitch_assign(tbl, cal)
            return chains_from_links(tbl["n"], links)

    out = {"table": args.table, "stitcher": args.stitcher,
           "cal": {k: v for k, v in cal.items() if k != "table"},
           "calibration": cal["table"],
           "gap_classes": {}}
    for g in GAP_CLASSES:
        rng_g = np.random.default_rng(SEED + int(g * 10))
        cuts = {}
        for d in donors:
            tr = t["rows"][int(t["starts"][d]):int(t["ends"][d])]
            c = cut_donor(tr, t["fps"], g, rng_g)
            if c is not None:
                cuts[int(d)] = c
        if not cuts:
            out["gap_classes"][str(g)] = {"donors": 0}
            continue
        t2, fragmap = rebuild_table(t, cuts)
        chains = run(t2)
        s = score(chains, fragmap)
        out["gap_classes"][str(g)] = s
        print(f"[frag] gap={g:>5}s donors={s['donors']:>3} "
              f"recall={s['recall']:.3f} cut_precision={s['cut_precision']:.3f} "
              f"(cut_welds={s['cut_welds']} ambient={s['ambient_outer_links']})")
    dst = Path("runs/v2_week1") / (
        f"frag_{Path(args.table).stem.replace('tracklets_', '')}_{args.stitcher}.json")
    dst.write_text(json.dumps(out, indent=1))
    print(f"[frag] -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
