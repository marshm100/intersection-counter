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


def classify(track, gates):
    """track: [(frame,x,y)...] -> (origin_leg, dest_leg, origin_cross_frame, tags)."""
    crossings = []          # (frame_interp, leg, inward: bool)
    for i in range(len(track) - 1):
        f0, x0, y0 = track[i]
        f1, x1, y1 = track[i + 1]
        for leg, (p1, p2, inw) in gates.items():
            t = _seg_cross((x0, y0), (x1, y1), p1, p2)
            if t is None:
                continue
            step = (x1 - x0, y1 - y0)
            inward = (step[0] * inw[0] + step[1] * inw[1]) > 0
            crossings.append((f0 + t * (f1 - f0), leg, inward))
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
            g = gates[origin[1]]
            mouth_far = max(
                abs((x - (g[0][0] + g[1][0]) / 2) * g[2][0]
                    + (y - (g[0][1] + g[1][1]) / 2) * g[2][1])
                for f, x, y in track if origin[0] <= f <= dest[0]) if any(
                    origin[0] <= f <= dest[0] for f, _x, _y in track) else 0.0
            if (dest[0] - origin[0]) < UTURN_MIN_FRAMES or mouth_far < UTURN_MIN_PX:
                return origin[1], None, origin[0], "entry_only"
        return origin[1], dest[1], origin[0], "full"
    if origin:
        return origin[1], None, origin[0], "entry_only"
    if dest:
        return None, dest[1], dest[0], "exit_only"
    return None, None, None, "no_crossing"


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

    tags = Counter()
    cells = Counter()
    ins = []
    for tid, pts in tracks.items():
        if len(pts) < args.min_points:
            tags["too_short"] += 1
            continue
        pts.sort()
        o, d, f_cross, tag = classify(pts, gates)
        tags[tag] += 1
        if tag != "full":
            continue
        mv = "u_turn" if o == d else label.get((o, d))
        if mv is None:
            tags["unlabeled_cell"] += 1
            continue
        mv = {"through": "through", "left": "left", "right": "right",
              "u_turn": "u_turn"}.get(mv, mv)
        ts = (VIDEO_START + timedelta(seconds=f_cross / fps)).isoformat()
        cells[(o, d, mv)] += 1
        ins.append((args.camera, o, d, mv, ts))
    c.executemany("INSERT INTO vehicle_events (camera_id, origin_leg_id,"
                  " destination_leg_id, movement, timestamp_real) VALUES (?,?,?,?,?)", ins)
    c.commit(); c.close()

    total = sum(tags.values())
    print(f"\ntracks: {total}")
    for k, v2 in tags.most_common():
        print(f"  {k:<14} {v2:>6}  ({v2/total*100:.1f}%)")
    print(f"\nevents written: {len(ins)} -> {out_db}")
    print("score with: py scripts/measure_cam2_reid_spike.py --db", out_db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
