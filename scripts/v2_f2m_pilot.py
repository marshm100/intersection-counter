"""Tier-3 pilot — FRAGMENT-TO-MOVEMENT classification (F2M).
docs/plan_t3_f2m_pilot_2026-08-13.md — gates pre-declared there.

Reads a window's pass-1 dump, builds per-cell mean-polyline prototypes
from the window's OWN gate-verified full journeys (the boxclip_pass2
discover_channels shape — drawn centerlines sit a lane off), classifies
FRAGMENT tracks (>= 5 points, no kept event, chain-sibling guard) with
self-calibrated floors (split-half on the fulls), applies the
double-count guards, and composes synthetic additive events into a
WAL-safe COPY of the control replay DB. GT-free by construction: every
prototype, floor, and assignment comes from the window's own tracks and
operator geometry.

Usage:
  py -X utf8 scripts/v2_f2m_pilot.py --camera 2 --variant study_0700 \
      --control-db data/projects/97a7849a/_replay_scratch/d1_conserve/ctrl/d1ctrl_cam2_study_0700.db \
      --out-db data/projects/97a7849a/_replay_scratch/f2m/f2m_cam2_study_0700.db
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                                  # noqa: E402

from backend.database import get_connection, list_paths_for_camera  # noqa: E402
from backend.services.entry_gates import (                          # noqa: E402
    _closest_on_polyline, build_gates, classify)
from backend.services.pass2_replay import load_dump, tracks_dir     # noqa: E402
from backend.services.track_chains import build_chain_map_ev        # noqa: E402
from backend.services.trajectory_classifier import derive_movement  # noqa: E402
from backend.services.two_pass import (                             # noqa: E402
    _camera_parquet, _tracks_from_rows, gate_axes_for)
from v2_common import fit_motion_residual, load_table               # noqa: E402

SEED = 42
MIN_PTS = 5
PROTO_MIN_FULLS = 10          # plan step 2: cells below cannot build a map
PROTO_CAP = 300
RESAMPLE_N = 15
HELDOUT_PRECISION = 0.95      # plan step 4
MARGIN_SWEEP = [round(0.5 + 0.05 * k, 2) for k in range(9)]  # 0.50..0.90
SUSPICIOUS_S = 2.0            # plan guard (b), pre-declared
CLASS_NAMES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def _resample(xy, n=RESAMPLE_N):
    segs = [math.hypot(xy[i + 1][0] - xy[i][0], xy[i + 1][1] - xy[i][1])
            for i in range(len(xy) - 1)]
    total = sum(segs) or 1.0
    out, acc, si = [], 0.0, 0
    for k in range(n):
        d = total * k / (n - 1)
        while si < len(segs) - 1 and acc + segs[si] < d:
            acc += segs[si]
            si += 1
        t = (d - acc) / segs[si] if segs[si] > 1e-9 else 0.0
        out.append((xy[si][0] + t * (xy[si + 1][0] - xy[si][0]),
                    xy[si][1] + t * (xy[si + 1][1] - xy[si][1])))
    return out


def build_prototypes(fulls, min_support=PROTO_MIN_FULLS):
    """fulls: list of (cell, clipped_xy). Per-cell mean polyline."""
    by = defaultdict(list)
    for cell, clip in fulls:
        if len(by[cell]) < PROTO_CAP and len(clip) >= 4:
            by[cell].append(_resample(clip))
    out = {}
    for cell, tracks in by.items():
        if len(tracks) < min_support or cell[0] == cell[1]:
            continue
        out[cell] = [(sum(t[k][0] for t in tracks) / len(tracks),
                      sum(t[k][1] for t in tracks) / len(tracks))
                     for k in range(RESAMPLE_N)]
    return out


def score_track(pts, channels, mode, known, w_ang):
    """pts: [(f,x,y)...]; the boxclip attribute cost, constants injected.
    Returns sorted [(cost, cell), ...] over eligible candidate cells."""
    n = len(pts)
    if mode == "entry":
        sample = pts[int(n * 0.4):]
        key = 0
    elif mode == "exit":
        sample = pts[:max(1, int(n * 0.6))]
        key = 1
    else:
        sample = pts
        key = None
    step = max(1, len(sample) // 40)
    sample = sample[::step]
    scores = []
    for cell, poly in channels.items():
        if key is not None and cell[key] != known:
            continue
        costs = []
        for i in range(len(sample)):
            _f, x, y = sample[i]
            _cpt, tan, dist = _closest_on_polyline(poly, (x, y))
            cost = dist
            if i + 1 < len(sample):
                dx = sample[i + 1][1] - x
                dy = sample[i + 1][2] - y
                length = math.hypot(dx, dy)
                if length > 1.0 and tan is not None:
                    dot = max(-1.0, min(1.0, (dx * tan[0] + dy * tan[1]) / length))
                    cost += math.degrees(math.acos(dot)) * w_ang
            costs.append(cost)
        if costs:
            scores.append((sum(costs) / len(costs), cell))
    scores.sort()
    return scores


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--control-db", required=True)
    ap.add_argument("--out-db", required=True)
    args = ap.parse_args()
    cam, variant = args.camera, args.variant
    rng = np.random.default_rng(SEED)

    # ---- geometry + video params (the strict_full_census recipe) ----------
    conn = get_connection(args.project)
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id = ?", (cam,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
    conn.row_factory = sqlite3.Row
    legs_full = {r["leg_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM legs WHERE camera_id=?", (cam,))}
    fps, rec_start = conn.execute(
        "SELECT fps, recording_start_datetime FROM videos WHERE camera_id=? "
        "ORDER BY sort_order LIMIT 1", (cam,)).fetchone()
    conn.close()
    fps = float(fps)
    all_legs = list(legs_full.values())
    if not mouths:
        print("no leg mouths")
        return 1

    # ---- dump ---------------------------------------------------------------
    tdir = tracks_dir(_camera_parquet(args.project, cam, variant))
    rows = load_dump(tdir)
    tracks = {tid: sorted(pts) for tid, pts in _tracks_from_rows(rows).items()}
    gates = build_gates(mouths, list_paths_for_camera(args.project, cam),
                        heads, leg_axes=gate_axes_for(mouths, tracks.values()))
    if not gates:
        print("no gates")
        return 1

    # per-track conf/class from raw rows (cols: tid f cx cy bw bh conf cls)
    conf_by, cls_by = defaultdict(list), defaultdict(list)
    for r in rows:
        conf_by[int(r[0])].append(float(r[6]))
        cls_by[int(r[0])].append(int(r[7]))

    # ---- classify + census --------------------------------------------------
    info = {}
    for tid, pts in tracks.items():
        if len(pts) < MIN_PTS:
            continue
        o, d, of, df, _op, _dp, tag = classify(pts, gates, fps)
        info[tid] = {"o": o, "d": d, "of": of, "df": df, "tag": tag,
                     "pts": pts}
    census = defaultdict(int)
    for v in info.values():
        census[v["tag"]] += 1

    # ---- calibration (zv_radius for W_ang) ---------------------------------
    npz = Path("runs/v2_week1") / f"tracklets_cam{cam}_{variant}.npz"
    if not npz.exists():
        print(f"missing tracklet table {npz} — run v2_dump_graph first")
        return 1
    cal = fit_motion_residual(load_table(npz))
    w_ang = cal["zv_radius"] / 45.0   # 45 deg misheading costs one zv_radius

    # ---- control DB: kept events + chain guard ------------------------------
    cctl = sqlite3.connect(f"file:{args.control_db}?mode=ro", uri=True)
    kept = cctl.execute(
        "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
        "timestamp_video FROM vehicle_events WHERE camera_id=? "
        "AND COALESCE(rejected,0)=0", (cam,)).fetchall()
    cctl.close()
    kept_tids = {int(t) for t, _o, _d, _tv in kept}
    kept_by_cell = defaultdict(list)
    for _t, o, d, tv in kept:
        if tv is not None:
            kept_by_cell[(o, d)].append(float(tv))
    for v in kept_by_cell.values():
        v.sort()

    chain_map, _ev = build_chain_map_ev(tracks, gates, fps)
    chain_members = defaultdict(set)
    for tid, cid in chain_map.items():
        chain_members[cid].add(tid)
    counted_chains = {chain_map[t] for t in kept_tids if t in chain_map}

    frags, excl_chain = [], 0
    for tid, v in info.items():
        if tid in kept_tids:
            continue
        cid = chain_map.get(tid)
        if cid is not None and cid in counted_chains:
            excl_chain += 1
            continue
        frags.append(tid)

    # ---- prototypes + split-half floor calibration --------------------------
    full_recs = []
    for tid, v in info.items():
        if v["tag"] != "full":
            continue
        clip = [(x, y) for f, x, y in v["pts"] if v["of"] <= f <= v["df"]]
        full_recs.append(((int(v["o"]), int(v["d"])), clip, v["pts"]))
    rng.shuffle(full_recs)
    half = len(full_recs) // 2
    protos_A = build_prototypes([(c, clip) for c, clip, _p in full_recs[:half]])
    heldout = [r for r in full_recs[half:] if r[0] in protos_A]
    ho_rows = []
    for cell, _clip, pts in heldout:
        sc = score_track(pts, protos_A, "free", None, w_ang)
        if sc:
            ho_rows.append((sc, cell))
    best_costs = [sc[0][0] for sc, _ in ho_rows]
    attr_max = float(np.percentile(best_costs, 95)) if best_costs else 0.0
    margin, precision, coverage = None, None, None
    for m in sorted(MARGIN_SWEEP, reverse=True):     # weakest first
        assigned = correct = 0
        for sc, truth in ho_rows:
            if sc[0][0] > attr_max:
                continue
            if len(sc) > 1 and sc[0][0] >= m * sc[1][0]:
                continue
            assigned += 1
            correct += (sc[0][1] == truth)
        p = correct / assigned if assigned else 0.0
        if p >= HELDOUT_PRECISION:
            margin, precision = m, p
            coverage = assigned / len(ho_rows) if ho_rows else 0.0
            break
    if margin is None:
        print(f"[f2m] cam{cam} {variant}: NO margin in sweep reaches "
              f"{HELDOUT_PRECISION} held-out precision — floors uncalibratable")
        margin, precision, coverage = 0.0, 0.0, 0.0
    protos = build_prototypes([(c, clip) for c, clip, _p in full_recs])
    med_transit = float(np.median(
        [(v["df"] - v["of"]) / fps for v in info.values()
         if v["tag"] == "full"])) if census["full"] else 0.0

    # ---- assign fragments ---------------------------------------------------
    MODE = {"entry_only": "entry", "exit_only": "exit", "no_crossing": "free"}
    assigned, rejected = [], defaultdict(int)
    for tid in frags:
        v = info[tid]
        mode = MODE.get(v["tag"])
        if mode is None:
            rejected["full_uncounted"] += 1     # full but pipeline-dropped
            mode = "free"
        known = (int(v["o"]) if mode == "entry"
                 else int(v["d"]) if mode == "exit" else None)
        sc = score_track(v["pts"], protos, mode, known, w_ang)
        if not sc:
            rejected["no_candidates"] += 1
            continue
        if sc[0][0] > attr_max:
            rejected["poor_fit"] += 1
            continue
        if margin == 0.0 or (len(sc) > 1 and sc[0][0] >= margin * sc[1][0]):
            rejected["ambiguous"] += 1
            continue
        cell = sc[0][1]
        frame = v["of"] if v["of"] is not None else float(
            np.median([p[0] for p in v["pts"]]))
        assigned.append({"tid": tid, "cell": cell, "cost": sc[0][0],
                        "tag": v["tag"], "frame": float(frame),
                         "f0": v["pts"][0][0], "f1": v["pts"][-1][0]})

    # ---- double-count guards ------------------------------------------------
    # (a) same-cell entry-stub + exit-stub pairing within 2x median transit
    pair_gap_f = 2.0 * med_transit * fps
    by_cell_entries = defaultdict(list)
    for a in assigned:
        if a["tag"] == "entry_only":
            by_cell_entries[a["cell"]].append(a)
    paired = 0
    for a in assigned:
        if a["tag"] != "exit_only":
            continue
        for e in by_cell_entries[a["cell"]]:
            if e.get("dead") or a.get("dead"):
                continue
            if 0 < a["f0"] - e["f1"] <= pair_gap_f:
                a["dead"] = True            # exit stub folds into the entry
                paired += 1
                break
    # (b) co-temporal same-cell suspicion vs kept control events
    suspicious = 0
    for a in assigned:
        if a.get("dead"):
            continue
        tv0, tv1 = a["f0"] / fps, a["f1"] / fps
        times = kept_by_cell.get(tuple(a["cell"]), [])
        lo = np.searchsorted(times, tv0 - SUSPICIOUS_S)
        if lo < len(times) and times[lo] <= tv1 + SUSPICIOUS_S:
            a["dead"] = True
            suspicious += 1
    final = [a for a in assigned if not a.get("dead")]

    # ---- compose ------------------------------------------------------------
    out = Path(args.out_db)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    src = sqlite3.connect(args.control_db)
    dst = sqlite3.connect(out)
    src.backup(dst)
    src.close()
    ins = 0
    with dst:
        for a in final:
            o, d = int(a["cell"][0]), int(a["cell"][1])
            mv = derive_movement(legs_full[o], legs_full.get(d), all_legs)
            if mv == "insufficient_data":
                continue
            tv = a["frame"] / fps
            treal = (datetime.fromisoformat(rec_start)
                     + timedelta(seconds=tv)).isoformat()
            pts = info[a["tid"]]["pts"]
            step = max(1, len(pts) // 20)
            traj = json.dumps([[round(x, 1), round(y, 1)]
                               for _f, x, y in pts[::step]])
            cls = CLASS_NAMES.get(
                int(np.bincount(cls_by[a["tid"]]).argmax()), "car")
            dst.execute(
                "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                "origin_leg_id, destination_leg_id, movement, "
                "trajectory_data, trajectory_confidence, vehicle_class, "
                "detection_confidence, timestamp_video, timestamp_real, "
                "frame_number, posterior_source, rejected) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'f2m',0)",
                (cam, int(a["tid"]), o, d, mv, traj, 0.5, cls,
                 float(np.mean(conf_by[a["tid"]])), tv, treal,
                 int(a["frame"])))
            ins += 1
    dst.close()

    by_cell_final = defaultdict(int)
    for a in final:
        by_cell_final[str(tuple(a["cell"]))] += 1
    diag = {"camera": cam, "variant": variant,
            "census_by_tag": dict(census),
            "fragments": len(frags), "excluded_chain_sibling": excl_chain,
            "floors": {"attr_max_px": round(attr_max, 1), "margin": margin,
                       "w_ang_px_per_deg": round(w_ang, 3),
                       "heldout_precision": precision,
                       "heldout_coverage": coverage,
                       "heldout_n": len(ho_rows)},
            "prototype_cells": sorted(str(c) for c in protos),
            "assigned_pre_guard": len(assigned),
            "rejected": dict(rejected),
            "guard_paired_exit_stubs": paired,
            "guard_suspicious_cotmp": suspicious,
            "inserted": ins,
            "inserted_by_cell": dict(by_cell_final),
            "median_full_transit_s": round(med_transit, 1)}
    dpath = Path("runs/v2_week1") / f"f2m_cam{cam}_{variant}.json"
    dpath.write_text(json.dumps(diag, indent=1))
    print(f"[f2m] cam{cam} {variant}: frags={len(frags)} "
          f"(chain-excl {excl_chain}) assigned={len(assigned)} "
          f"paired={paired} suspicious={suspicious} inserted={ins}")
    print(f"[f2m] floors: max={attr_max:.1f}px margin={margin} "
          f"w_ang={w_ang:.2f} heldout p={precision} cov={coverage}")
    print(f"[f2m] by cell: " + " ".join(
        f"{c}:{n}" for c, n in sorted(by_cell_final.items())))
    print(f"[f2m] -> {out}")
    print(f"[f2m] -> {dpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
