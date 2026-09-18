"""Why do cam4's bottom-edge northbound tracks leave NO EVENT? (2026-09-12)

probe_cam4_nb_emergence.py found ~460 NB vehicles per window entering the
frame over the BOTTOM edge mid-frame (nearest lane), tracked late (median
2 frames), and 300+ of the covering tracks end with no event. This census
replays pass 2 for one cam4 window (apply=False, scratch workdir) with the
pipeline's finalize instrumented: for every track it records origin,
points, displacement, which n_* counter moved, and the straight-fragment
rule's verdict; then joins the working DB's events. Reports the drop
reason for (a) the covering tracks from the emergence probe and (b) every
NB-bearing dump track without an event.
Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/census_cam4_edge_births_pass2.py [VARIANT]
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import pipeline as P  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.two_pass import run_pass2  # noqa: E402

VARIANT = sys.argv[1] if len(sys.argv) > 1 else "study_1600"
PROJ = sys.argv[2] if len(sys.argv) > 2 else "97a7849a"
CAM = int(sys.argv[3]) if len(sys.argv) > 3 else 4
REC: dict[int, dict] = {}
SFR: dict[int, object] = {}
CUR_TID: int | None = None

_orig_fin = P.ProcessingPipeline._finalize_vehicle_data
_orig_sfr = P.ProcessingPipeline._straight_fragment_reroute


def _fin(self, track_id, vehicle, frame_number):
    before = {k: v for k, v in vars(self).items() if k.startswith("n_") and isinstance(v, int)}
    traj = vehicle.get("trajectory") or []
    disp = math.hypot(traj[-1][0] - traj[0][0], traj[-1][1] - traj[0][1]) if len(traj) >= 2 else 0.0
    global CUR_TID
    CUR_TID = int(track_id)
    r = _orig_fin(self, track_id, vehicle, frame_number)
    after = {k: v for k, v in vars(self).items() if k.startswith("n_") and isinstance(v, int)}
    moved = sorted(k for k in after if after[k] != before.get(k))
    REC[int(track_id)] = {"origin": vehicle.get("origin_leg_id"), "pts": len(traj), "disp": round(disp, 1),
                          "birth": (round(traj[0][0]), round(traj[0][1])) if traj else None,
                          "moved": moved, "sfr": SFR.pop(int(track_id), None)}
    return r


def _sfr(self, vehicle, trajectory, classification, origin_leg_id, origin_leg, destination_leg_id,
         movement, polyline_dest, posterior_source, gate_dest, dest_result):
    out = _orig_sfr(self, vehicle, trajectory, classification, origin_leg_id, origin_leg, destination_leg_id,
                    movement, polyline_dest, posterior_source, gate_dest, dest_result)
    tid = CUR_TID
    if tid is not None:
        SFR[int(tid)] = ("drop" if out == "drop" else ("reroute" if out else f"kept {movement}->{destination_leg_id}"))
    return out


P.ProcessingPipeline._finalize_vehicle_data = _fin
P.ProcessingPipeline._straight_fragment_reroute = _sfr
CLS: dict[int, dict] = {}
DST: dict[int, dict] = {}
_orig_cls = P.classify_trajectory
_orig_dst = P.score_destination_leg


def _cls(*a, **k):
    out = _orig_cls(*a, **k)
    if CUR_TID is not None:
        CLS[CUR_TID] = {"mv": out.get("movement"), "pts": out.get("num_points"), "dist": round(out.get("path_distance") or 0)}
    return out


def _dst(*a, **k):
    out = _orig_dst(*a, **k)
    if CUR_TID is not None:
        DST[CUR_TID] = {"dest": out.get("destination_leg_id"), "conf": round(out.get("confidence") or 0, 2)}
    return out


P.classify_trajectory = _cls
P.score_destination_leg = _dst


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix=f"edge_census_cam4_{VARIANT}_"))
    print(f"pass-2 replay cam4 {VARIANT} -> {workdir}")
    res = run_pass2(PROJ, CAM, variant=VARIANT, workdir=workdir, apply=False)
    out_db = res.get("out_db") or next(iter(workdir.glob("twopass_*.db")))
    print(f"replay done: events={res.get('events')} out_db={out_db}; finalize records {len(REC)}")
    con = sqlite3.connect(f"file:{out_db}?mode=ro", uri=True)
    legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (CAM,)))
    ev = {}
    for tid, o, d, rej in con.execute(
            "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, COALESCE(rejected,0) FROM vehicle_events WHERE camera_id=?", (CAM,)):
        ev.setdefault(int(tid), []).append((legs.get(o, "?"), legs.get(d, "?"), rej))

    def fate(tid):
        evs = ev.get(tid, [])
        if any(e[2] == 0 for e in evs):
            return "counted " + "/".join(f"{e[0]}->{e[1]}" for e in evs if e[2] == 0)
        if evs:
            return "rejected"
        return "NO EVENT"

    def reason(tid):
        r = REC.get(tid)
        if r is None:
            return "never finalized (still active / not in replay)"
        if r["origin"] is None:
            return f"no origin ({'<%d pts' % P.ORIGIN_ASSIGN_MIN_FRAMES if r['pts'] < P.ORIGIN_ASSIGN_MIN_FRAMES else 'dropped'})"
        m = [k for k in r["moved"] if k not in ("n_tracks_total", "n_crossed_enter", "n_origin_via_polyline",
                                                 "n_posterior_origin", "n_posterior_dest", "n_destination_via_polyline",
                                                 "n_origin_evidenced", "n_origin_unevidenced", "n_gate_supremacy",
                                                 "n_entry_tiebreak", "n_speed_tiebreak", "n_origin_vetoed")]
        tag = ",".join(m) if m else "no counter moved"
        if "n_insufficient_data" in m:
            c = CLS.get(tid); d = DST.get(tid)
            if c and c["mv"] == "insufficient_data":
                tag += f" @classify (pts {c['pts']}, dist {c['dist']})"
            elif d is not None:
                tag += f" @destination (softmax dest={d['dest']}, conf {d['conf']})"
            else:
                tag += " @destination (no softmax call)"
        if r["sfr"]:
            tag += f" | sfr={r['sfr']}"
        return f"origin {legs.get(r['origin'], r['origin'])}: {tag}"

    # (a) covering tracks from the emergence probe
    tp = Path(f"runs/v2_week1/probe_cam4_nb_emergence_{VARIANT}_tids.json")
    if tp.exists():
        cov = json.loads(tp.read_text())["covering"]
        print(f"\n(a) {len(cov)} covering tracks of bottom-edge NB entrances ({VARIANT}); fate in THIS replay vs reason:")
        tab = Counter()
        for c in cov:
            tid = int(c["tid"])
            tab[(fate(tid), reason(tid))] += 1
        for (f, rsn), n in tab.most_common(16):
            print(f"  {n:5}  {f:22} {rsn}")
        noev = [c for c in cov if fate(int(c["tid"])) == "NO EVENT"]
        pts = [REC[int(c["tid"])]["pts"] for c in noev if int(c["tid"]) in REC]
        disp = [REC[int(c["tid"])]["disp"] for c in noev if int(c["tid"]) in REC]
        if pts:
            print(f"  NO EVENT covering tracks: points median {np.median(pts):.0f} (p25 {np.percentile(pts, 25):.0f}), "
                  f"displacement median {np.median(disp):.0f} px (p25 {np.percentile(disp, 25):.0f})")

    # (b) every NB-bearing dump track (>=40 px rightward) with no event
    con0 = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    chash, = con0.execute("SELECT content_hash FROM videos WHERE camera_id=?", (CAM,)).fetchone()
    rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, CAM, chash, VARIANT))))
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    tids, st = np.unique(rows[:, 0], return_index=True); en = np.append(st[1:], len(rows))
    tab = Counter(); birth_y = []
    for t, a, b in zip(tids, st, en):
        trk = rows[a:b]
        if CAM == 4 and PROJ == "97a7849a":
            if len(trk) < 2 or trk[-1, 2] - trk[0, 2] < 40:
                continue
        elif len(trk) < 15:
            continue
        tid = int(t)
        if fate(tid) != "NO EVENT":
            continue
        rs = reason(tid)
        tab[rs.split(" (")[0] if "@destination" in rs else rs] += 1
        birth_y.append((trk[0, 2], trk[0, 3] + trk[0, 5] / 2, trk[0, 4], trk[-1, 2], len(trk), trk[-1, 2] - trk[0, 2], "@destination" in rs))
    print(f"\n(b) NB-bearing dump tracks with NO EVENT in this replay: {sum(tab.values())}")
    for rsn, n in tab.most_common(12):
        print(f"  {n:5}  {rsn}")
    by = np.asarray([b[:6] for b in birth_y], dtype=float)
    dst_flag = np.asarray([b[6] for b in birth_y], dtype=bool)
    if len(by):
        dd = by[dst_flag]
        if len(dd):
            print(f"  dropped @destination: {len(dd)}; death x median {np.median(dd[:, 3]):.0f}, "
                  f"died at x >= 600 (right edge): {(dd[:, 3] >= 600).sum()}; pts median {np.median(dd[:, 4]):.0f}; "
                  f"rightward travel median {np.median(dd[:, 5]):.0f} px; born at bottom edge: {(dd[:, 1] >= 440).sum()}")
        edge = by[:, 1] >= 440
        print(f"  born with box bottom >= 440 px (frame bottom edge): {edge.sum()} of {len(by)}; "
              f"their median box width {np.median(by[edge, 2]) if edge.any() else 0:.0f} px, median birth x {np.median(by[edge, 0]) if edge.any() else 0:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
