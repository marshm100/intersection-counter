"""Tier-3 A1+B2 — tubelet stabilization, RESCORE-ONLY iteration 1.
docs/plan_t3_a1b2_tubelet_2026-08-13.md — gates pre-declared there.

Cache-in / cache-out: reads a detection-cache parquet, links raw
detections into tubelets (the retired v2_tubelet matcher shape + the B2
zero-velocity hypothesis), and raises the confidence of sub-birth-floor
members of STRUCTURALLY ELIGIBLE tubelets to the camera's effective
birth floor + 0.02. Nothing else changes: row count, order, and every
non-conf column are byte-preserved. BoT-SORT/ByteTrack still do ALL
tracking on the output variant.

The failing class is ANCHORLESS (orphan clusters with conf_max < 0.25),
so eligibility is structural — span >= 1.5 s, >= 8 members, density
>= 0.5/frame, motion-coherent (net displacement >= own bbox diagonal OR
ZV-stationary) — never anchor-required. The false-birth bound is the
flicker instrument's decoy gate (G-A1-i), not an anchor rule.

Usage:
  py -X utf8 scripts/v2_tubelet_stabilize.py --camera 2 --variant study_0700
  # writes a1_study_0700.parquet + .meta.json next to the source cache
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                              # noqa: E402
import pyarrow as pa                                            # noqa: E402
import pyarrow.parquet as pq                                    # noqa: E402

from backend.services.two_pass import _camera_parquet           # noqa: E402
from v2_common import fit_motion_residual, load_table           # noqa: E402

V_EMA = 0.5              # the v2_tubelet velocity smoothing (proven shape)
GATE_DIAG = 0.7          # gate = 0.7*diag + 0.6*|v|*dt  (v2_tubelet:44-52)
GATE_VEL = 0.6
COAST_MOVING_S = 1.0     # v2_tubelet T_MISS_S
COAST_STOPPED_S = 3.0    # the fit_motion_residual stopped-run bound
ELIG_SPAN_S = 1.5        # v2_tubelet MIN_SPAN_S
ELIG_MEMBERS = 8         # v2_tubelet MIN_HITS
ELIG_DENSITY = 0.5       # members per frame over the span
BOOST_EPS = 0.02

_SCHEMA = pa.schema([
    ("frame_idx", pa.uint32()), ("bbox_x1", pa.float32()),
    ("bbox_y1", pa.float32()), ("bbox_x2", pa.float32()),
    ("bbox_y2", pa.float32()), ("confidence", pa.float32()),
    ("class_id", pa.uint8())])


def birth_floor_for(project: str, camera: int) -> tuple[float, str]:
    """The camera's EFFECTIVE birth threshold, backend-derived (never
    hardcoded per camera): botsort new_track_thresh (calib or wrapper
    default 0.30); bytetrack activation + 0.1 (supervision det_thresh)."""
    conn = sqlite3.connect(f"file:data/projects/{project}/project.db?mode=ro",
                           uri=True)
    row = conn.execute(
        "SELECT calib_pass1_backend, calib_new_track_thresh, "
        "calib_tracker_activation_threshold FROM cameras WHERE camera_id=?",
        (camera,)).fetchone()
    conn.close()
    backend = (row[0] or "bytetrack").lower()
    if backend.startswith("botsort"):
        return (float(row[1]) if row[1] is not None else 0.30), backend
    act = float(row[2]) if row[2] is not None else 0.25
    return act + 0.10, backend


def stabilize(frames: np.ndarray, cx: np.ndarray, cy: np.ndarray,
              diag: np.ndarray, conf: np.ndarray, fps: float, cal: dict,
              birth_floor: float):
    """Core linking + rescore. Returns (new_conf, census). Arrays are the
    full frame-sorted detection stream; only conf is ever modified."""
    v_stop, zv_radius = cal["v_stop"], cal["zv_radius"]
    new_conf = conf.copy()
    n = len(frames)
    # frame -> row-range index
    uniq, starts = np.unique(frames, return_index=True)
    ends = np.append(starts[1:], n)

    # open tubelet state (parallel lists)
    tx, ty, tvx, tvy, tlf, tdiag = [], [], [], [], [], []
    tmembers, tconfmax, tx0, ty0, tpath, tf0 = [], [], [], [], [], []
    closed = []
    boosted = 0
    eligible_ct = 0

    def close(k):
        nonlocal boosted, eligible_ct
        members = tmembers[k]
        span_f = tlf[k] - tf0[k]
        span_s = span_f / fps
        cnt = len(members)
        ok = (span_s >= ELIG_SPAN_S and cnt >= ELIG_MEMBERS
              and cnt / (span_f + 1) >= ELIG_DENSITY)
        if ok:
            # ITERATION 2 (plan doc, declared before re-run): displacement
            # coherence ONLY. The ZV-stationary eligibility arm admitted
            # static debris (decoy false-boost 0.61, 25% of the stream
            # boosted — the v2_tubelet flood at detection level). B2 lives
            # in the LINKING (zv_radius gate + stationary coast): a queued
            # vehicle drives in and eventually out, so its tubelet passes
            # displacement; a fence post never does.
            disp = float(np.hypot(tx[k] - tx0[k], ty[k] - ty0[k]))
            mdiag = float(np.mean(diag[members]))
            ok = disp >= mdiag
        if ok:
            eligible_ct += 1
            for i in members:
                if new_conf[i] < birth_floor:
                    new_conf[i] = birth_floor + BOOST_EPS
                    boosted += 1
        closed.append(cnt)

    for fi in range(len(uniq)):
        f = float(uniq[fi])
        lo, hi = int(starts[fi]), int(ends[fi])
        didx = np.arange(lo, hi)
        # close over-coasted tubelets first
        if tx:
            keep = []
            for k in range(len(tx)):
                gap_s = (f - tlf[k]) / fps
                speed = float(np.hypot(tvx[k], tvy[k]))
                coast = COAST_STOPPED_S if speed < v_stop else COAST_MOVING_S
                if gap_s > coast:
                    close(k)
                else:
                    keep.append(k)
            if len(keep) != len(tx):
                for lst in (tx, ty, tvx, tvy, tlf, tdiag, tmembers,
                            tconfmax, tx0, ty0, tpath, tf0):
                    lst[:] = [lst[k] for k in keep]
        # match
        matched_d = set()
        if tx and len(didx):
            T = len(tx)
            atx = np.array(tx); aty = np.array(ty)
            avx = np.array(tvx); avy = np.array(tvy)
            alf = np.array(tlf); adg = np.array(tdiag)
            dt = (f - alf) / fps
            px = atx + avx * dt
            py = aty + avy * dt
            dxs = cx[didx][None, :] - px[:, None]
            dys = cy[didx][None, :] - py[:, None]
            dist = np.hypot(dxs, dys)
            speed = np.hypot(avx, avy)
            gate = GATE_DIAG * adg + GATE_VEL * speed * dt
            gate = np.where(speed < v_stop, np.maximum(gate, zv_radius), gate)
            cost = dist / np.maximum(gate, 4.0)[:, None]
            cost[cost > 1.0] = np.inf
            order = np.argsort(cost, axis=None)
            used_t = set()
            D = len(didx)
            for flat in order:
                if not np.isfinite(cost.flat[flat]):
                    break
                k, j = divmod(int(flat), D)
                if k in used_t or j in matched_d:
                    continue
                used_t.add(k)
                matched_d.add(j)
                i = int(didx[j])
                dts = (f - tlf[k]) / fps
                if dts > 0:
                    vnx = (cx[i] - tx[k]) / dts
                    vny = (cy[i] - ty[k]) / dts
                    tvx[k] = V_EMA * tvx[k] + (1 - V_EMA) * vnx
                    tvy[k] = V_EMA * tvy[k] + (1 - V_EMA) * vny
                tpath[k] += float(np.hypot(cx[i] - tx[k], cy[i] - ty[k]))
                tx[k], ty[k] = float(cx[i]), float(cy[i])
                tlf[k] = f
                tdiag[k] = float(diag[i])
                tconfmax[k] = max(tconfmax[k], float(conf[i]))
                tmembers[k].append(i)
        # births
        for j in range(len(didx)):
            if j in matched_d:
                continue
            i = int(didx[j])
            tx.append(float(cx[i])); ty.append(float(cy[i]))
            tvx.append(0.0); tvy.append(0.0)
            tlf.append(f); tdiag.append(float(diag[i]))
            tmembers.append([i]); tconfmax.append(float(conf[i]))
            tx0.append(float(cx[i])); ty0.append(float(cy[i]))
            tpath.append(0.0); tf0.append(f)
    for k in range(len(tx)):
        close(k)
    census = {"tubelets": len(closed), "eligible": eligible_ct,
              "boosted_dets": int(boosted),
              "dets": int(n),
              "boosted_frac": round(boosted / max(n, 1), 4)}
    return new_conf, census


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--out-prefix", default="a1")
    args = ap.parse_args()
    cam, variant = args.camera, args.variant

    src_pq = _camera_parquet(args.project, cam, variant)
    t = pq.read_table(src_pq)
    frames = t["frame_idx"].to_numpy()
    x1 = t["bbox_x1"].to_numpy(); y1 = t["bbox_y1"].to_numpy()
    x2 = t["bbox_x2"].to_numpy(); y2 = t["bbox_y2"].to_numpy()
    conf = t["confidence"].to_numpy()
    cls = t["class_id"].to_numpy()
    assert np.all(np.diff(frames.astype(np.int64)) >= 0), "cache not frame-sorted"
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    diag = np.hypot(x2 - x1, y2 - y1)

    npz = Path("runs/v2_week1") / f"tracklets_cam{cam}_{variant}.npz"
    if not npz.exists():
        print(f"missing tracklet table {npz} — run v2_dump_graph first")
        return 1
    cal = fit_motion_residual(load_table(npz))
    conn = sqlite3.connect(
        f"file:data/projects/{args.project}/project.db?mode=ro", uri=True)
    fps = float(conn.execute(
        "SELECT fps FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (cam,)).fetchone()[0])
    conn.close()
    floor, backend = birth_floor_for(args.project, cam)

    new_conf, census = stabilize(frames, cx, cy, diag, conf, fps, cal, floor)

    out_variant = f"{args.out_prefix}_{variant}"
    out_pq = src_pq.with_name(f"{out_variant}.parquet")
    out_tbl = pa.table({"frame_idx": frames.astype(np.uint32),
                        "bbox_x1": x1.astype(np.float32),
                        "bbox_y1": y1.astype(np.float32),
                        "bbox_x2": x2.astype(np.float32),
                        "bbox_y2": y2.astype(np.float32),
                        "confidence": new_conf.astype(np.float32),
                        "class_id": cls.astype(np.uint8)}, schema=_SCHEMA)
    pq.write_table(out_tbl, out_pq, compression="zstd")
    src_meta = json.loads(src_pq.with_suffix(".meta.json").read_text())
    meta = {**src_meta,
            "a1_stabilizer": {
                "version": "a1_rescore_v1", "source_variant": variant,
                "backend": backend, "birth_floor": floor,
                "cal": {k: v for k, v in cal.items() if k != "table"},
                **census}}
    out_pq.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))
    print(f"[a1] cam{cam} {variant} -> {out_variant}: "
          f"tubelets={census['tubelets']} eligible={census['eligible']} "
          f"boosted={census['boosted_dets']}/{census['dets']} "
          f"({100*census['boosted_frac']:.1f}%) floor={floor} ({backend})")
    print(f"[a1] -> {out_pq}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
