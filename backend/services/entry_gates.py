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

# Track-derived gate orientation (plan_v2_gate_axis_2026-08-10). The gate
# must lie ACROSS the road; the shipped source for that direction is the
# mean of the operator's channel tangents at the mouth, and it is measured
# unreliable (FM51 legs 1/2 at 77.9/85.4 deg from actual travel; corridor
# cam2 leg 29 at 55.0, cam4 leg 33 at 49.4). These constants govern
# deriving the axis from the window's own tracks instead.
AXIS_RADIUS_PX = 90.0     # neighbourhood around the mouth
AXIS_MIN_DISP_PX = 8.0    # ignore parked/jitter tracks
AXIS_MIN_TRACKS = 30      # support floor
AXIS_MIN_R = 0.30         # axial concentration floor (resultant length)


def derive_gate_axes(legs, tracks, radius_px: float = AXIS_RADIUS_PX,
                     min_tracks: int = AXIS_MIN_TRACKS,
                     min_r: float = AXIS_MIN_R) -> dict:
    """{leg_id: (ax, ay)} road AXIS at each mouth, from the tracks' own
    motion. Unit vector, sign meaningless (an axis, not a direction).

    Traffic through a mouth is BIDIRECTIONAL, so averaging displacement
    vectors cancels inbound against outbound. This uses the axial
    estimator instead: average (cos 2t, sin 2t) and halve, which is
    invariant to each track's direction sign by construction. A leg is
    OMITTED (caller falls back to the channel tangents) unless it has
    min_tracks contributors and resultant length >= min_r — a mouth whose
    traffic has no dominant axis must not have one invented for it.

    Pure function of (mouths, tracks, constants): no bank, no candidate
    paths, so injecting or ablating candidates cannot rotate a gate (the
    stability rule pipeline._gate_paths exists to protect).
    """
    out = {}
    for leg, mouth in legs.items():
        sx = sy = 0.0
        n = 0
        for tr in tracks:
            near = [p for p in tr
                    if math.hypot(p[-2] - mouth[0], p[-1] - mouth[1]) <= radius_px]
            if len(near) < 2:
                continue
            dx = near[-1][-2] - near[0][-2]
            dy = near[-1][-1] - near[0][-1]
            L = math.hypot(dx, dy)
            if L < AXIS_MIN_DISP_PX:
                continue
            t = math.atan2(dy / L, dx / L)
            sx += math.cos(2.0 * t)
            sy += math.sin(2.0 * t)
            n += 1
        if n < min_tracks:
            continue
        r = math.hypot(sx, sy) / n          # axial concentration in [0,1]
        if r < min_r:
            continue
        t2 = math.atan2(sy / n, sx / n) / 2.0
        out[leg] = (math.cos(t2), math.sin(t2))
    return out


def parse_gate_segment(val):
    """Operator-drawn gate line -> ((x1,y1),(x2,y2)) | None. Accepts the
    raw JSON string from the legs row or an already-parsed list; anything
    that is not exactly two [x, y] points is None (never raises — a
    malformed row must not take the pipeline down)."""
    if val is None:
        return None
    if isinstance(val, str):
        import json
        try:
            val = json.loads(val)
        except (TypeError, ValueError):
            return None
    try:
        if len(val) != 2:
            return None
        (x1, y1), (x2, y2) = val[0], val[1]
        return ((float(x1), float(y1)), (float(x2), float(y2)))
    except (TypeError, ValueError):
        return None


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


def build_gates(legs, bank_paths, leg_head=None, leg_axes=None,
                leg_gates=None):
    """{leg_id: (p1, p2, inward_normal)} — gate segment + which way is 'in'.

    Orientation: mean of the leg's channels' local tangents at their closest
    approach to the mouth; the gate is the PERPENDICULAR through the mouth.
    Span: the channels' closest points projected on the gate direction give the
    lane spread; pad + floor. Inward normal points at the mouth centroid.
    A leg with NO channels in the bank (e.g. cam1's zero-traffic driveway leg)
    falls back to the operator's reference_heading for the road direction.

    leg_axes: optional {leg_id: (ax, ay)} road axes measured from the
    window's own tracks (derive_gate_axes). Where a leg has one it REPLACES
    the channel-tangent direction — the drawn artifacts are measured
    unreliable — while span, inward sign and de-overlap are unchanged.
    Legs absent from the map keep the channel-tangent behavior exactly.

    leg_gates: optional {leg_id: ((x1,y1),(x2,y2))} OPERATOR-DRAWN gate
    lines (B1 2026-08-21 — the G-PF2-1 negative measured that derived
    gates are the accuracy cap: a 94 px stub above the travel lanes
    zeroed a 379-vehicle movement). A drawn segment is used VERBATIM:
    its endpoints are the gate, the road direction is its perpendicular,
    the inward sign comes from the same centroid test, and the entire
    tangent/axis/span/pad/floor derivation is skipped. Highest
    precedence; legs without one keep the derived behavior exactly;
    de-overlap still runs over all gates (drawn included) as safety."""
    centroid = (sum(m[0] for m in legs.values()) / len(legs),
                sum(m[1] for m in legs.values()) / len(legs))
    gates = {}
    for leg, mouth in legs.items():
        drawn = (leg_gates or {}).get(leg)
        if drawn:
            p1, p2 = drawn
            gx, gy = p2[0] - p1[0], p2[1] - p1[1]
            n = math.hypot(gx, gy) or 1.0
            gx, gy = gx / n, gy / n
            tx, ty = -gy, gx                    # road dir = perpendicular
            s = 1.0 if ((centroid[0] - mouth[0]) * tx
                        + (centroid[1] - mouth[1]) * ty) > 0 else -1.0
            gates[leg] = (tuple(p1), tuple(p2), (s * tx, s * ty))
            continue
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
        if (leg_axes or {}).get(leg):
            tx, ty = leg_axes[leg]
        else:
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


def all_crossings(track, gates, fps):
    """Every gate crossing of a track, jitter-collapsed, time-ordered:
    [(frame_interp, leg, inward: bool, pos: (x, y)), ...].

    Factored verbatim out of classify() (2026-08-19, A3 block) so the
    splice splitter can see EVERY crossing — classify() keeps only
    entries[0]/exits[-1], which for a Type-1 splice returns the THIEF's
    exit. One source of truth: classify() calls this."""
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
    return kept


def classify(track, gates, fps, lanes=None):
    """track: [(frame,x,y)...] ->
    (origin_leg, dest_leg, origin_frame, dest_frame, origin_pos, dest_pos, tag)."""
    kept = all_crossings(track, gates, fps)
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


def cell_census(tracks, gates, fps, min_points: int = 5):
    """Per-cell observed n from GATE EVIDENCE alone — the merge-expecteds
    source when the partial-evidence posterior is on
    (docs/plan_posterior_half_2026-07-15.md stage 3).

    The legacy expecteds came from the corpus bank builder's own shape
    assignment, i.e. from FLIP-prone matching — which starved cells whose
    traffic was being stolen (measured: 17/14 genuine box-full EB-lefts per
    held-out window merge-rejected). This census is de-flipped by
    construction and stays GT-free and scale-1 (corpus-window observed n):

      - box-FULL journeys count 1.0 at their (origin, dest) cell;
      - entry-only tracks distribute over their origin's cells by the full
        census's own proportions;
      - exit-only tracks distribute over their destination's cells likewise;
      - no-crossing tracks carry no evidence and are ignored.

    Truncated evidence is allocated by the census's OWN full-journey mix —
    never by bank supports or the posterior's output (the circularity
    guard). tracks: iterables of (frame, x, y). Returns {(o, d): float}.
    """
    full: dict = {}
    entry_only: dict = {}
    exit_only: dict = {}
    for pts in tracks:
        if len(pts) < min_points:
            continue
        o, d, *_rest, tag = classify(pts, gates, fps)
        if tag == "full":
            full[(o, d)] = full.get((o, d), 0) + 1
        elif tag == "entry_only":
            entry_only[o] = entry_only.get(o, 0) + 1
        elif tag == "exit_only":
            exit_only[d] = exit_only.get(d, 0) + 1
    expected = {cell: float(n) for cell, n in full.items()}
    for o, n in entry_only.items():
        cells = {c: v for c, v in full.items() if c[0] == o}
        tot = float(sum(cells.values()))
        if tot > 0:
            for c, v in cells.items():
                expected[c] += n * v / tot
    for d, n in exit_only.items():
        cells = {c: v for c, v in full.items() if c[1] == d}
        tot = float(sum(cells.values()))
        if tot > 0:
            for c, v in cells.items():
                expected[c] += n * v / tot
    return expected
