"""Pipeline-V2 B1 — the synthetic CONCURRENT-TWIN instrument
(docs/plan_b1_twin_isolation_2026-08-12.md, gate G-B1i): the NO-GT progress
meter for the structural twin channel. v2_frag_instrument.py measures
SEQUENTIAL stitching (cut-and-rejoin); this measures the other phenomenon —
a detector double-box producing two SIMULTANEOUS tracklets of one vehicle.

Method: donors = the window's own confident both-gate tracklets (the frag
instrument's quality gates), split into disjoint TWIN-host and DECOY-host
halves. Twin hosts get a clone modeling the double-box: co-life log-uniform
1-10 s, constant offset U(0.05,0.35)*bbox-diag clipped to same-size IoU
>= 0.30, per-frame jitter N(0, max(1px, 0.03*diag)), size *U(0.9,1.1) with
per-frame N(1, 0.02), conf *U(0.55,0.9), 10% frame drop (>= 3 common frames
guaranteed). Decoy hosts get the documented channel-killers instead:
queued-FOLLOWER (same path, time-lag U(0.8,2.0) s — behind by v*tau) or
lane-NEIGHBOR (perpendicular offset U(2.5,4.0)*zv_radius, same motion).
Clones are APPENDED (originals untouched), the calibration is re-fit on the
augmented table (the v2_reid_dump order), and twin_pairs_structural runs.

Score:
  twin recall        — injected (donor, clone) pairs recovered, aggregate +
                       per co-life bin {1-2, 2-5, 5-10 s};
  decoy false-flag   — decoys appearing in ANY returned pair, per class
                       (either class flagged = the follower/neighbor weld
                       that killed the four dead channels);
  clean-window pairs — channel output on the untouched table (context);
  seq_overlap_frac   — clean pairs that are also stitch_greedy links
                       (DIAGNOSTIC only: both verdicts assert "same
                       vehicle"; high overlap predicts re-derived G-A1).

Usage:
  py -X utf8 scripts/v2_twin_instrument.py runs/v2_week1/tracklets_cam2_study_0700.npz
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                                  # noqa: E402
from v2_common import (fit_motion_residual, load_table,             # noqa: E402
                       table_from_pieces, track_points,
                       twin_pairs_structural)
from v2_frag_instrument import pick_donors                          # noqa: E402

SEED = 42
COLIFE_BINS = ((1.0, 2.0), (2.0, 5.0), (5.0, 10.0))
MIN_COMMON = 3


def _same_size_iou(w: float, h: float, dx: float, dy: float) -> float:
    iw = max(0.0, w - abs(dx))
    ih = max(0.0, h - abs(dy))
    inter = iw * ih
    return inter / (2.0 * w * h - inter) if inter > 0 else 0.0


def _segment(tr: np.ndarray, fps: float, life_s: float, rng) -> np.ndarray | None:
    """A co-life window of the donor's rows, uniformly placed."""
    fr = tr[:, 1]
    span = (fr[-1] - fr[0]) / fps
    if span <= life_s + 0.5:
        return None
    s0 = fr[0] + rng.uniform(0.0, span - life_s) * fps
    seg = tr[(fr >= s0) & (fr <= s0 + life_s * fps)]
    return seg.copy() if len(seg) >= MIN_COMMON else None


def make_twin(tr: np.ndarray, fps: float, rng):
    """-> (clone_rows, colife_s) or None. The detector double-box model."""
    life = float(math.exp(rng.uniform(math.log(1.0), math.log(10.0))))
    seg = _segment(tr, fps, life, rng)
    if seg is None:
        return None
    w, h = float(seg[:, 4].mean()), float(seg[:, 5].mean())
    diag = math.hypot(w, h)
    theta = rng.uniform(0.0, 2.0 * math.pi)
    mag = rng.uniform(0.05, 0.35) * diag
    while mag > 1.0 and _same_size_iou(
            w, h, mag * math.cos(theta), mag * math.sin(theta)) < 0.30:
        mag *= 0.9                       # clip to the phenomenon (IoU >= 0.30)
    dx, dy = mag * math.cos(theta), mag * math.sin(theta)
    sigma = max(1.0, 0.03 * diag)
    seg[:, 2] += dx + rng.normal(0.0, sigma, len(seg))
    seg[:, 3] += dy + rng.normal(0.0, sigma, len(seg))
    size_f = rng.uniform(0.9, 1.1)
    seg[:, 4] *= size_f * np.maximum(rng.normal(1.0, 0.02, len(seg)), 0.5)
    seg[:, 5] *= size_f * np.maximum(rng.normal(1.0, 0.02, len(seg)), 0.5)
    seg[:, 6] *= rng.uniform(0.55, 0.9)
    keep = rng.random(len(seg)) >= 0.10          # detector flicker
    if keep.sum() < MIN_COMMON:                  # >= 3 common frames pinned
        keep[:MIN_COMMON] = True
    return seg[keep], life


def make_follower(tr: np.ndarray, fps: float, rng):
    """Queued/tailing follower: same path, time-lagged tau — at any common
    frame it sits where the donor was tau seconds AGO (headway, not twin)."""
    life = float(rng.uniform(3.0, 10.0))
    seg = _segment(tr, fps, life, rng)
    if seg is None:
        return None
    tau = rng.uniform(0.8, 2.0)
    seg[:, 1] += round(tau * fps)                # keep the frame grid
    sigma = max(1.0, 0.03 * math.hypot(seg[:, 4].mean(), seg[:, 5].mean()))
    seg[:, 2] += rng.normal(0.0, sigma, len(seg))
    seg[:, 3] += rng.normal(0.0, sigma, len(seg))
    return seg, life - tau                       # actual co-life with donor


def make_neighbor(tr: np.ndarray, fps: float, zv_radius: float, rng):
    """Lane neighbor: constant PERPENDICULAR offset 2.5-4.0 * zv_radius,
    same motion — the adjacent-lane platoon partner."""
    life = float(rng.uniform(3.0, 10.0))
    seg = _segment(tr, fps, life, rng)
    if seg is None:
        return None
    v = seg[-1, 2:4] - seg[0, 2:4]
    n = math.hypot(*v)
    if n < 1e-6:
        return None                              # stationary segment: skip
    px, py = -v[1] / n, v[0] / n
    off = rng.uniform(2.5, 4.0) * zv_radius * (1 if rng.random() < 0.5 else -1)
    sigma = max(1.0, 0.03 * math.hypot(seg[:, 4].mean(), seg[:, 5].mean()))
    seg[:, 2] += px * off + rng.normal(0.0, sigma, len(seg))
    seg[:, 3] += py * off + rng.normal(0.0, sigma, len(seg))
    return seg, life


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    args = ap.parse_args()
    t = load_table(args.table)
    fps = t["fps"]
    rng = np.random.default_rng(SEED)
    donors = pick_donors(t, rng)
    cal0 = fit_motion_residual(t)

    # ---- context on the CLEAN table: channel output + seq overlap ----------
    clean_pairs = set(twin_pairs_structural(t, cal0))
    from v2_baseline_greedy import stitch_greedy
    links, _chains = stitch_greedy(t, cal0)
    link_pairs = {(min(i, j), max(i, j)) for i, j in links}
    seq_overlap = (len(clean_pairs & link_pairs) / len(clean_pairs)
                   if clean_pairs else 0.0)

    # ---- injection: disjoint twin / decoy halves ---------------------------
    perm = rng.permutation(donors)
    half = len(perm) // 2
    twin_hosts, decoy_hosts = perm[:half], perm[half:]
    pieces = [track_points(t, i).copy() for i in range(t["n"])]
    injected: dict[int, tuple[int, str, float]] = {}  # new_idx -> (donor, kind, colife)
    idx = t["n"]
    for d in twin_hosts:
        r = make_twin(track_points(t, int(d)), fps, rng)
        if r is None:
            continue
        clone, life = r
        clone[:, 0] = 900000 + idx
        pieces.append(clone)
        injected[idx] = (int(d), "twin", life)
        idx += 1
    for k, d in enumerate(decoy_hosts):
        kind = "follower" if k % 2 == 0 else "neighbor"
        r = (make_follower(track_points(t, int(d)), fps, rng)
             if kind == "follower"
             else make_neighbor(track_points(t, int(d)), fps,
                                cal0["zv_radius"], rng))
        if r is None:
            continue
        clone, life = r
        clone[:, 0] = 900000 + idx
        pieces.append(clone)
        injected[idx] = (int(d), kind, life)
        idx += 1

    t2 = table_from_pieces(pieces, fps, t["meta"])
    cal2 = fit_motion_residual(t2)               # the v2_reid_dump order
    got = set(twin_pairs_structural(t2, cal2))
    flagged: dict[int, set] = {}
    for a, b in got:
        flagged.setdefault(a, set()).add(b)
        flagged.setdefault(b, set()).add(a)

    # ---- score -------------------------------------------------------------
    twins = {i: v for i, v in injected.items() if v[1] == "twin"}
    hits = {i for i, (d, _k, _l) in twins.items()
            if (min(d, i), max(d, i)) in got}
    by_bin = {}
    for lo, hi in COLIFE_BINS:
        ids = [i for i, (_d, _k, life) in twins.items() if lo <= life < hi]
        by_bin[f"{lo:g}-{hi:g}s"] = {
            "n": len(ids),
            "recall": (sum(1 for i in ids if i in hits) / len(ids))
            if ids else None}
    decoy_stats = {}
    for kind in ("follower", "neighbor"):
        ids = [i for i, v in injected.items() if v[1] == kind]
        ff = [i for i in ids if flagged.get(i)]
        decoy_stats[kind] = {"n": len(ids), "false_flagged": len(ff),
                             "rate": len(ff) / len(ids) if ids else None}
    n_decoys = sum(v["n"] for v in decoy_stats.values())
    n_ff = sum(v["false_flagged"] for v in decoy_stats.values())

    out = {"table": args.table,
           "cal_clean": {k: v for k, v in cal0.items() if k != "table"},
           "clean_pairs": len(clean_pairs),
           "seq_overlap_frac": round(seq_overlap, 4),
           "twins_injected": len(twins),
           "twin_recall": round(len(hits) / len(twins), 4) if twins else None,
           "twin_recall_by_colife": by_bin,
           "decoys": decoy_stats,
           "decoy_false_flag_rate": round(n_ff / n_decoys, 4)
           if n_decoys else None,
           "pairs_on_augmented": len(got)}
    stem = Path(args.table).stem.replace("tracklets_", "")
    dst = Path("runs/v2_week1") / f"twin_{stem}.json"
    dst.write_text(json.dumps(out, indent=1))
    print(f"[twin] {stem}: clean_pairs={len(clean_pairs)} "
          f"seq_overlap={seq_overlap:.2f} | twins={len(twins)} "
          f"recall={out['twin_recall']} by_bin=" +
          " ".join(f"{k}:{v['recall']}" for k, v in by_bin.items()) +
          f" | decoys={n_decoys} false_flag={out['decoy_false_flag_rate']} "
          f"(fol={decoy_stats['follower']['rate']} "
          f"nb={decoy_stats['neighbor']['rate']})")
    print(f"[twin] -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
