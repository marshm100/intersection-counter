"""PASS 2 of the two-pass architecture (MASTER_PLAN 2c): box-clip classify + count.

Consumes the raw-track dump (dump_raw_tracks.py) and the operator's calibration:
- GATES: one segment per leg, through the leg's origin_zone mouth point, oriented
  along the local cross-road direction taken from the DRAWN channels' tangents
  where they pass the mouth (perspective-correct — no perpendicular-tripwire
  assumption; the F-audit killed that on oblique views). Half-length spans the
  channels' lane spread + margin.
- CLASSIFY (stage A, pure gates): origin = first gate crossed moving INWARD,
  destination = last gate crossed moving OUTWARD. No track is dropped for shape
  mismatch — the cam2 SB/WB collapse cannot recur by construction. Movement
  label = the drawn bank's (origin,dest) cell label; same-leg = u_turn.
- TIMESTAMP: at the ORIGIN crossing (pipeline.py:1083 convention — TMC counts
  at the crossing), so bins match Miovision and the live baseline.
- OUTPUT: a minimal vehicle_events SQLite DB scoreable by
  measure_cam2_reid_spike.py unchanged, plus a coverage breakdown (full journey /
  entry-only / exit-only / no-crossing) — the entry-only+exit-only population is
  the far-field-truncation fallback workload for stage B.

Everything here is GT-free: video + operator calibration only (prime directive).

Usage:
  py scripts/boxclip_pass2.py --camera 2 --variant study_0700 \
     --bank evaluations/gtfree_bank_cam2_direct.json [--print-gates]
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import (
    DEFAULT_VARIANT, compute_video_content_hash, parquet_path)
from dump_raw_tracks import tracks_path
from groundtruth import VIDEO_START

GATE_PAD_PX = 30.0     # beyond the channels' lane spread, each side
GATE_MIN_HALF = 45.0   # floor so a one-lane leg still has a usable gate


def _closest_on_polyline(poly, pt):
    """(closest point, unit tangent, distance) of poly to pt."""
    best = (None, None, float("inf"))
    px, py = pt
    for i in range(len(poly) - 1):
        ax, ay = poly[i]; bx, by = poly[i + 1]
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        if L2 < 1e-9:
            continue
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
        cx, cy = ax + t * vx, ay + t * vy
        d = math.hypot(px - cx, py - cy)
        if d < best[2]:
            L = math.sqrt(L2)
            best = ((cx, cy), (vx / L, vy / L), d)
    return best


def build_gates(legs, bank_paths):
    """{leg_id: (p1, p2, inward_normal)} — gate segment + which way is 'in'.

    Orientation: mean of the leg's channels' local tangents at their closest
    approach to the mouth; the gate is the PERPENDICULAR through the mouth.
    Span: the channels' closest points projected on the gate direction give the
    lane spread; pad + floor. Inward normal points at the mouth centroid."""
    centroid = (sum(m[0] for m in legs.values()) / len(legs),
                sum(m[1] for m in legs.values()) / len(legs))
    gates = {}
    for leg, mouth in legs.items():
        tangents, cpts = [], []
        for p in bank_paths:
            if p["origin_leg_id"] != leg and p["destination_leg_id"] != leg:
                continue
            cpt, tan, _ = _closest_on_polyline(p["polyline"], mouth)
            if cpt is None:
                continue
            # sign-align tangents (a channel toward vs away flips the vector)
            if tangents and (tan[0] * tangents[0][0] + tan[1] * tangents[0][1]) < 0:
                tan = (-tan[0], -tan[1])
            tangents.append(tan)
            cpts.append(cpt)
        tx = sum(t[0] for t in tangents) / len(tangents)
        ty = sum(t[1] for t in tangents) / len(tangents)
        n = math.hypot(tx, ty) or 1.0
        tx, ty = tx / n, ty / n                     # mean road direction
        gx, gy = -ty, tx                            # gate = perpendicular
        spread = [(c[0] - mouth[0]) * gx + (c[1] - mouth[1]) * gy
                  for c in cpts] + [0.0]
        half = max(GATE_MIN_HALF, max(abs(min(spread)), abs(max(spread))) + GATE_PAD_PX)
        p1 = (mouth[0] - gx * half, mouth[1] - gy * half)
        p2 = (mouth[0] + gx * half, mouth[1] + gy * half)
        # inward = along the road direction, toward the intersection centroid
        s = 1.0 if ((centroid[0]-mouth[0])*tx + (centroid[1]-mouth[1])*ty) > 0 else -1.0
        gates[leg] = (p1, p2, (s * tx, s * ty))

    # De-overlap: two gates that cross would double-register one crossing.
    # Pull the intersecting END of each gate back to 8px short of the cross.
    from itertools import combinations
    for _ in range(3):                    # few passes settle any chain
        clean = True
        for a, b in combinations(list(gates), 2):
            (a1, a2, ai), (b1, b2, bi) = gates[a], gates[b]
            t = _seg_cross(a1, a2, b1, b2)
            if t is None:
                continue
            clean = False
            cx, cy = a1[0] + t * (a2[0] - a1[0]), a1[1] + t * (a2[1] - a1[1])
            for leg in (a, b):
                p1, p2, inw = gates[leg]
                m = legs[leg]
                # move whichever endpoint is nearer the crossing to 8px inside it
                d1 = math.hypot(p1[0] - cx, p1[1] - cy)
                d2 = math.hypot(p2[0] - cx, p2[1] - cy)
                far = p2 if d1 <= d2 else p1
                v = (cx - far[0], cy - far[1])
                L = math.hypot(*v) or 1.0
                newpt = (cx - v[0] / L * 8.0, cy - v[1] / L * 8.0)
                gates[leg] = ((newpt, p2, inw) if d1 <= d2 else (p1, newpt, inw))
        if clean:
            break
    return gates


def _seg_cross(a, b, p1, p2):
    """Param t in [0,1] where segment a->b crosses segment p1->p2, else None."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (p2[0] - p1[0], p2[1] - p1[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    qp = (p1[0] - a[0], p1[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / den
    u = (qp[0] * r[1] - qp[1] * r[0]) / den
    return t if (0.0 <= t <= 1.0 and 0.0 <= u <= 1.0) else None


JITTER_FRAMES = 50.0    # same-gate crossings within this = bbox jitter, keep first
UTURN_MIN_FRAMES = 125  # a real u-turn dwells in the box >=5s @25fps...
UTURN_MIN_PX = 40.0     # ...and excursions past the gate; queue jitter does neither
UTURN_MIN_LANE_SHIFT = 25.0  # ...and EXITS IN THE OPPOSITE LANE: in/out crossing
                             # points must differ along the gate axis. Queue creep
                             # over a long red re-crosses at the SAME lane spot
                             # (this killed 100 phantom 'full' SB u-turns)


def gate_lane_clusters(gates, bank_paths):
    """{leg: (in_proj, out_proj)} — where INBOUND vs OUTBOUND channels cross the
    leg's gate, projected on the gate axis. A real u-turn exits via the outbound
    lanes; queue jitter re-crosses in the inbound lanes."""
    lanes = {}
    for leg, (p1, p2, _inw) in gates.items():
        gl = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) or 1.0
        gdir = ((p2[0] - p1[0]) / gl, (p2[1] - p1[1]) / gl)
        ins, outs = [], []
        for p in bank_paths:
            if p["origin_leg_id"] != leg and p["destination_leg_id"] != leg:
                continue
            poly = p["polyline"]
            for i in range(len(poly) - 1):
                t = _seg_cross(poly[i], poly[i + 1], p1, p2)
                if t is None:
                    continue
                cx = poly[i][0] + t * (poly[i + 1][0] - poly[i][0])
                cy = poly[i][1] + t * (poly[i + 1][1] - poly[i][1])
                proj = (cx - p1[0]) * gdir[0] + (cy - p1[1]) * gdir[1]
                (ins if p["origin_leg_id"] == leg else outs).append(proj)
                break
        if ins and outs:
            lanes[leg] = (sum(ins) / len(ins), sum(outs) / len(outs), gdir)
    return lanes


def classify(track, gates, lanes=None):
    """track: [(frame,x,y)...] ->
    (origin_leg, dest_leg, origin_frame, dest_frame, origin_pos, dest_pos, tag)."""
    crossings = []          # (frame_interp, leg, inward: bool, pos: (x,y))
    for i in range(len(track) - 1):
        f0, x0, y0 = track[i]
        f1, x1, y1 = track[i + 1]
        for leg, (p1, p2, inw) in gates.items():
            t = _seg_cross((x0, y0), (x1, y1), p1, p2)
            if t is None:
                continue
            step = (x1 - x0, y1 - y0)
            inward = (step[0] * inw[0] + step[1] * inw[1]) > 0
            crossings.append((f0 + t * (f1 - f0), leg, inward,
                              (x0 + t * step[0], y0 + t * step[1])))
    crossings.sort()
    # Collapse same-gate jitter runs (a queued bbox wobbling across the line
    # emits in/out/in... bursts): keep the FIRST crossing of each burst.
    kept = []
    for c in crossings:
        if kept and c[1] == kept[-1][1] and (c[0] - kept[-1][0]) < JITTER_FRAMES:
            continue
        kept.append(c)
    entries = [c for c in kept if c[2]]
    exits = [c for c in kept if not c[2]]
    origin = entries[0] if entries else None
    dest = exits[-1] if exits else None
    if origin and dest and dest[0] > origin[0]:
        if origin[1] == dest[1]:
            # same-leg = u-turn ONLY with real dwell + excursion past the gate
            # + AN OPPOSITE-LANE EXIT (lateral shift along the gate axis) —
            # queue creep over a red re-crosses at the same lane position.
            g = gates[origin[1]]
            gl = math.hypot(g[1][0] - g[0][0], g[1][1] - g[0][1]) or 1.0
            gdir = ((g[1][0] - g[0][0]) / gl, (g[1][1] - g[0][1]) / gl)
            lane_shift = abs((dest[3][0] - origin[3][0]) * gdir[0]
                             + (dest[3][1] - origin[3][1]) * gdir[1])
            mouth_far = max(
                abs((x - (g[0][0] + g[1][0]) / 2) * g[2][0]
                    + (y - (g[0][1] + g[1][1]) / 2) * g[2][1])
                for f, x, y in track if origin[0] <= f <= dest[0]) if any(
                    origin[0] <= f <= dest[0] for f, _x, _y in track) else 0.0
            lane_ok = True
            if lanes and origin[1] in lanes:
                in_m, out_m, gdir2 = lanes[origin[1]]
                oproj = ((dest[3][0] - g[0][0]) * gdir2[0]
                         + (dest[3][1] - g[0][1]) * gdir2[1])
                lane_ok = abs(oproj - out_m) < abs(oproj - in_m)
            if ((dest[0] - origin[0]) < UTURN_MIN_FRAMES or mouth_far < UTURN_MIN_PX
                    or lane_shift < UTURN_MIN_LANE_SHIFT or not lane_ok):
                return origin[1], None, origin[0], None, origin[3], None, "entry_only"
        return origin[1], dest[1], origin[0], dest[0], origin[3], dest[3], "full"
    if origin:
        return origin[1], None, origin[0], None, origin[3], None, "entry_only"
    if dest:
        return None, dest[1], dest[0], None, None, dest[3], "exit_only"
    return None, None, None, None, None, None, "no_crossing"


def _resample(xy, n=15):
    """Arc-length resample a polyline [(x,y)...] to exactly n points."""
    segs = [math.hypot(xy[i + 1][0] - xy[i][0], xy[i + 1][1] - xy[i][1])
            for i in range(len(xy) - 1)]
    total = sum(segs) or 1.0
    out, acc, si = [], 0.0, 0
    for k in range(n):
        d = total * k / (n - 1)
        while si < len(segs) - 1 and acc + segs[si] < d:
            acc += segs[si]; si += 1
        t = (d - acc) / segs[si] if segs[si] > 1e-9 else 0.0
        out.append((xy[si][0] + t * (xy[si + 1][0] - xy[si][0]),
                    xy[si][1] + t * (xy[si + 1][1] - xy[si][1])))
    return out


def discover_channels(recs, min_support=5, cap=300):
    """Per-cell mean polylines from OUR OWN full journeys (gate-to-gate clipped)
    — the s2c 'path discovery pooled over the full corpus'. These carry the
    lanes vehicles ACTUALLY drive, where the drawn idealized centerlines can
    sit a lane off (which mis-attributed truncated SB-thrus as EB-rights)."""
    by = defaultdict(list)
    for r in recs:
        if r["tag"] != "full" or len(by[(r["o"], r["d"])]) >= cap:
            continue
        clip = [(x, y) for f, x, y in r["pts"] if r["f"] <= f <= r["f_out"]]
        if len(clip) >= 4:
            by[(r["o"], r["d"])].append(_resample(clip))
    out = {}
    for cell, tracks in by.items():
        if len(tracks) < min_support:
            continue
        n = len(tracks[0])
        out[cell] = [(sum(t[k][0] for t in tracks) / len(tracks),
                      sum(t[k][1] for t in tracks) / len(tracks)) for k in range(n)]
    return out


# ---- STAGE B (docs/plan_boxclip_stageb_2026-07-08.md) ----------------------
STITCH_MOVE_GAP = (-12.0, 75.0)   # frames: occlusion break mid-box
STITCH_MOVE_DIST = 70.0           # px
STITCH_STAT_SPEED = 0.4           # px/frame: "ended stationary" (stop bar)
STITCH_STAT_GAP = 1250.0          # frames (~50 s red): resumes where it stopped
STITCH_STAT_DIST = 35.0           # px
ATTR_MAX_PX = 30.0                # channel fit acceptance (cars sit 12-25px, s2b)
ATTR_MARGIN = 0.7                 # best must beat 2nd-best by this factor
ATTR_ANGLE_PX_PER_DEG = 0.7       # direction-mismatch penalty: channels carry a
                                  # DIRECTION; a truncated SB-thru in the exit
                                  # convergence zone is distance-close to EB-right
                                  # but moves ~35 deg differently (and a backwards
                                  # traversal is 180 deg off)
STUB_MIN_ARC = 80.0               # px: a no-crossing chain must be at least this
                                  # long to be attributable (bank --min-path)
ATTR_PAIR_GAP = 3000.0            # frames (~2 min): same-cell entry piece + later
                                  # exit piece = ONE broken vehicle, count once
LANE_SD_FLOOR = 8.0               # px: min lane-position spread (bbox jitter scale)


def _arclen(pts):
    return sum(math.hypot(pts[i + 1][1] - pts[i][1], pts[i + 1][2] - pts[i][2])
               for i in range(len(pts) - 1))


def _end_speed(pts, tail=6):
    seg = pts[-tail:] if len(pts) > tail else pts
    df = seg[-1][0] - seg[0][0]
    return (math.hypot(seg[-1][1] - seg[0][1], seg[-1][2] - seg[0][2]) / df
            if df > 0 else 0.0)


def chain_tracks(recs):
    """B3 (docs/plan_boxclip_b3_chaining_2026-07-08.md): global fragment
    chaining. Edge A->B iff B plausibly continues A (the proven break rules,
    applied to EVERY pair, not just entry x exit). Greedy on (dist + 0.5*gap),
    each rec <=1 predecessor and <=1 successor; chains strictly extend in time
    (no cycles). Returns a list of chains (time-ordered lists of recs)."""
    import bisect
    rs = sorted(recs, key=lambda r: r["birth"][0])
    births = [r["birth"][0] for r in rs]
    # Tag-gating (the dedup_ceiling lesson): death->birth proximity CANNOT
    # tell a fragment continuation from a 1-2s-headway FOLLOWER on a dense
    # arterial. So only journey-INCOMPLETE tracks may chain: A must still lack
    # its exit crossing, B must still lack its entry crossing. A full journey
    # never chains — ungated, chaining merged complete NB vehicles into their
    # followers (fulls 3459->2951, NB 2.4%->28.9%).
    A_OK = ("entry_only", "no_crossing")
    B_OK = ("exit_only", "no_crossing")
    cands = []
    for ai, a in enumerate(rs):
        if a["tag"] not in A_OK:
            continue
        fa, xa, ya = a["death"]
        lo = bisect.bisect_left(births, fa + STITCH_MOVE_GAP[0])
        hi = bisect.bisect_right(births, fa + STITCH_STAT_GAP)
        a_slow = a["v_end"] < STITCH_STAT_SPEED
        for bi in range(lo, hi):
            if bi == ai:
                continue
            b = rs[bi]
            if b["tag"] not in B_OK:
                continue
            if b["death"][0] <= fa:          # chain must EXTEND in time
                continue
            gap = b["birth"][0] - fa
            dist = math.hypot(b["birth"][1] - xa, b["birth"][2] - ya)
            moving = (STITCH_MOVE_GAP[0] <= gap <= STITCH_MOVE_GAP[1]
                      and dist <= STITCH_MOVE_DIST)
            stat = a_slow and 0 < gap <= STITCH_STAT_GAP and dist <= STITCH_STAT_DIST
            if moving or stat:
                cands.append((dist + 0.5 * max(gap, 0.0), ai, bi))
    cands.sort(key=lambda c: c[0])
    succ, pred = {}, {}
    for _s, ai, bi in cands:
        if ai in succ or bi in pred:
            continue
        succ[ai] = bi
        pred[bi] = ai
    chains = []
    for i in range(len(rs)):
        if i in pred:
            continue
        idx = [i]
        while idx[-1] in succ:
            idx.append(succ[idx[-1]])
        chains.append([rs[k] for k in idx])
    return chains


def attribute(rec, channels, mode):
    """Assign the missing endpoint(s) of a truncated track by channel fit.
    mode 'entry': origin known, score LATE 60% vs channels out of it.
    mode 'exit':  dest known,  score EARLY 60% vs channels into it.
    mode 'free':  NOTHING known (no-crossing chain) — score ALL points vs ALL
                  channels; same acceptance bar.
    Returns (cell, best_px) or (None, reason)."""
    pts = rec["pts"]
    n = len(pts)
    if mode == "entry":
        sample = pts[int(n * 0.4):]
    elif mode == "exit":
        sample = pts[:max(1, int(n * 0.6))]
    else:
        sample = pts
    step = max(1, len(sample) // 40)
    sample = sample[::step]
    key = 0 if mode == "entry" else 1          # cell index that must match
    known = rec["o"] if mode == "entry" else rec["d"]
    scores = []
    for cell, poly in channels.items():
        if cell[0] == cell[1]:
            continue
        if mode != "free" and cell[key] != known:
            continue
        costs = []
        for i in range(len(sample)):
            _f, x, y = sample[i]
            _cpt, tan, dist = _closest_on_polyline(poly, (x, y))
            cost = dist
            # direction alignment vs the channel's forward tangent
            if i + 1 < len(sample):
                dx = sample[i + 1][1] - x
                dy = sample[i + 1][2] - y
                L = math.hypot(dx, dy)
                if L > 1.0 and tan is not None:
                    dot = max(-1.0, min(1.0, (dx * tan[0] + dy * tan[1]) / L))
                    cost += math.degrees(math.acos(dot)) * ATTR_ANGLE_PX_PER_DEG
            costs.append(cost)
        scores.append((sum(costs) / len(costs), cell))
    if not scores:
        return None, "no_candidates", None
    scores.sort()
    best, cell = scores[0]
    if best > ATTR_MAX_PX:
        return None, "poor_fit", None
    if len(scores) > 1 and best >= ATTR_MARGIN * scores[1][0]:
        # tied = every candidate that genuinely competes (fit ok, within band)
        tied = [(sc, c) for sc, c in scores
                if sc <= ATTR_MAX_PX and sc <= best / ATTR_MARGIN]
        return None, "ambiguous", tied
    return cell, best, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=2)
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--variant", default=None)
    ap.add_argument("--bank", default="evaluations/gtfree_bank_cam2_direct.json")
    ap.add_argument("--out-db", default=None,
                    help="default <workdir>/boxclip_cam<N>.db")
    ap.add_argument("--min-points", type=int, default=5,
                    help="ignore tracks shorter than this many points (noise)")
    ap.add_argument("--stage", choices=["A", "B"], default="B",
                    help="A = pure gates (full journeys only); B = +chain +attribute")
    ap.add_argument("--no-chain", action="store_true", help="stage B ablation")
    ap.add_argument("--no-attribute", action="store_true", help="stage B ablation")
    ap.add_argument("--no-stubs", action="store_true",
                    help="skip attributing no-crossing chains (plan step 5)")
    ap.add_argument("--no-prior", action="store_true",
                    help="B4 ablation: reject ambiguous pieces instead of "
                         "lane-posterior assignment")
    ap.add_argument("--print-gates", action="store_true")
    args = ap.parse_args()

    proj_db = f"data/projects/{args.project}/project.db"
    conn = sqlite3.connect(proj_db)
    v = conn.execute("SELECT path,file_size_bytes,total_frames,fps FROM videos "
                     "WHERE camera_id=? ORDER BY sort_order LIMIT 1",
                     (args.camera,)).fetchone()
    legs = {lid: tuple(json.loads(oz)[0]) for lid, oz in conn.execute(
        "SELECT leg_id, origin_zone FROM legs WHERE camera_id=?", (args.camera,))}
    conn.close()
    fps = float(v[3])
    ch, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path(args.project, args.camera, ch, args.variant or DEFAULT_VARIANT)
    tdir = tracks_path(pq)

    bank = json.loads(Path(args.bank).read_text())
    label = {(p["origin_leg_id"], p["destination_leg_id"]): p["movement_label"]
             for p in bank["paths"]}
    gates = build_gates(legs, bank["paths"])
    lanes = gate_lane_clusters(gates, bank["paths"])
    if args.print_gates:
        for leg, (p1, p2, inw) in sorted(gates.items()):
            print(f"leg {leg}: gate ({p1[0]:.0f},{p1[1]:.0f})-({p2[0]:.0f},{p2[1]:.0f})"
                  f"  inward=({inw[0]:+.2f},{inw[1]:+.2f})")

    n = int((tdir / "count.txt").read_text())
    rows = np.load(tdir / "rows.npy", mmap_mode="r")[:n]
    print(f"{n} track points; grouping by track_id...", flush=True)
    tracks = defaultdict(list)
    for tid, fr, x, y in rows:
        tracks[int(tid)].append((float(fr), float(x), float(y)))

    out_db = Path(args.out_db) if args.out_db else Path(
        rf"C:\Users\onkar\AppData\Local\Temp\ic_scratch_{args.project}\boxclip_cam{args.camera}.db")
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    c = sqlite3.connect(out_db)
    c.execute("CREATE TABLE vehicle_events (event_id INTEGER PRIMARY KEY, camera_id INT,"
              " origin_leg_id INT, destination_leg_id INT, movement TEXT,"
              " timestamp_real TEXT, rejected INT DEFAULT 0)")

    channels = {(p["origin_leg_id"], p["destination_leg_id"]): p["polyline"]
                for p in bank["paths"]}

    tags = Counter()
    recs = []
    for tid, pts in tracks.items():
        if len(pts) < args.min_points:
            tags["too_short"] += 1
            continue
        pts.sort()
        o, d, f_cross, f_out, o_pos, d_pos, tag = classify(pts, gates, lanes)
        tags[tag] += 1
        recs.append({"tid": tid, "pts": pts, "tag": tag, "o": o, "d": d,
                     "f": f_cross, "f_out": f_out, "o_pos": o_pos, "d_pos": d_pos,
                     "birth": pts[0], "death": pts[-1], "v_end": _end_speed(pts)})

    def _event(o, d, f_cross):
        mv = "u_turn" if o == d else label.get((o, d))
        if mv is None:
            return None
        ts = (VIDEO_START + timedelta(seconds=f_cross / fps)).isoformat()
        return (args.camera, o, d, mv, ts)

    src = Counter()      # (leg_pair_label, source) -> n, for the diagnosis matrix

    def _record(e, source):
        if e:
            ins.append(e)
            src[(f"{e[1]}->{e[2]} {e[3]}", source)] += 1

    ins = []
    if args.stage == "A":
        for r in recs:
            if r["tag"] == "full":
                _record(_event(r["o"], r["d"], r["f"]), "full")

    stageb = Counter()
    if args.stage == "B":
        # ---- B3: chain fragments globally, re-classify each merged chain ----
        base = recs
        if not args.no_chain:
            merged = []
            for ch in chain_tracks(recs):
                if len(ch) == 1:
                    merged.append(ch[0])
                    continue
                pts = sorted(p for r in ch for p in r["pts"])
                o, d, f_in, f_out, o_pos, d_pos, tag = classify(pts, gates, lanes)
                stageb[f"chain_to_{tag}"] += 1
                merged.append({"tid": ch[0]["tid"], "pts": pts, "tag": tag,
                               "o": o, "d": d, "f": f_in, "f_out": f_out,
                               "o_pos": o_pos, "d_pos": d_pos,
                               "birth": pts[0], "death": pts[-1],
                               "v_end": _end_speed(pts), "members": len(ch)})
            base = merged
            print("post-chain census:", dict(Counter(r["tag"] for r in base)))
        # ---- discovery AFTER chaining (mints templates for thin cells) ----
        discovered = discover_channels(base)
        attr_channels = dict(channels)          # drawn = fallback...
        attr_channels.update(discovered)        # ...discovered wins where supported
        print(f"discovered channels (>=5 full journeys): "
              f"{sorted(discovered)} ({len(discovered)}/{len(channels)} cells)")
        counted = defaultdict(list)             # cell -> origin frames (suspicious metric)
        prior = Counter()                       # resolved counts per cell
        lane_obs = defaultdict(list)            # (side, gate, cell) -> [proj]

        def _gate_proj(gate_leg, pos):
            p1, p2, _inw = gates[gate_leg]
            gl = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) or 1.0
            return ((pos[0] - p1[0]) * (p2[0] - p1[0])
                    + (pos[1] - p1[1]) * (p2[1] - p1[1])) / gl

        for r in base:
            if r["tag"] == "full":
                e = _event(r["o"], r["d"], r["f"])
                _record(e, "chain" if r.get("members", 1) > 1 else "full")
                if e:
                    cell = (r["o"], r["d"])
                    counted[cell].append(r["f"])
                    prior[cell] += 1
                    if r.get("o_pos"):
                        lane_obs[("entry", r["o"], cell)].append(_gate_proj(r["o"], r["o_pos"]))
                    if r.get("d_pos"):
                        lane_obs[("exit", r["d"], cell)].append(_gate_proj(r["d"], r["d_pos"]))

        lane_mu = {}
        for key, vs in lane_obs.items():
            if len(vs) >= 3:
                mu = sum(vs) / len(vs)
                sd = max((sum((v - mu) ** 2 for v in vs) / len(vs)) ** 0.5, LANE_SD_FLOOR)
                lane_mu[key] = (mu, sd)

        pr_credit = defaultdict(float)
        pr_assigned = Counter()

        def posterior_assign(r, tied, mode):
            """Lane-likelihood x volume-prior posterior over the tied cells;
            deterministic proportional assignment (credit accumulation)."""
            side = "entry" if mode == "entry" else "exit"
            gate = r["o"] if mode == "entry" else r["d"]
            pos = r["o_pos"] if mode == "entry" else r["d_pos"]
            if pos is None:
                return None
            proj = _gate_proj(gate, pos)
            ws = []
            for _sc, cell in tied:
                ms = lane_mu.get((side, gate, cell))
                if ms:
                    mu, sd = ms
                    like = math.exp(-0.5 * ((proj - mu) / sd) ** 2) / sd
                else:
                    like = 1.0 / 100.0          # no lane stats: ~uniform over the gate
                ws.append(((prior[cell] + 1) * like, cell))
            tot = sum(w for w, _c in ws)
            if tot <= 0:
                return None
            for w, cell in ws:
                pr_credit[cell] += w / tot
            best = max(ws, key=lambda wc: pr_credit[wc[1]] - pr_assigned[wc[1]])
            pr_assigned[best[1]] += 1
            return best[1]
        if not args.no_attribute:
            # Attribute to cells, then SAME-CELL entry/exit pairing for breaks
            # the chain rules can't span (>3s moving gaps): the two pieces of
            # one vehicle count ONCE. (Removing this when chains landed brought
            # the EB-right double-count straight back.)
            att_e, att_x = defaultdict(list), defaultdict(list)
            for r in sorted(base, key=lambda r: r["birth"][0]):
                if r["tag"] == "entry_only":
                    cell, why, tied = attribute(r, attr_channels, "entry")
                    srcname = "attr_entry"
                    if cell is None and why == "ambiguous" and not args.no_prior:
                        cell = posterior_assign(r, tied, "entry")
                        srcname = "prior"
                    if cell is None:
                        stageb[f"attr_entry_{why}"] += 1
                    else:
                        att_e[cell].append((r, srcname))
                elif r["tag"] == "exit_only":
                    cell, why, tied = attribute(r, attr_channels, "exit")
                    srcname = "attr_exit"
                    if cell is None and why == "ambiguous" and not args.no_prior:
                        cell = posterior_assign(r, tied, "exit")
                        srcname = "prior"
                    if cell is None:
                        stageb[f"attr_exit_{why}"] += 1
                    else:
                        att_x[cell].append((r, srcname))
            for cell in set(att_e) | set(att_x):
                es = sorted(att_e.get(cell, []), key=lambda t: t[0]["death"][0])
                xs = sorted(att_x.get(cell, []), key=lambda t: t[0]["birth"][0])
                used_x = set()
                for r, srcname in es:
                    mate = next((k for k, (rx, _s2) in enumerate(xs)
                                 if k not in used_x
                                 and 0 < rx["birth"][0] - r["death"][0] <= ATTR_PAIR_GAP),
                                None)
                    if mate is not None:
                        used_x.add(mate)
                        stageb["attr_paired"] += 1
                    else:
                        stageb["attributed_entry" if srcname != "prior"
                               else "prior_entry"] += 1
                    e = _event(cell[0], cell[1], r["f"])
                    _record(e, "attr_pair" if mate is not None else srcname)
                    if e:
                        counted[cell].append(r["f"])
                for k, (rx, srcname) in enumerate(xs):
                    if k in used_x:
                        continue
                    # birth frame approximates the unobserved origin crossing
                    e = _event(cell[0], cell[1], rx["birth"][0])
                    _record(e, srcname)
                    if e:
                        stageb["attributed_exit" if srcname != "prior"
                               else "prior_exit"] += 1
                        counted[cell].append(rx["birth"][0])
            if not args.no_stubs:
                for r in base:
                    if r["tag"] != "no_crossing":
                        continue
                    if _arclen(r["pts"]) < STUB_MIN_ARC:
                        stageb["stub_too_short"] += 1
                        continue
                    cell, why, _tied = attribute(r, attr_channels, "free")
                    if cell is None:
                        stageb[f"stub_{why}"] += 1
                        continue
                    # suspicious = plausibly the same vehicle as a counted
                    # journey in this cell -> SKIPPED (first run counted them:
                    # 193/240 suspicious, EB-right +316 — pure double-count)
                    lo, hi = r["birth"][0] - 125, r["death"][0] + 125
                    if any(lo <= f <= hi for f in counted[cell]):
                        stageb["stub_suspicious_skipped"] += 1
                        continue
                    e = _event(cell[0], cell[1], r["birth"][0])
                    _record(e, "stub")
                    if e:
                        stageb["attributed_stub"] += 1
                        counted[cell].append(r["birth"][0])

    c.executemany("INSERT INTO vehicle_events (camera_id, origin_leg_id,"
                  " destination_leg_id, movement, timestamp_real) VALUES (?,?,?,?,?)", ins)
    c.commit(); c.close()

    total = sum(tags.values())
    print(f"\ntracks: {total}   (stage {args.stage}"
          f"{' no-chain' if args.no_chain else ''}"
          f"{' no-attribute' if args.no_attribute else ''}"
          f"{' no-stubs' if args.no_stubs else ''})")
    for k, v2 in tags.most_common():
        print(f"  {k:<14} {v2:>6}  ({v2/total*100:.1f}%)")
    if stageb:
        print("stage B:")
        for k, v2 in sorted(stageb.items()):
            print(f"  {k:<24} {v2:>6}")
    SOURCES = ("full", "chain", "attr_entry", "attr_exit", "prior", "stub")
    print("\nper-cell source matrix (cells with >=20 events):")
    cells_all = sorted({cl for cl, _s in src},
                       key=lambda cl: -sum(src.get((cl, s2), 0) for s2 in SOURCES))
    print(f"{'cell':<22}{'full':>6}{'chain':>7}{'a_ent':>7}{'a_ex':>6}{'prior':>7}{'stub':>6}")
    for cl in cells_all:
        row = [src.get((cl, s2), 0) for s2 in SOURCES]
        if sum(row) >= 20:
            print(f"{cl:<22}{row[0]:>6}{row[1]:>7}{row[2]:>7}{row[3]:>6}{row[4]:>7}{row[5]:>6}")
    print(f"\nevents written: {len(ins)} -> {out_db}")
    print("score with: py scripts/measure_cam2_reid_spike.py --db", out_db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
