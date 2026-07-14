"""Entry/exit gates on the operator-leg box perimeter (item-8 mechanism 1).

Verbatim port of the box-clip gate machinery from scripts/boxclip_pass2.py
(the Gate-B diagnostic, proven at live parity on cam2) so the pipeline's
origin-evidence gate and the script share ONE implementation — the
turn_merge port pattern. Everything here is GT-free: operator calibration
geometry + the applied bank's own polylines.

classify(track, gates, fps) -> (origin_leg, dest_leg, origin_frame,
dest_frame, origin_pos, dest_pos, tag) with tag in
full | entry_only | exit_only | no_crossing.
"""
from __future__ import annotations

import math

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


def build_gates(legs, bank_paths, leg_head=None):
    """{leg_id: (p1, p2, inward_normal)} — gate segment + which way is 'in'.

    Orientation: mean of the leg's channels' local tangents at their closest
    approach to the mouth; the gate is the PERPENDICULAR through the mouth.
    Span: the channels' closest points projected on the gate direction give the
    lane spread; pad + floor. Inward normal points at the mouth centroid.
    A leg with NO channels in the bank (e.g. cam1's zero-traffic driveway leg)
    falls back to the operator's reference_heading for the road direction."""
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
        if not tangents:
            hd = math.radians(float((leg_head or {}).get(leg) or 0.0))
            # reference_heading: 0=N, clockwise; screen y grows downward
            tangents = [(math.sin(hd), -math.cos(hd))]
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


# Time-based constants (SECONDS / px-per-second, converted via fps at use
# sites): cams run 10-25 fps, and frame-based constants silently mean
# DIFFERENT durations per camera — a frozen-constant sweep must freeze TIME.
# Values chosen on cam2@25fps are preserved exactly (50f=2.0s etc).
JITTER_S = 2.0          # same-gate crossings within this = bbox jitter, keep first
UTURN_MIN_S = 5.0       # a real u-turn dwells in the box at least this long...
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


def classify(track, gates, fps, lanes=None):
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
        if kept and c[1] == kept[-1][1] and (c[0] - kept[-1][0]) < JITTER_S * fps:
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
            if ((dest[0] - origin[0]) < UTURN_MIN_S * fps or mouth_far < UTURN_MIN_PX
                    or lane_shift < UTURN_MIN_LANE_SHIFT or not lane_ok):
                return origin[1], None, origin[0], None, origin[3], None, "entry_only"
        return origin[1], dest[1], origin[0], dest[0], origin[3], dest[3], "full"
    if origin:
        return origin[1], None, origin[0], None, origin[3], None, "entry_only"
    if dest:
        return None, dest[1], dest[0], None, None, dest[3], "exit_only"
    return None, None, None, None, None, None, "no_crossing"
