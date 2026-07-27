"""SB insufficient-data DIAGNOSIS (plan_cam5_eb_bankhole_2026-07-27, re-aimed
wall item 2 — diagnosis only, no mechanism, no fix).

Phase-0 fate ledgers: 21%/18% of real-geometry SB-thru journeys (geo 37>39:
257/1222 @0700, 430/2444 @1600) drop as insufficient-data. Three sites
increment n_insufficient_data (pipeline.py):

  A  ~1145  no-origin at finalize (needs final origin None) — excluded by
            the ledger (no_origin=0 for geo 37>39), instrumented anyway;
  B  ~1184  classify_trajectory returns insufficient_data — for
            cross-anchor tracks only its num_points<5 case can fire
            (min-distance 50px and uturn-displacement 90px are
            geometrically excluded at >=190px anchor separation);
  C  ~1538  the tier-chain fall-through (joint scorer / fallback derive
            produced no label; cam5 runs posterior-OFF so the rescue
            block never re-places them).

This harness replays a stock window with two patches — a class-level
_finalize_vehicle_data wrap + a classify_trajectory shim in pipeline's
namespace (single-threaded replay; a module global carries per-call
results) — and records, for EVERY finalized track: geometry cell, npts,
displacement, path distance, drop site (A/B/C or kept), classifier
movement + metrics. Analysis slices geo 37>39 (and 39>37 for symmetry).

Usage: py scripts/cam5_sbinsuf_diag.py [--window study_0700]
Evidence -> runs/cam5_wall/sbinsuf_<window>.json. Replayed-minutes basis.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.pass2_replay import replay_camera
from backend.services.pipeline import ProcessingPipeline
import backend.services.pipeline as PL

PROJECT = "97a7849a"
CAM = 5
SCRATCH = Path("data/projects/97a7849a/_replay_scratch")  # see cam5_wall_phase0

RECORDS: list[dict] = []
_LEGS: dict[int, tuple[float, float]] = {}
_LAST_CLS: dict = {}
_SB_PATH: list[tuple[float, float]] = []   # applied 37->39 polyline


def _seg_dist(pt, a, b):
    ax, ay = a
    bx, by = b
    px, py = pt[0] - ax, pt[1] - ay
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, (px * dx + py * dy) / L2))
    return math.hypot(pt[0] - (ax + t * dx), pt[1] - (ay + t * dy))


def _poly_dist(pt):
    if len(_SB_PATH) < 2:
        return None
    return min(_seg_dist(pt, _SB_PATH[i], _SB_PATH[i + 1])
               for i in range(len(_SB_PATH) - 1))


def _nearest(pt):
    if not _LEGS:
        return None
    return min(_LEGS, key=lambda l: math.hypot(pt[0] - _LEGS[l][0],
                                               pt[1] - _LEGS[l][1]))


_ORIG_FIN = ProcessingPipeline._finalize_vehicle_data
_ORIG_CLS = PL.classify_trajectory


def _cls_shim(trajectory, reference_heading, **kw):
    res = _ORIG_CLS(trajectory, reference_heading, **kw)
    _LAST_CLS.clear()
    _LAST_CLS.update(res)
    return res


def _path_dist(traj):
    return sum(math.hypot(traj[i + 1][0] - traj[i][0],
                          traj[i + 1][1] - traj[i][1])
               for i in range(len(traj) - 1))


def _wrap(self, track_id, vehicle, frame_number):
    traj = vehicle.get("trajectory", [])
    sl = _nearest(traj[0]) if len(traj) >= 2 else None
    el = _nearest(traj[-1]) if len(traj) >= 2 else None
    ins0 = self.n_insufficient_data
    _LAST_CLS.clear()
    _ORIG_FIN(self, track_id, vehicle, frame_number)
    dropped = self.n_insufficient_data > ins0
    site = None
    if dropped:
        if vehicle.get("origin_leg_id") is None:
            site = "A_no_origin"
        elif _LAST_CLS.get("movement") == "insufficient_data":
            site = "B_classifier"
        else:
            site = "C_derive"
    disp = (math.hypot(traj[-1][0] - traj[0][0], traj[-1][1] - traj[0][1])
            if len(traj) >= 2 else 0.0)
    rec = {
        "tid": track_id, "sl": sl, "el": el, "npts": len(traj),
        "disp": round(disp, 1),
        "pdist": round(_path_dist(traj), 1) if len(traj) >= 2 else 0.0,
        "site": site,
        "origin": vehicle.get("origin_leg_id"),
        "cls_mv": _LAST_CLS.get("movement"),
        "cls_net": round(_LAST_CLS.get("net_heading_change", 0.0), 1),
        "cls_pts": _LAST_CLS.get("num_points"),
    }
    if (sl, el) in ((37, 39), (39, 37)) and len(traj) >= 4 and _SB_PATH:
        ds = [_poly_dist(p) for p in traj]
        rec["sb_mean_off"] = round(sum(ds) / len(ds), 1)
        rec["sb_max_off"] = round(max(ds), 1)
        rec["sb_end_gap"] = round(
            math.hypot(traj[-1][0] - _SB_PATH[-1][0],
                       traj[-1][1] - _SB_PATH[-1][1]), 1)
    RECORDS.append(rec)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="study_0700")
    args = ap.parse_args()

    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    for lid, oz in conn.execute(
            "SELECT leg_id, origin_zone FROM legs WHERE camera_id=?", (CAM,)):
        if oz:
            z = json.loads(oz)
            _LEGS[lid] = (z[0][0], z[0][1]) if isinstance(z[0], (list, tuple)) \
                else (z[0], z[1])
    row = conn.execute(
        "SELECT polyline FROM intersection_paths WHERE camera_id=? AND "
        "origin_leg_id=37 AND destination_leg_id=39", (CAM,)).fetchone()
    if row:
        _SB_PATH.extend((float(p[0]), float(p[1]))
                        for p in json.loads(row[0]))
    print(f"[D] applied 37>39 polyline: {len(_SB_PATH)} pts", flush=True)
    conn.close()

    ProcessingPipeline._finalize_vehicle_data = _wrap
    PL.classify_trajectory = _cls_shim
    try:
        out = SCRATCH / f"cam5wall_sbdiag_{args.window}.db"
        st = replay_camera(PROJECT, CAM, variant=args.window, out_db=out)
    finally:
        ProcessingPipeline._finalize_vehicle_data = _ORIG_FIN
        PL.classify_trajectory = _ORIG_CLS
    print(f"[D] {args.window}: events={st['events']} tracks={st.get('tracks')}",
          flush=True)

    res = {"window": args.window, "n_finalized": len(RECORDS)}
    for label, cell in (("sb_37_39", (37, 39)), ("nb_39_37", (39, 37))):
        rs = [r for r in RECORDS if (r["sl"], r["el"]) == cell
              and r["npts"] >= 4]
        drops = [r for r in rs if r["site"]]
        sites = Counter(r["site"] for r in drops)
        cls_mv = Counter(r["cls_mv"] for r in drops)
        by_site_feats = {}
        for s in sites:
            ds = [r for r in drops if r["site"] == s]
            qn = lambda xs: [round(q, 1) for q in _quartiles(xs)]
            by_site_feats[s] = {
                "n": len(ds),
                "npts_q": qn([r["npts"] for r in ds]),
                "disp_q": qn([r["disp"] for r in ds]),
                "pdist_q": qn([r["pdist"] for r in ds]),
                "cls_net_q": qn([abs(r["cls_net"]) for r in ds
                                 if r["cls_net"] is not None]),
                "cls_movements": dict(Counter(r["cls_mv"] for r in ds)),
                "origins": dict(Counter(r["origin"] for r in ds)),
            }
        res.setdefault("kept_origins", {})[label] = dict(Counter(
            r["origin"] for r in rs if not r["site"]))
        qn = lambda xs: [round(q, 1) for q in _quartiles(xs)]
        kept = [r for r in rs if not r["site"] and "sb_mean_off" in r]
        drop_off = [r for r in drops if "sb_mean_off" in r]
        res[label] = {
            "n": len(rs), "dropped": len(drops),
            "drop_rate": round(len(drops) / len(rs), 3) if rs else None,
            "sites": dict(sites), "classifier_movements": dict(cls_mv),
            "by_site": by_site_feats,
            "offset_vs_sb_path": {
                "kept":    {"mean_off_q": qn([r["sb_mean_off"] for r in kept]),
                            "max_off_q":  qn([r["sb_max_off"] for r in kept]),
                            "end_gap_q":  qn([r["sb_end_gap"] for r in kept])},
                "dropped": {"mean_off_q": qn([r["sb_mean_off"] for r in drop_off]),
                            "max_off_q":  qn([r["sb_max_off"] for r in drop_off]),
                            "end_gap_q":  qn([r["sb_end_gap"] for r in drop_off])},
            },
        }
        print(f"[D] {label} offsets: {json.dumps(res[label]['offset_vs_sb_path'])}",
              flush=True)
        print(f"[D] {label}: n={len(rs)} dropped={len(drops)} "
              f"sites={dict(sites)}", flush=True)
        for s, f in by_site_feats.items():
            print(f"[D]   {s}: {json.dumps(f)}", flush=True)

    # whole-camera site split for context
    all_drops = Counter(r["site"] for r in RECORDS if r["site"])
    res["all_sites"] = dict(all_drops)
    print(f"[D] all-camera drop sites: {dict(all_drops)}", flush=True)

    outp = Path(f"runs/cam5_wall/sbinsuf_{args.window}.json")
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(res, indent=1))
    print(f"wrote {outp}", flush=True)
    print("SBDIAG DONE", flush=True)
    return 0


def _quartiles(xs):
    if not xs:
        return [0, 0, 0, 0]
    s = sorted(xs)
    n = len(s)
    return [s[0], s[n // 4], s[n // 2], s[-1]]


if __name__ == "__main__":
    raise SystemExit(main())
