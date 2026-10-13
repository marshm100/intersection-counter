"""THE MOUTH FROM MOTION + COUNT ONCE (arm mm, declared 2026-10-13,
docs/plan_basis_2026-09-11.md; operator: "the most common one is not the same
as the logical trajectory").

A counted track whose entry crossing was not witnessed (gate tag exit_only)
has its entry line decided from what the car itself did - where it waited,
where and which way it moved, where the ray of its motion comes from, which
vehicle hid it - against LANE MAPS built from the same window's fully seen
journeys. Never from how many other cars make a movement. The mirror decides
the exit line of an entry_only track. COUNT ONCE: two counted tracks with one
movement that reach every spot of their shared path at the same moment are
one car (a queued car carrying two ids), unlike a follower, which reaches
each spot a headway later.

Pure on dump rows (tid, frame, cx, cy, w, h, ...) + gates + the working DB.
Write-then-modify like the other pass-2 post-passes; apply=False returns the
decisions without touching the DB (the offline check).
"""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

_TAG_RANK = {"full": 0, "entry_only": 1, "exit_only": 1}


# --- per-track kinematics ----------------------------------------------------

@dataclass
class Track:
    tid: int
    f: np.ndarray          # frames
    x: np.ndarray          # bottom-centre anchor (the point the gates use)
    y: np.ndarray
    cx: np.ndarray         # box centre and size (occlusion test)
    cy: np.ndarray
    w: np.ndarray
    h: np.ndarray
    vx: np.ndarray = field(default=None)   # px / s over +-HEADING_VELOCITY_S
    vy: np.ndarray = field(default=None)

    @property
    def speed(self) -> np.ndarray:
        return np.hypot(self.vx, self.vy)


def tracks_from_rows(rows: np.ndarray, fps: float, tids=None) -> dict[int, Track]:
    """Per-track arrays with smoothed velocity (the jitter of a 15-30 px box
    averages out over +-HEADING_VELOCITY_S; only the direction and whether the
    car is moving are used)."""
    from backend.config import HEADING_VELOCITY_S
    arr = np.asarray(rows, dtype=float)
    if tids is not None:
        arr = arr[np.isin(arr[:, 0], np.fromiter(tids, float))]
    if not len(arr):
        return {}
    arr = arr[np.lexsort((arr[:, 1], arr[:, 0]))]
    ids, i0 = np.unique(arr[:, 0], return_index=True)
    k = HEADING_VELOCITY_S * fps
    out = {}
    for tid, a in zip(ids.astype(int), np.split(arr, i0[1:])):
        f = a[:, 1]
        x, y = a[:, 2], a[:, 3] + a[:, 5] / 2.0
        j1 = np.searchsorted(f, f - k, side="left")
        j2 = np.clip(np.searchsorted(f, f + k, side="right") - 1, 0, len(f) - 1)
        dt = np.maximum((f[j2] - f[j1]) / fps, 1e-6)
        vx = np.where(j2 > j1, (x[j2] - x[j1]) / dt, 0.0)
        vy = np.where(j2 > j1, (y[j2] - y[j1]) / dt, 0.0)
        out[int(tid)] = Track(int(tid), f, x, y, a[:, 2], a[:, 3], a[:, 4], a[:, 5], vx, vy)
    return out


# --- lane maps ---------------------------------------------------------------

@dataclass
class LaneMaps:
    cell: float
    lanes: dict                 # (o, d) -> {(ix, iy): [n_tracks, hx, hy]}
    queues: dict                # o -> set of (ix, iy) cells where o's cars stood
    n_clean: dict               # (o, d) -> clean tracks
    labels: dict                # (o, d) -> movement label used by the clean events

    def key(self, x, y):
        return int(x // self.cell), int(y // self.cell)


def _entry_index(t: Track, gate) -> int:
    """Index of the first inward crossing of gate (p1, p2, inward) by the
    anchor; the last index if none (the whole track is approach)."""
    from backend.services.entry_gates import _seg_cross
    p1, p2, inw = gate
    for i in range(len(t.f) - 1):
        a, b = (t.x[i], t.y[i]), (t.x[i + 1], t.y[i + 1])
        if _seg_cross(a, b, p1, p2) is not None and \
                (b[0] - a[0]) * inw[0] + (b[1] - a[1]) * inw[1] > 0:
            return i
    return len(t.f) - 1


def build_lane_maps(tracks: dict[int, Track], clean: dict[int, tuple],
                    gates: dict) -> LaneMaps:
    """clean: tid -> (origin, dest, movement) for fully seen counted journeys."""
    from backend.config import LANE_CELL_PX
    from backend.services.track_chains import STITCH_STAT_SPEED_PXS
    lm = LaneMaps(float(LANE_CELL_PX), {}, {}, defaultdict(int), {})
    lane_tracks = defaultdict(lambda: defaultdict(set))
    lane_head = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    queue_tracks = defaultdict(lambda: defaultdict(set))
    label_votes = defaultdict(lambda: defaultdict(int))
    for tid, (o, d, mv) in clean.items():
        t = tracks.get(tid)
        if t is None or len(t.f) < 2:
            continue
        lm.n_clean[(o, d)] += 1
        label_votes[(o, d)][mv] += 1
        sp = t.speed
        ie = _entry_index(t, gates[o]) if o in gates else -1
        for i in range(len(t.f)):
            c = lm.key(t.x[i], t.y[i])
            if sp[i] >= STITCH_STAT_SPEED_PXS:
                lane_tracks[(o, d)][c].add(tid)
                h = lane_head[(o, d)][c]
                h[0] += t.vx[i] / sp[i]
                h[1] += t.vy[i] / sp[i]
            elif i <= ie:
                queue_tracks[o][c].add(tid)
    for od, cells in lane_tracks.items():
        lm.lanes[od] = {}
        for c, ts in cells.items():
            if len(ts) >= 2:                       # driven by two cars at least
                hx, hy = lane_head[od][c]
                n = math.hypot(hx, hy) or 1.0
                lm.lanes[od][c] = (len(ts), hx / n, hy / n)
    for o, cells in queue_tracks.items():
        lm.queues[o] = {c for c, ts in cells.items() if len(ts) >= 2}
    lm.labels = {od: max(v, key=v.get) for od, v in label_votes.items()}
    return lm


# --- the resolver ---------------------------------------------------------------

def _near(cells: set | dict, c) -> bool:
    return any((c[0] + dx, c[1] + dy) in cells for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def _lane_fit(t: Track, idx: np.ndarray, lane: dict, lm: LaneMaps) -> float:
    from backend.config import TRAJECTORY_THROUGH_MAX_ANGLE
    if not len(idx) or not lane:
        return 0.0
    cos_tol = math.cos(math.radians(TRAJECTORY_THROUGH_MAX_ANGLE))
    hits = 0
    for i in idx:
        cell = lane.get(lm.key(t.x[i], t.y[i]))
        if cell is None:
            continue
        s = math.hypot(t.vx[i], t.vy[i]) or 1.0
        if (t.vx[i] * cell[1] + t.vy[i] * cell[2]) / s >= cos_tol:
            hits += 1
    return hits / len(idx)


def _lane_votes(t: Track, idx: np.ndarray, lanes: dict, lm: LaneMaps) -> dict:
    """THE EXCLUSIVE CELLS (step 3b): over the given moving points, a point
    votes for a candidate only where that candidate's lane alone runs (cell
    and heading); where the lanes coincide - cam2's far corner - a point says
    nothing either way, so a long shared tail neither dilutes nor decides."""
    from backend.config import TRAJECTORY_THROUGH_MAX_ANGLE
    cos_tol = math.cos(math.radians(TRAJECTORY_THROUGH_MAX_ANGLE))
    votes = {k: 0 for k in lanes}
    for i in idx:
        c = lm.key(t.x[i], t.y[i])
        s = math.hypot(t.vx[i], t.vy[i]) or 1.0
        hit = [k for k, lane in lanes.items() if (cell := lane.get(c)) is not None
               and (t.vx[i] * cell[1] + t.vy[i] * cell[2]) / s >= cos_tol]
        if len(hit) == 1:
            votes[hit[0]] += 1
    return votes


def _reverses(t: Track, fps: float) -> bool:
    """The car's own visible track turns back: the mean heading of its first
    and of its last MOTION_FIT_S s of motion differ by at least
    TRAJECTORY_UTURN_MIN_ANGLE."""
    from backend.config import TRAJECTORY_UTURN_MIN_ANGLE
    a, b = _moving_window(t, fps, True), _moving_window(t, fps, False)
    if not len(a) or not len(b):
        return False
    ha = math.atan2(float(np.mean(t.vy[a])), float(np.mean(t.vx[a])))
    hb = math.atan2(float(np.mean(t.vy[b])), float(np.mean(t.vx[b])))
    dh = abs(math.degrees(ha - hb)) % 360.0
    return min(dh, 360.0 - dh) >= TRAJECTORY_UTURN_MIN_ANGLE


def _moving_window(t: Track, fps: float, at_start: bool, whole: bool = False) -> np.ndarray:
    """Indices of the first (or last) MOTION_FIT_S seconds of motion; with
    whole=True every moving index of the visible track."""
    from backend.config import MOTION_FIT_S
    from backend.services.track_chains import STITCH_STAT_SPEED_PXS
    mv = np.nonzero(t.speed >= STITCH_STAT_SPEED_PXS)[0]
    if not len(mv) or whole:
        return mv
    span = MOTION_FIT_S * fps
    if at_start:
        return mv[t.f[mv] <= t.f[mv[0]] + span]
    return mv[t.f[mv] >= t.f[mv[-1]] - span]


def incidence_deg(vel, p1, p2) -> float:
    """Angle between a motion and a line: 90 = head-on, 0 = along it."""
    lx, ly = p2[0] - p1[0], p2[1] - p1[1]
    n = math.hypot(vel[0], vel[1]) * math.hypot(lx, ly)
    if n < 1e-9:
        return 0.0
    return math.degrees(math.asin(min(1.0, abs(vel[0] * ly - vel[1] * lx) / n)))


def ray_leg(pt, vel, gates: dict, entering: bool) -> tuple[int | None, float | None, list]:
    """entry_gates.nearest_line_in_direction with THE GRAZE: a line the ray
    meets nearly along it (across < along / EXIT_GRAZE_RATIO, the grazed-exit
    definition of riding a line) is no evidence the car came through (went
    out through) it, so the ray goes on to the next line it really crosses.
    Returns (leg, incidence deg, grazed legs passed on the way)."""
    from backend.config import EXIT_GRAZE_RATIO, GATE_EXTENSION_MARGIN
    from backend.services.entry_gates import _seg_cross, extend_gates
    n = math.hypot(vel[0], vel[1])
    if n < 1e-9:
        return None, None, []
    ux, uy = vel[0] / n, vel[1] / n
    if entering:
        ux, uy = -ux, -uy
    q = (pt[0] + ux * 3000.0, pt[1] + uy * 3000.0)
    min_inc = math.degrees(math.atan(1.0 / EXIT_GRAZE_RATIO))
    hits = []
    for lg, (p1, p2, inw) in extend_gates(gates, GATE_EXTENSION_MARGIN).items():
        agree = vel[0] * inw[0] + vel[1] * inw[1]
        if (entering and agree <= 0) or (not entering and agree >= 0):
            continue
        s = _seg_cross(pt, q, p1, p2)
        if s is not None:
            hits.append((s, lg, incidence_deg(vel, p1, p2)))
    grazed = []
    for _s, lg, inc in sorted(hits):
        if inc >= min_inc:
            return lg, inc, grazed
        grazed.append(lg)
    return None, None, grazed


def _waited_leg(t: Track, fps: float, lm: LaneMaps, cands) -> int | None:
    from backend.config import MOTION_WAIT_S
    from backend.services.track_chains import STITCH_STAT_SPEED_PXS
    still = t.speed < STITCH_STAT_SPEED_PXS
    if not still[0]:
        return None
    end = int(np.argmin(still)) if not still.all() else len(still)
    if (t.f[end - 1] - t.f[0]) / fps < MOTION_WAIT_S:
        return None
    m = (end - 1) // 2
    c = lm.key(t.x[m], t.y[m])
    hit = [o for o in cands if _near(lm.queues.get(o, ()), c)]
    return hit[0] if len(hit) == 1 else None


def _occluder_leg(t: Track, tracks_all: dict[int, Track], counted: dict,
                  fps: float, frame_size, gates, cands) -> int | None:
    """A mid-box birth: the counted track whose box covered the birth point in
    the second before - the hidden car travelled with it."""
    from backend.services.entry_gates import _dist_to_segment
    bx, by, bw = t.cx[0], t.cy[0], float(t.w[0])
    if frame_size is not None:
        W, H = frame_size
        if min(bx, by, W - bx, H - by) < bw:
            return None                            # born at the frame edge
    if any(_dist_to_segment((t.x[0], t.y[0]), p1, p2)[0] < bw for p1, p2, _ in gates.values()):
        return None                                # born at a gate line
    f0 = t.f[0]
    best = None
    ids, starts, ends = counted["_index"]
    live = ids[(starts <= f0 - 1) & (ends >= f0 - fps)]
    for tid in live.tolist():
        u = tracks_all.get(tid)
        o = counted.get(tid)
        if u is None or tid == t.tid or o is None:
            continue
        sel = (u.f >= f0 - fps) & (u.f < f0)
        if not sel.any():
            continue
        i = np.nonzero(sel)[0][-1]
        if abs(bx - u.cx[i]) <= u.w[i] / 2 and abs(by - u.cy[i]) <= u.h[i] / 2:
            gap = f0 - u.f[i]
            if best is None or gap < best[0]:
                best = (gap, o)
    if best is not None and best[1] in cands:
        return best[1]
    return None


def decide(t: Track, side: str, known: int, lm: LaneMaps, gates: dict, fps: float,
           tracks_all: dict | None = None, counted_origin: dict | None = None,
           frame_size=None, graze: bool = False, whole: bool = False,
           mean_ray: bool = False, exclusive: bool = False,
           uturn_seen: bool = False) -> tuple[int | None, str, dict]:
    """side 'entry': known = the witnessed exit leg, returns the entry leg.
    side 'exit': known = the witnessed entry leg, returns the exit leg.
    Returns (leg or None, evidence, detail). None = a tie (no evidence decides).
    Variants (step 3b): graze = the ray skips a line it meets along (ray_leg);
    whole = lanes fitted over the whole visible moving track; mean_ray = the
    ray's direction is the mean motion over the first (last) MOTION_FIT_S s;
    exclusive = the lane tier counts votes from cells one candidate's lane
    alone runs, over the whole visible moving track (_lane_votes): the best
    needs >= 3 votes, a MOTION_MIN_FIT share and a MOTION_MARGIN lead;
    uturn_seen = the line the car is known to use is a candidate for the
    other end (a U-turn) only when its own visible track reverses (_reverses)."""
    from backend.config import MIN_CLEAN_TRACKS, MOTION_MARGIN, MOTION_MIN_FIT
    from backend.services.entry_gates import nearest_line_in_direction
    entry = side == "entry"
    ods = [od for od, n in lm.n_clean.items() if n >= MIN_CLEAN_TRACKS
           and (od[1] == known if entry else od[0] == known)]
    if uturn_seen and not _reverses(t, fps):
        ods = [od for od in ods if od[0] != od[1]]
    cands = [od[0] if entry else od[1] for od in ods]
    detail = {"cands": cands}
    if not cands:
        return None, "no_lanes", detail
    if entry:
        w = _waited_leg(t, fps, lm, cands)
        if w is not None:
            return w, "wait", detail
    idx = _moving_window(t, fps, at_start=entry)
    fit_idx = _moving_window(t, fps, at_start=entry, whole=True) if (whole or exclusive) else idx
    if exclusive:
        votes = _lane_votes(t, fit_idx, {(od[0] if entry else od[1]): lm.lanes.get(od, {})
                                         for od in ods}, lm)
        n = sum(votes.values())
        detail["votes"] = votes
        ranked = sorted(votes.items(), key=lambda kv: -kv[1])
        if n >= 3:
            best, second = ranked[0][1] / n, (ranked[1][1] / n if len(ranked) > 1 else 0.0)
            if best >= MOTION_MIN_FIT and best - second >= MOTION_MARGIN:
                return ranked[0][0], "lane", detail
    else:
        fits = {(od[0] if entry else od[1]): _lane_fit(t, fit_idx, lm.lanes.get(od, {}), lm)
                for od in ods}
        detail["fits"] = {k: round(v, 2) for k, v in fits.items()}
        ranked = sorted(fits.items(), key=lambda kv: -kv[1])
        best, second = ranked[0][1], (ranked[1][1] if len(ranked) > 1 else 0.0)
        if len(fit_idx) >= 3 and best >= MOTION_MIN_FIT and best - second >= MOTION_MARGIN:
            return ranked[0][0], "lane", detail
    if len(idx):
        i = idx[0] if entry else idx[-1]
        vel = ((float(np.mean(t.vx[idx])), float(np.mean(t.vy[idx]))) if mean_ray
               else (t.vx[i], t.vy[i]))
        if graze:
            leg, inc, grazed = ray_leg((t.x[i], t.y[i]), vel, gates, entering=entry)
            detail.update(ray_inc=None if inc is None else round(inc, 1), grazed=grazed)
        else:
            leg, _ = nearest_line_in_direction((t.x[i], t.y[i]), vel, gates, entering=entry)
        detail["ray"] = leg
        if leg in cands:
            return leg, "ray", detail
    if entry and tracks_all is not None and counted_origin:
        occ = _occluder_leg(t, tracks_all, counted_origin, fps, frame_size, gates, cands)
        if occ is not None:
            return occ, "occluder", detail
    return None, "tie", detail


# --- the passes -------------------------------------------------------------------

def _load(conn, camera_id):
    q = ("SELECT e.event_id, e.vehicle_track_id, e.origin_leg_id, e.destination_leg_id, "
         "e.movement, f.gate_tag FROM vehicle_events e LEFT JOIN track_fates f "
         "ON f.vehicle_track_id = e.vehicle_track_id AND f.camera_id = e.camera_id "
         "AND f.disposition = 'counted' WHERE e.camera_id = ? AND COALESCE(e.rejected, 0) = 0 "
         "AND e.vehicle_track_id IS NOT NULL AND e.vehicle_track_id >= 0")
    return [dict(zip(("eid", "tid", "o", "d", "mv", "tag"), r))
            for r in conn.execute(q, (camera_id,))]


def _movement(o, d, lm: LaneMaps, legs: list[dict] | None):
    if (o, d) in lm.labels:
        return lm.labels[(o, d)]
    if legs:
        from backend.services.trajectory_classifier import derive_movement
        lo = next((lg for lg in legs if lg["leg_id"] == o), None)
        ld = next((lg for lg in legs if lg["leg_id"] == d), None)
        if lo is not None:
            return derive_movement(lo, ld, all_legs=legs)
    return None


def mouth_from_motion_pass(db, camera_id: int, rows, fps: float, gates: dict,
                           legs: list[dict] | None = None, frame_size=None,
                           apply: bool = True, **variant) -> dict:
    """Re-decide the unseen entry line of exit_only counts (and the unseen exit
    line of entry_only counts). Returns stats + the per-event decisions.
    variant: decide()'s graze / whole / mean_ray switches."""
    conn = sqlite3.connect(str(db))
    try:
        evs = _load(conn, camera_id)
        tracks = tracks_from_rows(rows, fps, tids={e["tid"] for e in evs})
        clean = {e["tid"]: (e["o"], e["d"], e["mv"]) for e in evs
                 if e["tag"] == "full" and e["o"] is not None and e["d"] is not None}
        lm = build_lane_maps(tracks, clean, gates)
        counted_origin = {e["tid"]: e["o"] for e in evs if e["o"] is not None}
        _ids = np.array(sorted(t for t in counted_origin if t in tracks), dtype=int)
        counted_origin["_index"] = (_ids, np.array([tracks[t].f[0] for t in _ids]),
                                    np.array([tracks[t].f[-1] for t in _ids]))
        decisions, stats = [], defaultdict(int)
        for e in evs:
            if e["tag"] not in ("exit_only", "entry_only"):
                continue
            t = tracks.get(e["tid"])
            if t is None or len(t.f) < 2:
                continue
            if e["tag"] == "exit_only" and e["d"] is not None:
                leg, ev, det = decide(t, "entry", e["d"], lm, gates, fps, tracks,
                                      counted_origin, frame_size, **variant)
                new_o, new_d = (leg, e["d"]) if leg is not None else (e["o"], e["d"])
            elif e["tag"] == "entry_only" and e["o"] is not None:
                leg, ev, det = decide(t, "exit", e["o"], lm, gates, fps, **variant)
                new_o, new_d = (e["o"], leg) if leg is not None else (e["o"], e["d"])
            else:
                continue
            changed = (new_o, new_d) != (e["o"], e["d"])
            stats[f"{e['tag']}:{ev}"] += 1
            stats[f"{e['tag']}:{'changed' if changed else 'kept'}"] += 1
            mv = _movement(new_o, new_d, lm, legs) if changed else e["mv"]
            if changed and not mv:
                changed = False
                stats[f"{e['tag']}:no_movement_label"] += 1
            decisions.append({**e, "new_o": new_o, "new_d": new_d, "new_mv": mv,
                              "evidence": ev, "changed": changed, **det})
        if apply:
            with conn:
                for dcs in decisions:
                    if not dcs["changed"]:
                        continue
                    src = f"motion_{dcs['evidence']}"
                    conn.execute("UPDATE vehicle_events SET origin_leg_id=?, destination_leg_id=?, "
                                 "movement=?, posterior_source=? WHERE event_id=?",
                                 (dcs["new_o"], dcs["new_d"], dcs["new_mv"], src, dcs["eid"]))
                    conn.execute("UPDATE track_fates SET origin_leg_id=?, destination_leg_id=?, "
                                 "movement=?, posterior_source=? WHERE vehicle_track_id=? AND "
                                 "camera_id=? AND disposition='counted'",
                                 (dcs["new_o"], dcs["new_d"], dcs["new_mv"], src, dcs["tid"],
                                  camera_id))
    finally:
        conn.close()
    return {"camera_id": camera_id, **dict(stats), "decisions": decisions}


def path_lag(a: Track, b: Track, fps: float) -> tuple[float, float, int] | None:
    """Along the shared path, how much later b reaches each spot a passes while
    moving: (median |lag| s, median distance in box widths, points matched)."""
    from backend.services.track_chains import STITCH_STAT_SPEED_PXS
    ia = np.nonzero(a.speed >= STITCH_STAT_SPEED_PXS)[0]
    if len(ia) < 5 or len(b.f) < 2:
        return None
    lags, dists = [], []
    for i in ia[:: max(len(ia) // 40, 1)]:
        dd = np.hypot(b.x - a.x[i], b.y - a.y[i])
        j = int(np.argmin(dd))
        wbox = max(float(a.w[i]), 1.0)
        if dd[j] / wbox > 1.5 or j in (0, len(b.f) - 1):
            continue                     # b never passed this spot (or only at its ends)
        lags.append((b.f[j] - a.f[i]) / fps)
        dists.append(dd[j] / wbox)
    if len(lags) < 5:
        return None
    return float(np.median(np.abs(lags))), float(np.median(dists)), len(lags)


def lane_headways(tracks: dict[int, Track], clean: dict, fps: float) -> dict:
    """Per movement, the lags between consecutive clean tracks along their path:
    how soon after one car the next car of the same movement reaches a spot."""
    by = defaultdict(list)
    for tid, (o, d, _mv) in clean.items():
        if tid in tracks:
            by[(o, d)].append(tracks[tid])
    out = {}
    for od, ts in by.items():
        ts.sort(key=lambda t: t.f[0])
        lags = []
        for a, b in zip(ts, ts[1:]):
            if b.f[0] - a.f[-1] > 10 * fps:
                continue
            r = path_lag(a, b, fps)
            if r is not None:
                lags.append(r[0])
        out[od] = lags
    return out


def count_once_pass(db, camera_id: int, rows, fps: float, apply: bool = True) -> dict:
    """Two counted tracks of one movement that reach every spot of their path
    at the same moment are one car: reject the less-witnessed event."""
    from backend.config import (COUNT_ONCE_HEADWAY_FRAC, COUNT_ONCE_HEADWAY_PCT,
                                LINKER_STOP_DIST_BOXES)
    conn = sqlite3.connect(str(db))
    try:
        evs = [e for e in _load(conn, camera_id) if e["o"] is not None and e["d"] is not None]
        tracks = tracks_from_rows(rows, fps, tids={e["tid"] for e in evs})
        clean = {e["tid"]: (e["o"], e["d"], e["mv"]) for e in evs if e["tag"] == "full"}
        hw = {od: COUNT_ONCE_HEADWAY_FRAC * float(np.percentile(v, COUNT_ONCE_HEADWAY_PCT))
              for od, v in lane_headways(tracks, clean, fps).items() if len(v) >= 10}
        by = defaultdict(list)
        for e in evs:
            if e["tid"] in tracks:
                by[(e["o"], e["d"])].append(e)
        drop, pairs = set(), []
        for od, es in by.items():
            if od not in hw:
                continue
            es.sort(key=lambda e: tracks[e["tid"]].f[0])
            for i, ea in enumerate(es):
                if ea["eid"] in drop:
                    continue
                a = tracks[ea["tid"]]
                for eb in es[i + 1:]:
                    b = tracks[eb["tid"]]
                    if b.f[0] > a.f[-1]:
                        break
                    if eb["eid"] in drop:
                        continue
                    r = path_lag(a, b, fps) or path_lag(b, a, fps)
                    if r is None or r[0] > hw[od] or r[1] > LINKER_STOP_DIST_BOXES:
                        continue
                    ka = (_TAG_RANK.get(ea["tag"], 2), -(a.f[-1] - a.f[0]))
                    kb = (_TAG_RANK.get(eb["tag"], 2), -(b.f[-1] - b.f[0]))
                    victim = eb if kb >= ka else ea
                    drop.add(victim["eid"])
                    pairs.append({"keep": (ea if victim is eb else eb)["tid"], "drop": victim["tid"],
                                  "od": od, "lag_s": round(r[0], 2), "dist_w": round(r[1], 2),
                                  "headway_s": round(hw[od], 2)})
                    if victim is ea:
                        break
        if apply and drop:
            with conn:
                conn.executemany("UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?",
                                 [(int(e),) for e in drop])
    finally:
        conn.close()
    return {"camera_id": camera_id, "count_once_rejected": len(drop),
            "headway_s": {f"{o}->{d}": round(v, 2) for (o, d), v in hw.items()}, "pairs": pairs}
