"""A3 — splice splitter (docs/plan_a3_split_2026-08-19.md).

Cuts tracks at the two operator-observed splice mechanisms:
  Type 1 (post-exit lingering)  -> geometry cut at the FIRST outbound
      exit-gate crossing + margin (classify() keeps exits[-1] — the
      thief's exit — which is why the splice class existed at all).
  Type 2 (mid-intersection box theft, "pinched trajectory") -> pinch
      cut at the cusp: impossible deceleration into a stop/flip vertex
      followed by departure >= PINCH_ANGLE away, discriminated from
      queue stops (same-direction resume) and smooth U-turns
      (distributed same-sign curvature) per the operator's spec.

Kinematic bounds are SELF-CALIBRATED per window (fit_motion_residual:
v_stop / a_allow) — never frozen pixel constants (the compression
trap). Completion channel: segment-1 fulls -> direct candidates;
segment-1 entry_only -> the PPT prototype scorer with the origin
fixed (the operator's extrapolate-or-flag), floors from calibrate();
below-floors -> review_flags rows for the upgraded reviewer.

Modes:
  --mode audit     cut/segment funnel + pinch_rate (read-only)
  --mode validate  G-A3-1 (labeled splices) + G-A3-2 (label parity)
  --mode compose   candidate DB + flags (requires gates passed)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                              # noqa: E402

from backend.config import (                                    # noqa: E402
    NATIVE_ARTICULATED_CLASS_ID, NATIVE_ARTICULATED_MIN_FRAMES,
    NATIVE_SINGLE_UNIT_CLASS_ID, NATIVE_SINGLE_UNIT_MIN_FRAMES)
from backend.database import list_paths_for_camera              # noqa: E402
from backend.services.classifier import classify_vehicle        # noqa: E402
from backend.services.entry_gates import (                      # noqa: E402
    all_crossings, build_gates, cell_census, classify, parse_gate_segment)
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.track_chains import build_chain_map_ev    # noqa: E402
from backend.services.trajectory_classifier import (            # noqa: E402
    classify_trajectory, derive_movement)
from backend.services.two_pass import (                         # noqa: E402
    _camera_parquet, _tracks_from_rows, gate_axes_for)
from v2_common import fit_motion_residual, load_table           # noqa: E402
from v2_f2m_pilot import score_track                            # noqa: E402
from v2_ppt_reattr import calibrate                             # noqa: E402

# ---- declared constants (gate doc; frozen before validation) --------------
MARGIN_S = 1.0            # geometry cut margin past the exit crossing
PINCH_ANGLE = 120.0       # arrival->departure bearing change (deg)
PINCH_SPREAD = 6          # >this many turning chords = smooth turn, no cut
DECEL_K = 3.0             # impossible decel = K x fitted a_allow
CHORD_K = 3               # chord span (points) for bearing/speed series
RE_ENTRY_S = 2.0          # inbound within this after an exit = graze
T_DWELL = 3.0             # QD freeze (geometry unchanged; hash re-pinned)
QD_LANE_TOL_PX = 25.0
QD_TAIL_DIST_PX = 70.0
MIN_SEG_PTS = 5
SEED = 42
PROJECT_DEFAULT = "97a7849a"


# ---------------------------------------------------------------------------
# Window loading (ported from the QD composer, + kinematics)
# ---------------------------------------------------------------------------

def geom_hash(project: str, cam: int) -> str:
    conn = sqlite3.connect(f"file:data/projects/{project}/project.db?mode=ro",
                           uri=True)
    h = hashlib.sha256()
    for table in ("legs", "intersection_paths", "channels"):
        for row in conn.execute(
                f"SELECT * FROM {table} WHERE camera_id=? ORDER BY 1", (cam,)):
            h.update(repr(row).encode())
    conn.close()
    return h.hexdigest()[:16]


def load_window(project: str, cam: int, variant: str) -> dict:
    conn = sqlite3.connect(f"file:data/projects/{project}/project.db?mode=ro",
                           uri=True)
    legs_full, mouths, heads, drawn_gates = {}, {}, {}, {}
    for lid, oz, rh, card, gs in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading, "
            "cardinal_direction, gate_segment FROM legs "
            "WHERE camera_id=?", (cam,)):
        legs_full[lid] = {"leg_id": lid, "reference_heading": rh,
                          "cardinal_direction": card}
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
            g = parse_gate_segment(gs)
            if g:
                drawn_gates[lid] = g
    video = conn.execute(
        "SELECT video_id, fps, recording_start_datetime FROM videos "
        "WHERE camera_id=? ORDER BY sort_order LIMIT 1", (cam,)).fetchone()
    conn.close()

    pq = _camera_parquet(project, cam, variant)
    meta_p = Path(tracks_dir(pq)) / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    rows = load_dump(tracks_dir(pq))
    tracks = {tid: sorted(p) for tid, p in _tracks_from_rows(rows).items()}
    rows_by_tid = defaultdict(list)
    for r in rows:
        rows_by_tid[int(r[0])].append(r)
    for v in rows_by_tid.values():
        v.sort(key=lambda r: r[1])

    fps = float(video[1]) if video else 25.0
    f_lo, f_hi = (meta.get("frames") or
                  [min(p[0][0] for p in tracks.values()),
                   max(p[-1][0] for p in tracks.values())])
    gates = build_gates(mouths, list_paths_for_camera(project, cam), heads,
                        leg_axes=gate_axes_for(mouths, tracks.values()),
                        leg_gates=drawn_gates or None)
    # self-calibrated kinematics (px/frame units, like _end_speed)
    npz = Path("runs/v2_week1") / f"tracklets_cam{cam}_{variant}.npz"
    kin = (fit_motion_residual(load_table(npz)) if npz.exists()
           else {"v_stop": 0.8, "a_allow": 0.5, "zv_radius": 20.0})
    info = {}
    for tid, pts in tracks.items():
        pts_in = [p for p in pts if f_lo <= p[0] < f_hi]
        if len(pts_in) < MIN_SEG_PTS:
            info[tid] = {"tag": "too_short", "pts": pts_in}
            continue
        o, d, of, df, op, dp, tag = classify(pts_in, gates, fps)
        info[tid] = {"o": o, "d": d, "of": of, "df": df, "op": op,
                     "dp": dp, "tag": tag, "pts": pts_in}
    return {"project": project, "cam": cam, "variant": variant, "fps": fps,
            "f_lo": f_lo, "f_hi": f_hi,
            "t_lo": f_lo / fps, "t_hi": f_hi / fps,
            "legs_full": legs_full, "all_legs": list(legs_full.values()),
            "heads": heads, "gates": gates, "tracks": tracks, "info": info,
            "rows_by_tid": rows_by_tid, "kin": kin,
            "video_id": video[0] if video else None,
            "rec_start": video[2] if video else None,
            "geom_hash": geom_hash(project, cam)}


# ---------------------------------------------------------------------------
# The cutter
# ---------------------------------------------------------------------------

def _bearing(p, q):
    return math.degrees(math.atan2(q[1] - p[1], -(q[2] - p[2]))) % 360


def _bdiff(a, b):
    return abs((a - b + 180) % 360 - 180)


def displacement_chords(pts, d_min):
    """Amendment 3: chords spanning >= d_min px of NET displacement —
    bearings over these are real motion, not jitter. Returns
    [(f_start, f_end, bearing_deg, speed_px_per_frame, i_start)]."""
    out = []
    i = 0
    n = len(pts)
    while i < n - 1:
        j = i + 1
        while j < n and math.hypot(pts[j][1] - pts[i][1],
                                   pts[j][2] - pts[i][2]) < d_min:
            j += 1
        if j >= n:
            break
        df = pts[j][0] - pts[i][0]
        if df > 0:
            d = math.hypot(pts[j][1] - pts[i][1], pts[j][2] - pts[i][2])
            out.append((pts[i][0], pts[j][0],
                        _bearing(pts[i], pts[j]), d / df, i))
        i = j
    return out


def pinch_cuts(pts, kin, fps):
    """Pinch (Type-2) cuts per amendments 2+3: bearings over
    displacement-chords (2 x fitted zv_radius — beyond-jitter motion
    only); flip >= PINCH_ANGLE between consecutive chords fires:
    gap <= 2 s -> flip_at_speed; gap > 2 s -> stop_flip requiring the
    impossible-decel corroborator (px/s units converted per fps)."""
    d_min = max(2.0 * float(kin.get("zv_radius", 12.0)), 8.0)
    ch = displacement_chords(pts, d_min)
    if len(ch) < 2:
        return []
    v_stop = max(float(kin.get("v_stop", 8.0)), 1e-3) / fps
    a_allow = max(float(kin.get("a_allow", 12.0)), 1e-3) / (fps * fps)
    cuts = []
    for a, b in zip(ch, ch[1:]):
        flip = _bdiff(a[2], b[2])
        if flip < PINCH_ANGLE:
            continue
        gap = b[0] - a[1]              # frames between chord end/start
        if gap <= 2.0 * fps:
            cuts.append((a[1], {"rule": "flip_at_speed",
                                "flip": round(flip, 1)}))
        else:
            # stop-flip: require impossible decel INTO the stop — the
            # arrival chord's speed must vanish faster than DECEL_K x
            # the window's fitted allowance
            decel = a[3] / max(1.0, gap * 0.25)
            if a[3] > 2.0 * v_stop and decel > DECEL_K * a_allow:
                cuts.append((a[1], {"rule": "stop_flip",
                                    "flip": round(flip, 1),
                                    "gap_s": round(gap / fps, 1)}))
    return cuts


def cut_track(pts, gates, fps, kin):
    """All cut frames for a track: geometry (Type 1) + pinch (Type 2).
    Returns (segments, cut_records). Segments = [pts_slice, ...]."""
    records = []
    kept = all_crossings(pts, gates, fps)
    entries = [c for c in kept if c[2]]
    exits = [c for c in kept if not c[2]]
    # Amendment 1: only outbound crossings AFTER the journey's entry —
    # a pre-entry jitter blip must not decapitate a good track.
    if entries:
        exits = [c for c in exits if c[0] > entries[0][0]]
    # Amendment 2: graze-vs-latch. An outbound ends the journey only
    # if no inbound follows within RE_ENTRY_S — UNLESS that inbound
    # arrives via a discontinuity (frame gap or teleport step), which
    # is the lost-track latch signature and CONFIRMS the splice.
    v_stop_pf = max(float(kin.get("v_stop", 8.0)), 1e-3) / fps
    chosen = None
    for ex in exits:
        following = [c for c in kept
                     if c[2] and ex[0] < c[0] <= ex[0] + RE_ENTRY_S * fps]
        if not following:
            chosen = ex
            break
        fin = following[0]
        # locate the step that produced the inbound crossing
        latch = False
        for i in range(len(pts) - 1):
            if pts[i][0] <= fin[0] <= pts[i + 1][0]:
                dfr = pts[i + 1][0] - pts[i][0]
                step = math.hypot(pts[i + 1][1] - pts[i][1],
                                  pts[i + 1][2] - pts[i][2])
                if dfr > 0.5 * fps or (dfr > 0
                                       and step / dfr > 4.0 * v_stop_pf):
                    latch = True
                break
        if latch:
            chosen = ex
            break
    if chosen is not None:
        records.append((chosen[0] + MARGIN_S * fps,
                        {"rule": "geometry", "leg": chosen[1]}))
    for f, diag in pinch_cuts(pts, kin, fps):
        records.append((f, diag))
    records.sort(key=lambda r: r[0])
    # dedup cuts within 1 s
    dedup = []
    for f, diag in records:
        if dedup and f - dedup[-1][0] < 1.0 * fps:
            continue
        dedup.append((f, diag))
    # slice
    segments, start = [], 0
    cutpoints = [f for f, _ in dedup]
    for cf in cutpoints:
        seg = [p for p in pts[start:] if p[0] <= cf]
        idx = start + len(seg)
        if len(seg) >= MIN_SEG_PTS:
            segments.append(seg)
        start = idx
    tail = pts[start:]
    if len(tail) >= MIN_SEG_PTS:
        segments.append(tail)
    if not segments:                      # everything stubbed — keep whole
        segments = [pts]
    return segments, dedup


# ---------------------------------------------------------------------------
# Funnel / guards (ported from the QD composer)
# ---------------------------------------------------------------------------

def bucket_tracks(ctx, control_db):
    conn = sqlite3.connect(f"file:{control_db}?mode=ro", uri=True)
    kept, rej = set(), set()
    for tid, r in conn.execute(
            "SELECT vehicle_track_id, COALESCE(rejected,0) FROM "
            "vehicle_events WHERE camera_id=? AND timestamp_video>=? AND "
            "timestamp_video<?", (ctx["cam"], ctx["t_lo"], ctx["t_hi"])):
        (kept if r == 0 else rej).add(int(tid))
    conn.close()
    buckets = {}
    for tid, v in ctx["info"].items():
        if v["tag"] == "too_short":
            buckets[tid] = "too_short"
        elif int(tid) in kept:
            buckets[tid] = "counted"
        elif int(tid) in rej:
            buckets[tid] = "rejected_pool"
        else:
            buckets[tid] = f"eventless_{v['tag']}"
    return buckets


def events_map(control_db, cam, t_lo, t_hi):
    conn = sqlite3.connect(f"file:{control_db}?mode=ro", uri=True)
    out = defaultdict(list)
    for tid, dest, fn in conn.execute(
            "SELECT vehicle_track_id, destination_leg_id, frame_number "
            "FROM vehicle_events WHERE camera_id=? AND timestamp_video>=? "
            "AND timestamp_video<? AND COALESCE(rejected,0)=0",
            (cam, t_lo, t_hi)):
        out[int(tid)].append((dest, fn))
    conn.close()
    return out


def _gate_axis_proj(gates, leg, pos):
    if pos is None or leg not in gates:
        return None
    p1, p2, _n = gates[leg]
    ax, ay = p2[0] - p1[0], p2[1] - p1[1]
    n = math.hypot(ax, ay) or 1e-9
    return ((pos[0] - p1[0]) * ax + (pos[1] - p1[1]) * ay) / n


def _tail_dist(a_pts, b_pts):
    if not a_pts or not b_pts:
        return float("inf")
    ds = sorted(min(math.hypot(p[1] - q[1], p[2] - q[2]) for q in b_pts)
                for p in a_pts)
    return ds[len(ds) // 2]


INSERT_SQL = """INSERT INTO vehicle_events
   (video_id, camera_id, trim_id,
    vehicle_track_id, origin_leg_id, movement,
    trajectory_data, trajectory_confidence, vehicle_class,
    fhwa_class, detection_confidence, timestamp_video,
    timestamp_real, frame_number, start_frame,
    classifier_net_heading_change, classifier_cumulative_curvature,
    classifier_path_straightness, classifier_path_distance,
    classifier_num_points, destination_leg_id, destination_confidence,
    destination_posterior_json, destination_margin,
    origin_posterior_json, origin_margin, posterior_source,
    bbox_length, bbox_center_y)
   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def synthesize_row(ctx, tid, seg, origin, dest, source):
    rows = [r for r in ctx["rows_by_tid"].get(int(tid), [])
            if seg[0][0] <= r[1] <= seg[-1][0]]
    fps = ctx["fps"]
    mv = derive_movement(ctx["legs_full"][origin],
                         ctx["legs_full"].get(dest), ctx["all_legs"])
    if mv == "insufficient_data":
        return None
    if mv == "u_turn":
        return "uturn_deferred"
    traj = [[round(p[1], 2), round(p[2], 2)] for p in seg]
    cls = classify_trajectory(traj, ctx["heads"].get(origin) or 0.0)
    if rows:
        confs = [float(r[6]) for r in rows]
        avg_conf = sum(confs) / len(confs)
        birth_cls = int(rows[0][7])
        n_art = sum(1 for r in rows
                    if int(r[7]) == NATIVE_ARTICULATED_CLASS_ID)
        n_su = sum(1 for r in rows
                   if int(r[7]) == NATIVE_SINGLE_UNIT_CLASS_ID)
        eff = birth_cls
        if n_art >= NATIVE_ARTICULATED_MIN_FRAMES:
            eff = NATIVE_ARTICULATED_CLASS_ID
        elif n_su >= NATIVE_SINGLE_UNIT_MIN_FRAMES:
            eff = NATIVE_SINGLE_UNIT_CLASS_ID
        elif eff in (NATIVE_ARTICULATED_CLASS_ID,
                     NATIVE_SINGLE_UNIT_CLASS_ID):
            eff = 7
        bl = max(max(float(r[4]), float(r[5])) for r in rows)
        best = max(rows, key=lambda r: max(float(r[4]), float(r[5])))
        vc = classify_vehicle(eff, float(best[4]), float(best[5]),
                              float(best[4]) * float(best[5]), avg_conf)
        bcy = float(best[3])
    else:
        avg_conf, bl, bcy = 0.0, None, None
        vc = {"simplified_class": "unknown", "fhwa_class": None}
    ts_frame = seg[0][0]
    o, d2, of, df, _op, _dp, tag = classify(seg, ctx["gates"], fps)
    if tag == "full" and of is not None:
        ts_frame = of
    timestamp_video = float(ts_frame) / fps
    timestamp_real = None
    if ctx["rec_start"]:
        try:
            timestamp_real = (
                datetime.fromisoformat(str(ctx["rec_start"]))
                + timedelta(seconds=timestamp_video)).isoformat()
        except (ValueError, TypeError):
            pass
    return (ctx["video_id"], ctx["cam"], None, int(tid), int(origin), mv,
            json.dumps(traj), float(cls.get("confidence", 0.0)),
            vc.get("simplified_class") or "unknown", vc.get("fhwa_class"),
            float(avg_conf), timestamp_video, timestamp_real,
            int(seg[-1][0]), int(seg[0][0]),
            cls.get("net_heading_change"), cls.get("cumulative_curvature"),
            cls.get("path_straightness"), cls.get("path_distance"),
            cls.get("num_points"),
            int(dest), None, None, None, None, None, source, bl, bcy)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def run_cuts(ctx):
    """Cut every >=5pt track once; return {tid: (segments, cut_records)}."""
    out = {}
    for tid, v in ctx["info"].items():
        if v["tag"] == "too_short":
            continue
        out[tid] = cut_track(v["pts"], ctx["gates"], ctx["fps"], ctx["kin"])
    return out


def mode_audit(ctx, cuts, buckets):
    census = Counter()
    n_tracks = 0
    for tid, (segs, recs) in cuts.items():
        n_tracks += 1
        census[f"cuts_{min(len(recs), 3)}"] += 1
        for _f, diag in recs:
            census[f"rule_{diag['rule']}"] += 1
        census["segments"] += len(segs)
    pinch = census["rule_flip_at_speed"] + census["rule_stop_flip"]
    return {"n_tracks": n_tracks, "census": dict(census),
            "pinch_rate": round(pinch / max(1, n_tracks), 4)}


def mode_validate(ctx, cuts, buckets, labeled_tids):
    """G-A3-1 + G-A3-2 (definitions in the gate doc)."""
    g1 = {"pass": 0, "fail": [], "n": 0}
    for tid in labeled_tids:
        v = ctx["info"].get(tid)
        if v is None or v["tag"] == "too_short":
            g1["fail"].append({"tid": tid, "why": "not classifiable"})
            g1["n"] += 1
            continue
        kept = all_crossings(v["pts"], ctx["gates"], ctx["fps"])
        if not kept:
            g1["fail"].append({"tid": tid, "why": "no crossings"})
            g1["n"] += 1
            continue
        first_cross = kept[0][0]
        last_frame = v["pts"][-1][0]
        segs, recs = cuts.get(tid, ([v["pts"]], []))
        # Amendment 1 acceptance: >=2 segments; segment 1 contains the
        # first crossing; the cut severs a real tail.
        ok = (len(segs) >= 2
              and segs[0][0][0] <= first_cross <= segs[0][-1][0] + 1
              and any(f < last_frame for f, _ in recs))
        g1["n"] += 1
        if ok:
            g1["pass"] += 1
        else:
            g1["fail"].append({
                "tid": tid, "why": "no separating cut",
                "cuts": [round(f, 1) for f, _ in recs],
                "first_cross": round(first_cross, 1),
                "last_frame": round(last_frame, 1),
                "n_segs": len(segs)})
    # G-A3-2: label parity on counted tids
    g2 = {"n": 0, "parity": 0, "diffs": []}
    for tid, b in buckets.items():
        if b != "counted":
            continue
        v = ctx["info"][tid]
        segs, recs = cuts.get(tid, ([v["pts"]], []))
        g2["n"] += 1
        if len(segs) == 1 and not recs:
            g2["parity"] += 1
            continue
        base = (v["o"], v["d"], v["tag"])
        match = any(
            classify(seg, ctx["gates"], ctx["fps"])[0:2]
            + (classify(seg, ctx["gates"], ctx["fps"])[6],) == base
            for seg in segs)
        if match:
            g2["parity"] += 1
        else:
            g2["diffs"].append({
                "tid": tid, "base": [v["o"], v["d"], v["tag"]],
                "segs": [list(classify(s, ctx["gates"], ctx["fps"])[0:2])
                         + [classify(s, ctx["gates"], ctx["fps"])[6]]
                         for s in segs]})
    g2["rate"] = round(g2["parity"] / max(1, g2["n"]), 4)
    return g1, g2


def labeled_splices(ctx, buckets):
    """The 23-splice validation set: 17 from the operator's condemned
    review file + the deferred u-turn class re-derived per QD rules."""
    tids = []
    rev = Path("runs/v2_week1/qd_review_cam2_study_1100.json")
    if rev.exists():
        tids += [int(r["tid"]) for r in json.loads(rev.read_text())]
    # deferred u-turns: eventless full/exit_only, moving exit, trace
    # origin, derive_movement == u_turn (the QD compose skip class)
    from backend.services.track_chains import _end_speed
    for tid, b in buckets.items():
        if b not in ("eventless_full", "eventless_exit_only"):
            continue
        v = ctx["info"][tid]
        if v.get("d") is None or v.get("o") is None:
            continue
        mv = derive_movement(ctx["legs_full"][int(v["o"])],
                             ctx["legs_full"].get(int(v["d"])),
                             ctx["all_legs"])
        if mv == "u_turn" and _end_speed(v["pts"]) * ctx["fps"] >= 25.0:
            if int(tid) not in tids:
                tids.append(int(tid))
    return tids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=PROJECT_DEFAULT)
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--mode", choices=["audit", "validate", "compose"],
                    required=True)
    ap.add_argument("--control-db", default=None)
    ap.add_argument("--out-db", default=None)
    args = ap.parse_args()
    control_db = args.control_db or \
        f"data/projects/{args.project}/project.db"

    ctx = load_window(args.project, args.camera, args.variant)
    buckets = bucket_tracks(ctx, control_db)
    cuts = run_cuts(ctx)
    audit = mode_audit(ctx, cuts, buckets)
    print(f"[a3] cam{args.camera} {args.variant} geom={ctx['geom_hash']} "
          f"tracks={audit['n_tracks']} pinch_rate={audit['pinch_rate']} "
          f"census={audit['census']}")

    if args.mode == "audit":
        out = Path("runs/v2_week1") / (
            f"a3_audit_cam{args.camera}_{args.variant}.json")
        out.write_text(json.dumps(
            {"camera": args.camera, "variant": args.variant,
             "geom_hash": ctx["geom_hash"], **audit}, indent=1))
        print(f"[a3] -> {out}")
        return 0

    if args.mode == "validate":
        tids = labeled_splices(ctx, buckets)
        g1, g2 = mode_validate(ctx, cuts, buckets, tids)
        verdict1 = "PASS" if g1["pass"] >= 20 or \
            (g1["n"] and g1["pass"] / g1["n"] >= 0.87) else "FAIL"
        verdict2 = "PASS" if g2["rate"] >= 0.99 else "FAIL"
        print(f"[a3] G-A3-1: {g1['pass']}/{g1['n']} separating cuts "
              f"-> {verdict1}")
        for f in g1["fail"][:8]:
            print(f"[a3]    miss: {f}")
        print(f"[a3] G-A3-2: parity {g2['parity']}/{g2['n']} "
              f"({g2['rate']:.2%}) -> {verdict2}  "
              f"diffs={len(g2['diffs'])}")
        out = Path("runs/v2_week1") / (
            f"a3_validate_cam{args.camera}_{args.variant}.json")
        out.write_text(json.dumps(
            {"camera": args.camera, "variant": args.variant,
             "geom_hash": ctx["geom_hash"], "labeled_n": len(tids),
             "labeled_tids": tids, "g_a3_1": g1, "g_a3_2": g2,
             "verdicts": {"g_a3_1": verdict1, "g_a3_2": verdict2},
             "audit": audit}, indent=1))
        print(f"[a3] -> {out}")
        return 0 if (verdict1 == "PASS" and verdict2 == "PASS") else 1

    # ---- compose ----------------------------------------------------------
    assert args.out_db, "--out-db required"
    chain_map, _ev = build_chain_map_ev(ctx["tracks"], ctx["gates"],
                                        ctx["fps"])
    ev_map = events_map(control_db, args.camera, ctx["t_lo"], ctx["t_hi"])
    protos, attr_max, margin, cal_rep = calibrate(
        ctx["info"], ctx["kin"]["zv_radius"] / 45.0,
        np.random.default_rng(SEED))
    print(f"[a3] calibration: {cal_rep}")

    census = Counter()
    candidates = {}
    flags = []
    for tid, b in buckets.items():
        if b not in ("eventless_full", "eventless_exit_only",
                     "eventless_entry_only", "eventless_no_crossing"):
            continue
        segs, recs = cuts.get(tid, ([ctx["info"][tid]["pts"]], []))
        if not recs:
            census["uncut_eventless"] += 1
            continue
        seg1 = segs[0]
        o, d, of, df, _op, dp, tag = classify(seg1, ctx["gates"],
                                              ctx["fps"])
        if tag == "full":
            candidates[tid] = {"seg": seg1, "origin": int(o),
                               "dest": int(d), "source": "a3_geometry",
                               "f_cross": df, "pos": dp}
            census["seg1_full"] += 1
        elif tag == "entry_only" and o is not None and margin > 0.0:
            sc = score_track(seg1, protos, "entry", int(o),
                             ctx["kin"]["zv_radius"] / 45.0)
            if sc and sc[0][0] <= attr_max and (
                    len(sc) < 2 or sc[0][0] < margin * sc[1][0]):
                cell = sc[0][1]
                candidates[tid] = {"seg": seg1, "origin": int(cell[0]),
                                   "dest": int(cell[1]),
                                   "source": "a3_extrapolated",
                                   "f_cross": seg1[-1][0], "pos": None}
                census["seg1_extrapolated"] += 1
            else:
                flags.append({"tid": int(tid), "origin": int(o),
                              "span": [seg1[0][0], seg1[-1][0]],
                              "cells": [[list(c), round(cost, 1)]
                                        for cost, c in (sc or [])[:3]]})
                census["seg1_flagged"] += 1
        else:
            census[f"seg1_{tag}"] += 1

    # guards (chain + queue-slot; QD port)
    chain_has_event = {chain_map.get(t) for t, b in buckets.items()
                      if b in ("counted", "rejected_pool")
                      and chain_map.get(t) is not None}
    kept_exits = defaultdict(list)
    for t, b in buckets.items():
        if b in ("counted", "rejected_pool"):
            v = ctx["info"][t]
            if v.get("d") is not None and v.get("df") is not None:
                proj = _gate_axis_proj(ctx["gates"], int(v["d"]),
                                       v.get("dp"))
                kept_exits[int(v["d"])].append(
                    (v["df"] / ctx["fps"], proj, v["pts"][-5:]))
    admitted = {}
    by_chain = defaultdict(list)
    for tid, c in candidates.items():
        cid = chain_map.get(tid)
        if cid is not None and cid in chain_has_event:
            census["blocked_chain"] += 1
            continue
        t_x = (c["f_cross"] or c["seg"][-1][0]) / ctx["fps"]
        proj_x = _gate_axis_proj(ctx["gates"], c["dest"], c.get("pos"))
        blocked = False
        for (t_e, proj_e, tail) in kept_exits.get(c["dest"], []):
            if t_e is not None and abs(t_e - t_x) > T_DWELL:
                continue
            if proj_x is not None and proj_e is not None:
                if abs(proj_x - proj_e) < QD_LANE_TOL_PX:
                    blocked = True
                    break
            elif _tail_dist(c["seg"][-5:], tail) < QD_TAIL_DIST_PX:
                blocked = True
                break
        if blocked:
            census["blocked_slot"] += 1
            continue
        if cid is not None:
            by_chain[cid].append(tid)
        else:
            admitted[tid] = c
    for cid, tids in by_chain.items():
        tids.sort(key=lambda t: candidates[t]["seg"][0][0])
        admitted[tids[0]] = candidates[tids[0]]
        census["chain_dupe_suppressed"] += len(tids) - 1

    # Amendment 5: census-headroom admission — recoveries only into
    # cells still UNDER the window's own gate-evidence envelope
    # (GT-free; the flood guard's per-cell logic at compose time).
    census_exp = cell_census(ctx["tracks"].values(), ctx["gates"],
                             ctx["fps"])
    conn = sqlite3.connect(f"file:{control_db}?mode=ro", uri=True)
    kept_cells = Counter()
    for o_, d_, n_ in conn.execute(
            "SELECT origin_leg_id, destination_leg_id, COUNT(*) FROM "
            "vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0 "
            "AND timestamp_video>=? AND timestamp_video<? AND "
            "origin_leg_id IS NOT NULL AND destination_leg_id IS NOT NULL "
            "GROUP BY 1,2", (args.camera, ctx["t_lo"], ctx["t_hi"])):
        kept_cells[(int(o_), int(d_))] = int(n_)
    conn.close()

    rows, skipped = [], Counter()
    added_cells = Counter()
    for tid, c in sorted(admitted.items(),
                         key=lambda kv: kv[1]["seg"][0][0]):
        cell = (c["origin"], c["dest"])
        headroom = float(census_exp.get(cell, 0.0)) \
            - kept_cells.get(cell, 0) - added_cells[cell]
        if headroom < 1.0:
            skipped["no_census_headroom"] += 1
            continue
        r = synthesize_row(ctx, tid, c["seg"], c["origin"], c["dest"],
                           c["source"])
        if r is None:
            skipped["movement_underivable"] += 1
        elif r == "uturn_deferred":
            skipped["uturn_deferred"] += 1
        else:
            rows.append(r)
            added_cells[cell] += 1

    out = Path(args.out_db)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    src = sqlite3.connect(control_db)
    dst = sqlite3.connect(out)
    src.backup(dst)
    src.close()
    n_before = dst.execute(
        "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=? AND "
        "COALESCE(rejected,0)=0 AND timestamp_video>=? AND "
        "timestamp_video<?",
        (args.camera, ctx["t_lo"], ctx["t_hi"])).fetchone()[0]
    with dst:
        dst.executemany(INSERT_SQL, rows)
    n_after = dst.execute(
        "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=? AND "
        "COALESCE(rejected,0)=0 AND timestamp_video>=? AND "
        "timestamp_video<?",
        (args.camera, ctx["t_lo"], ctx["t_hi"])).fetchone()[0]
    dst.close()
    assert n_after == n_before + len(rows), "additive-mass invariant"

    per_cell = Counter(f"{c['origin']}->{c['dest']}"
                       for t, c in admitted.items())
    diag = {"camera": args.camera, "variant": args.variant,
            "geom_hash": ctx["geom_hash"], "audit": audit,
            "calibration": cal_rep, "census": dict(census),
            "skipped": dict(skipped), "n_inserted": len(rows),
            "n_before": n_before, "n_after": n_after,
            "per_cell_added": dict(per_cell),
            "flags_below_floor": flags,
            "constants": {"MARGIN_S": MARGIN_S,
                          "PINCH_ANGLE": PINCH_ANGLE,
                          "PINCH_SPREAD": PINCH_SPREAD,
                          "DECEL_K": DECEL_K, "T_DWELL": T_DWELL}}
    dpath = Path("runs/v2_week1") / (
        f"a3_c_cam{args.camera}_{args.variant}.json")
    dpath.write_text(json.dumps(diag, indent=1))
    print(f"[a3] compose: inserted {len(rows)} "
          f"(census {dict(census)}, skipped {dict(skipped)}, "
          f"flags {len(flags)})")
    print(f"[a3] -> {out}")
    print(f"[a3] -> {dpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
