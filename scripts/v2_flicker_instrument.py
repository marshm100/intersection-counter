"""Tier-3 A1+B2 — the FLICKER instrument (kill gate G-A1-i).
docs/plan_t3_a1b2_tubelet_2026-08-13.md — gate numbers pre-declared.

The NO-GT progress meter for the rescore-only stabilizer, run BEFORE any
tracking compute. Donors = confident full tracks from the base dump;
their cache detections are located by frame + center proximity; a
contiguous flicker window per donor ({1, 3, 8} s round-robin, seeded
placement) has its conf suppressed into the sub-activation band — making
the window ANCHORLESS, the diagnosed failing class. Decoys = cache
detections in the same band matched to NO dump track (isolated
background flicker/debris — the v2_tubelet flood class). The stabilizer
runs on the modified stream.

  recovery    suppressed detections re-boosted to >= activation,
              aggregate + per duration bin
  false-boost decoys whose conf the stabilizer raised at all
  parity      row count identical; boost only upward; boosts only on
              sub-floor members (asserted)

Usage:
  py -X utf8 scripts/v2_flicker_instrument.py --camera 2 --variant study_0700
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                              # noqa: E402
import pyarrow.parquet as pq                                    # noqa: E402

from backend.services.two_pass import _camera_parquet           # noqa: E402
from v2_common import fit_motion_residual, load_table, track_points  # noqa: E402
from v2_frag_instrument import pick_donors                      # noqa: E402
from v2_tubelet_stabilize import birth_floor_for, stabilize     # noqa: E402

SEED = 42
DURATIONS = (1.0, 3.0, 8.0)
BAND_LO = 0.11
MAX_DECOYS = 2000
MATCH_FRAC = 0.5      # detection matches a track point within 0.5 * diag


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    args = ap.parse_args()
    cam, variant = args.camera, args.variant
    rng = np.random.default_rng(SEED)

    # ---- load table + parquet ----------------------------------------------
    npz = Path("runs/v2_week1") / f"tracklets_cam{cam}_{variant}.npz"
    t = load_table(npz)
    fps = t["fps"]
    cal = fit_motion_residual(t)
    floor, backend = birth_floor_for(args.project, cam)
    conn = sqlite3.connect(
        f"file:data/projects/{args.project}/project.db?mode=ro", uri=True)
    act = conn.execute(
        "SELECT calib_tracker_activation_threshold FROM cameras "
        "WHERE camera_id=?", (cam,)).fetchone()[0]
    conn.close()
    activation = float(act) if act is not None else 0.25
    band_hi = activation - 0.01

    src_pq = _camera_parquet(args.project, cam, variant)
    tbl = pq.read_table(src_pq)
    frames = tbl["frame_idx"].to_numpy().astype(np.int64)
    x1 = tbl["bbox_x1"].to_numpy(); y1 = tbl["bbox_y1"].to_numpy()
    x2 = tbl["bbox_x2"].to_numpy(); y2 = tbl["bbox_y2"].to_numpy()
    conf = tbl["confidence"].to_numpy().astype(np.float64)
    dcx = (x1 + x2) / 2.0
    dcy = (y1 + y2) / 2.0
    ddiag = np.hypot(x2 - x1, y2 - y1)
    d_lo = np.searchsorted(frames, np.arange(frames.min(), frames.max() + 2))

    def dets_at(f):
        f0 = int(f - frames.min())
        if f0 < 0 or f0 + 1 >= len(d_lo):
            return np.arange(0)
        return np.arange(d_lo[f0], d_lo[f0 + 1])

    # ---- track coverage per detection (for decoys) --------------------------
    # bucket ALL dump points by frame, mark detections near any track point
    rows = t["rows"]
    tr_f = rows[:, 1].astype(np.int64)
    order = np.argsort(tr_f, kind="stable")
    tr_f = tr_f[order]
    tr_x = rows[order, 2]; tr_y = rows[order, 3]
    covered = np.zeros(len(frames), bool)
    t_lo = np.searchsorted(tr_f, np.arange(frames.min(), frames.max() + 2))
    for f in range(int(frames.min()), int(frames.max()) + 1):
        di = dets_at(f)
        f0 = f - int(frames.min())
        ti0, ti1 = t_lo[f0], t_lo[f0 + 1]
        if not len(di) or ti0 == ti1:
            continue
        dx = dcx[di][:, None] - tr_x[ti0:ti1][None, :]
        dy = dcy[di][:, None] - tr_y[ti0:ti1][None, :]
        near = (np.hypot(dx, dy) <= MATCH_FRAC * ddiag[di][:, None]).any(1)
        covered[di[near]] = True

    # ---- donors + suppression ----------------------------------------------
    donors = pick_donors(t, rng)
    mod_conf = conf.copy()
    suppressed = []                    # (row_idx, duration)
    per_donor = []
    for k, d in enumerate(donors):
        tr = track_points(t, int(d))
        dur = DURATIONS[k % len(DURATIONS)]
        f0, f1 = tr[0, 1], tr[-1, 1]
        span_s = (f1 - f0) / fps
        if span_s < dur + 4.0:
            continue
        w0 = f0 + rng.uniform(2.0, span_s - dur - 2.0) * fps
        w1 = w0 + dur * fps
        hit = []
        for p in tr:
            if not (w0 <= p[1] <= w1):
                continue
            di = dets_at(int(p[1]))
            if not len(di):
                continue
            dd = np.hypot(dcx[di] - p[2], dcy[di] - p[3])
            j = int(np.argmin(dd))
            if dd[j] <= MATCH_FRAC * ddiag[di[j]]:
                hit.append(int(di[j]))
        if len(hit) < 3:
            continue
        for i in hit:
            mod_conf[i] = rng.uniform(BAND_LO, band_hi)
            suppressed.append((i, dur))
        per_donor.append((int(d), dur, len(hit)))

    # ---- decoys -------------------------------------------------------------
    sup_set = {i for i, _ in suppressed}
    decoy_pool = np.flatnonzero(~covered & (conf < activation))
    decoy_pool = np.array([i for i in decoy_pool if i not in sup_set])
    decoys = (rng.choice(decoy_pool, MAX_DECOYS, replace=False)
              if len(decoy_pool) > MAX_DECOYS else decoy_pool)

    # ---- run the stabilizer -------------------------------------------------
    new_conf, census = stabilize(frames.astype(np.float64), dcx, dcy, ddiag,
                                 mod_conf, fps, cal, floor)
    assert len(new_conf) == len(frames)
    assert np.all(new_conf >= mod_conf - 1e-9), "boost must be upward-only"
    changed = np.flatnonzero(np.abs(new_conf - mod_conf) > 1e-9)
    assert np.all(mod_conf[changed] < floor), "boosts only on sub-floor dets"

    # ---- metrics ------------------------------------------------------------
    rec_by = defaultdict(lambda: [0, 0])
    for i, dur in suppressed:
        rec_by[dur][1] += 1
        if new_conf[i] >= activation:
            rec_by[dur][0] += 1
    tot_hit = sum(v[0] for v in rec_by.values())
    tot_sup = sum(v[1] for v in rec_by.values())
    recovery = tot_hit / tot_sup if tot_sup else 0.0
    by_bin = {f"{d:g}s": (v[0] / v[1] if v[1] else None)
              for d, v in sorted(rec_by.items())}
    fb = int(np.sum(new_conf[decoys] > mod_conf[decoys] + 1e-9)) if len(decoys) else 0
    fb_rate = fb / len(decoys) if len(decoys) else 0.0

    out = {"camera": cam, "variant": variant, "backend": backend,
           "birth_floor": floor, "activation": activation,
           "donors_used": len(per_donor), "suppressed_dets": tot_sup,
           "recovery": round(recovery, 4),
           "recovery_by_duration": {k: (round(v, 4) if v is not None else None)
                                    for k, v in by_bin.items()},
           "decoys": int(len(decoys)), "false_boosted": fb,
           "false_boost_rate": round(fb_rate, 4),
           "stabilizer_census": census,
           "cal": {k: v for k, v in cal.items() if k != "table"}}
    dst = Path("runs/v2_week1") / f"flicker_cam{cam}_{variant}.json"
    dst.write_text(json.dumps(out, indent=1))
    print(f"[flicker] cam{cam} {variant}: donors={len(per_donor)} "
          f"suppressed={tot_sup} recovery={recovery:.3f} by_bin=" +
          " ".join(f"{k}:{v if v is None else round(v, 3)}"
                   for k, v in by_bin.items()) +
          f" | decoys={len(decoys)} false_boost={fb_rate:.4f}"
          f" | census={census}")
    print(f"[flicker] -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
