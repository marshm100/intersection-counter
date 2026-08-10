"""FM51 cam2 gate geometry: why don't the gates engage?

Computes the real gate segments (pre- and post-de-overlap), measures how
much traffic actually reaches each gate, and locates the arms EMPIRICALLY
from track endpoints so drawn-vs-actual is visible. Corridor cam2 is run
alongside as the healthy control.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from backend.database import get_connection, list_paths_for_camera   # noqa: E402
from backend.services.detection_cache import parquet_path            # noqa: E402
from backend.services.entry_gates import (                           # noqa: E402
    GATE_MIN_HALF, GATE_PAD_PX, _closest_on_polyline, build_gates, classify,
)
from backend.services.pass2_replay import load_dump, tracks_dir      # noqa: E402

SITES = [("0acb12c0", 2, "ftv2n_am", "FM51 cam2"),
         ("97a7849a", 2, "study_1100", "corridor cam2 (healthy control)")]


def raw_gates(legs, bank_paths, leg_head):
    """build_gates' per-leg construction WITHOUT the de-overlap pass."""
    centroid = (sum(m[0] for m in legs.values()) / len(legs),
                sum(m[1] for m in legs.values()) / len(legs))
    out = {}
    for leg, mouth in legs.items():
        tangents, cpts = [], []
        for p in bank_paths:
            if p["origin_leg_id"] != leg and p["destination_leg_id"] != leg:
                continue
            cpt, tan, _ = _closest_on_polyline(p["polyline"], mouth)
            if cpt is None:
                continue
            if tangents and (tan[0]*tangents[0][0] + tan[1]*tangents[0][1]) < 0:
                tan = (-tan[0], -tan[1])
            tangents.append(tan)
            cpts.append(cpt)
        n_chan = len(tangents)
        if not tangents:
            hd = math.radians(float((leg_head or {}).get(leg) or 0.0))
            tangents = [(math.sin(hd), -math.cos(hd))]
        tx = sum(t[0] for t in tangents) / len(tangents)
        ty = sum(t[1] for t in tangents) / len(tangents)
        n = math.hypot(tx, ty) or 1.0
        tx, ty = tx / n, ty / n
        gx, gy = -ty, tx
        spread = [(c[0]-mouth[0])*gx + (c[1]-mouth[1])*gy for c in cpts] + [0.0]
        half = max(GATE_MIN_HALF,
                   max(abs(min(spread)), abs(max(spread))) + GATE_PAD_PX)
        out[leg] = ((mouth[0]-gx*half, mouth[1]-gy*half),
                    (mouth[0]+gx*half, mouth[1]+gy*half), n_chan, half,
                    (tx, ty))
    return out


def seg_len(p1, p2):
    return math.hypot(p2[0]-p1[0], p2[1]-p1[1])


def dist_pt_seg(px, py, a, b):
    vx, vy = b[0]-a[0], b[1]-a[1]
    L2 = vx*vx + vy*vy
    if L2 < 1e-9:
        return math.hypot(px-a[0], py-a[1])
    t = max(0.0, min(1.0, ((px-a[0])*vx + (py-a[1])*vy) / L2))
    return math.hypot(px-(a[0]+t*vx), py-(a[1]+t*vy))


for proj, cam, variant, tag in SITES:
    conn = get_connection(proj)
    chash = conn.execute("SELECT content_hash FROM videos WHERE camera_id=? "
                         "ORDER BY sort_order LIMIT 1", (cam,)).fetchone()[0]
    mouths, heads, labels = {}, {}, {}
    for lid, lab, oz, rh in conn.execute(
            "SELECT leg_id,label,origin_zone,reference_heading FROM legs "
            "WHERE camera_id=?", (cam,)):
        if oz:
            mouths[lid] = tuple(json.loads(oz)[0])
            heads[lid] = rh
            labels[lid] = lab
    conn.close()
    paths = list_paths_for_camera(proj, cam)
    gr = raw_gates(mouths, paths, heads)
    gf = build_gates(mouths, paths, heads)

    rows = load_dump(tracks_dir(parquet_path(proj, cam, chash, variant)))
    tracks = defaultdict(list)
    for r in rows:
        tracks[int(r[0])].append((float(r[1]), float(r[2]), float(r[3])))

    print(f"\n{'='*72}\n{tag}  ({variant}, {len(tracks)} tracks)")
    print(f"{'leg':>4} {'label':<10} {'mouth':>14} {'chans':>5} "
          f"{'half':>6} {'len_raw':>8} {'len_final':>9} {'shrunk':>7}")
    for lid in sorted(mouths):
        p1r, p2r, nch, half, tan = gr[lid]
        p1f, p2f, _inw = gf[lid]
        lr, lf = seg_len(p1r, p2r), seg_len(p1f, p2f)
        print(f"{lid:>4} {labels[lid][:10]:<10} "
              f"({mouths[lid][0]:6.1f},{mouths[lid][1]:6.1f}) {nch:>5} "
              f"{half:6.1f} {lr:8.1f} {lf:9.1f} "
              f"{('YES -' + str(round(100*(1-lf/lr))) + '%') if lf < lr - 0.5 else '-':>7}")

    # how much traffic gets near each gate at all
    near = defaultdict(int)
    for tid, tr in tracks.items():
        for lid in mouths:
            p1, p2, _ = gf[lid]
            if any(dist_pt_seg(x, y, p1, p2) <= 15.0 for _f, x, y in tr):
                near[lid] += 1
    print("  tracks passing within 15px of each gate:",
          {lid: near.get(lid, 0) for lid in sorted(mouths)})

    tags = defaultdict(int)
    for tid, tr in tracks.items():
        tags[classify(tr, gf, 10.0)[6]] += 1
    print("  classify:", dict(tags))

    # EMPIRICAL arms: where do tracks actually begin and end?
    def cluster(pts, r=60.0):
        cl = []
        for p in pts:
            for c in cl:
                if math.hypot(p[0]-c[0][0], p[1]-c[0][1]) <= r:
                    c[1].append(p)
                    c[0] = (sum(q[0] for q in c[1])/len(c[1]),
                            sum(q[1] for q in c[1])/len(c[1]))
                    break
            else:
                cl.append([p, [p]])
        return sorted(((c[0], len(c[1])) for c in cl), key=lambda x: -x[1])

    long_tracks = [tr for tr in tracks.values() if len(tr) >= 15]
    starts = [(t[0][1], t[0][2]) for t in long_tracks]
    ends = [(t[-1][1], t[-1][2]) for t in long_tracks]
    print(f"  empirical ENTRY clusters (>=15pt tracks, top 5 of "
          f"{len(long_tracks)}):")
    for c, n in cluster(starts)[:5]:
        best = min(mouths, key=lambda l: math.hypot(c[0]-mouths[l][0],
                                                    c[1]-mouths[l][1]))
        d = math.hypot(c[0]-mouths[best][0], c[1]-mouths[best][1])
        print(f"     ({c[0]:6.1f},{c[1]:6.1f})  n={n:5d}   nearest drawn "
              f"mouth: leg {best} ({labels[best][:8]}) at {d:5.1f}px")
    print("  empirical EXIT clusters (top 5):")
    for c, n in cluster(ends)[:5]:
        best = min(mouths, key=lambda l: math.hypot(c[0]-mouths[l][0],
                                                    c[1]-mouths[l][1]))
        d = math.hypot(c[0]-mouths[best][0], c[1]-mouths[best][1])
        print(f"     ({c[0]:6.1f},{c[1]:6.1f})  n={n:5d}   nearest drawn "
              f"mouth: leg {best} ({labels[best][:8]}) at {d:5.1f}px")
