"""A3 splice cutter — service port (Track Repair Stage 0, 2026-08-24).

Verbatim promotion of the validated cutter from scripts/v2_a3_split.py
(G-A3-1 55/56 on operator-labeled splices; false-cut 0.39% <= 1% bar;
docs/plan_a3_split_2026-08-19.md) into backend/services, following the
entry_gates / track_chains one-source-of-truth port pattern. The script
re-imports from here; backend/tests/test_a3_split.py remains the behavior pin.

The two operator-observed splice mechanisms it cuts:
  Type 1 (post-exit lingering)  — geometry cut at the FIRST outbound
      exit-gate crossing + margin. This is also the operator's "cut the
      moment it touches that gate" rule: segment 1 then contains exactly one
      outbound crossing, so entry_gates.classify's dest (= exits[-1]) IS the
      real vehicle's exit and gate supremacy inherits no thief taint.
  Type 2 (mid-intersection box theft, "pinched trajectory") — cut at the
      impossible-deceleration cusp / bearing flip, jitter-immune via
      displacement chords.

kin POLICY (ported behavior CHANGE, deliberate): the old script fell back to
{v_stop:0.8, a_allow:0.5} — px/frame-looking values that pinch_cuts divides
by fps AGAIN, making the pinch detector over-fire by roughly fps x. That
fallback does not exist here. Callers pass a kin dict fitted from the
window's tracklets (scripts/v2_common.fit_motion_residual) or the
correct-units FALLBACK_KIN below (run_pathfit_cli's, px/SECOND).
"""
from __future__ import annotations

import math

import numpy as np

from backend.services.entry_gates import all_crossings

# ---- declared constants (gate doc; frozen before validation) --------------
MARGIN_S = 1.0            # geometry cut margin past the exit crossing
PINCH_ANGLE = 120.0       # arrival->departure bearing change (deg)
PINCH_SPREAD = 6          # >this many turning chords = smooth turn, no cut
DECEL_K = 3.0             # impossible decel = K x fitted a_allow
CHORD_K = 3               # chord span (points) for bearing/speed series
RE_ENTRY_S = 2.0          # inbound within this after an exit = graze
MIN_SEG_PTS = 5
# Cut-rule revision. Bumped by the GRAZE AMENDMENT (rev 4, 2026-08-24,
# operator identity law) and by Stage 2 (rev 5: chain glue + the segment
# renumber collision fix): derived a3_ dumps record it, so amended rules
# never reuse a dump built under an earlier rule.
RULE_REV = 5

# Cut segments renumber into a namespace DISJOINT from original tids:
# plain tid*10+k collided with real uncut tids (track 1's segments became
# 10 and 11 -- legitimate vehicle ids in every window) and the two were
# silently merged by every by-tid consumer. 1e6 + tid*10 + k stays exact
# in float32 (2**24) for tids into the hundreds of thousands.
CUT_SEG_BASE = 1_000_000.0

# Correct-units fallback (px/SECOND), from run_pathfit_cli.py — the only
# fallback permitted when no fitted kinematics exist for the window.
FALLBACK_KIN = {"v_stop": 8.0, "a_allow": 12.0, "zv_radius": 12.0}


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


LATCH_JUMP_PX = 25.0     # a latch hands the box to ANOTHER vehicle — at
                         # least a car-width away. Position-continuous stops
                         # and resumes are the SAME vehicle (operator law).


def _moving_median_step(pts, v_stop_pf):
    """Median per-frame speed over the track's MOVING samples (steps above
    the stop speed). The overall median collapses when the vehicle dwells at
    a red, making its own resume look like a teleport — the moving median is
    the honest driving-speed scale."""
    speeds = []
    for i in range(len(pts) - 1):
        dfr = pts[i + 1][0] - pts[i][0]
        if dfr > 0:
            v = math.hypot(pts[i + 1][1] - pts[i][1],
                           pts[i + 1][2] - pts[i][2]) / dfr
            if v > v_stop_pf:
                speeds.append(v)
    if not speeds:
        return v_stop_pf
    speeds.sort()
    return speeds[len(speeds) // 2]


def _pre_velocity(pts, i, lookback=5):
    """Mean velocity (vx, vy) px/frame over up to `lookback` steps ending at
    index i — the extrapolation basis for the continuity test."""
    j = max(0, i - lookback)
    dfr = pts[i][0] - pts[j][0]
    if dfr <= 0:
        return 0.0, 0.0
    return ((pts[i][1] - pts[j][1]) / dfr, (pts[i][2] - pts[j][2]) / dfr)


def _latch_in_span(pts, f_lo, f_hi, fps, v_stop_pf, med_step):
    """Identity-theft detector, span-scoped, per the operator's law
    (2026-08-24, the bus refinement): occlusion does not end identity —
    INCOMPATIBLE MOTION does. Across any discontinuity, extrapolate the
    prior motion through the gap; reappearing where physics says the SAME
    vehicle would be is continuity (a stopped car resuming in place, a
    mover re-emerging on its trajectory after an occluder). A latch is a
    reappearance that DEVIATES from the extrapolation by a real jump —
    the box was handed to a different vehicle."""
    bar = max(4.0 * v_stop_pf, 5.0 * med_step)
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        if b[0] <= f_lo or a[0] > f_hi:
            continue
        dfr = b[0] - a[0]
        step = math.hypot(b[1] - a[1], b[2] - a[2])
        if dfr > 0.5 * fps:
            vx, vy = _pre_velocity(pts, i)
            ex_x, ex_y = a[1] + vx * dfr, a[2] + vy * dfr
            deviation = math.hypot(b[1] - ex_x, b[2] - ex_y)
            # tolerance grows with the gap's expected travel (extrapolation
            # is imperfect over long occlusions) but never below a car-jump
            tol = max(LATCH_JUMP_PX, 0.6 * math.hypot(vx, vy) * dfr)
            if deviation > tol:
                return True
        elif dfr > 0 and step / dfr > bar and step >= LATCH_JUMP_PX:
            return True
    return False


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
    # GRAZE AMENDMENT (2026-08-24, operator identity law — supersedes and
    # SUBSUMES Amendment 2): full-span drawn gates cross each other's travel
    # paths, so a through vehicle GRAZES another leg's line mid-box before
    # its real exit (measured: every SB through reads IN:27 -> OUT:28 ->
    # OUT:29; blanket first-exit cutting projected SB_thru -479 -> -1126).
    # The discriminator between "graze then real exit" and "real exit then
    # thief" is what happens BETWEEN crossings: smooth continuation = same
    # vehicle (graze — skip); latch discontinuity = identity theft (cut at
    # the exit the theft followed). The final crossing is always a real
    # exit (harmless tail trim). Amendment 2's inbound-graze case falls out:
    # a smooth inbound follow-up is smooth continuation with further
    # crossings ahead; a latch-inbound is a discontinuity.
    v_stop_pf = max(float(kin.get("v_stop", 8.0)), 1e-3) / fps
    med_step = _moving_median_step(pts, v_stop_pf)
    chosen = None
    if exits:
        cross_frames = sorted(c[0] for c in kept)
        last_cross = cross_frames[-1]
        for ex in exits:
            nxt = next((f for f in cross_frames if f > ex[0]), None)
            span_hi = nxt if nxt is not None else pts[-1][0]
            if _latch_in_span(pts, ex[0], span_hi, fps, v_stop_pf, med_step):
                chosen = ex             # identity broke after this exit
                break
            if ex[0] >= last_cross:
                chosen = ex             # final crossing = the real exit
                break
            # else: graze — smooth continuation, further crossings ahead
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
# Dump-level transform (Track Repair Stage 1)
# ---------------------------------------------------------------------------

def cut_dump_rows(rows: np.ndarray, gates: dict, fps: float,
                  kin: dict) -> tuple[np.ndarray, dict]:
    """Apply cut_track to every track of a pass-1 dump, renumbering segments
    tid*10+k (float32-exact for realistic tid ranges — rows are float32).

    rows: dump format v2 [N,8] cols [track_id, frame, cx, cy, bw, bh, conf,
    class_id]. Returns (rows', stats). Uncut tracks keep their original tid
    verbatim (byte-identical rows); segments beyond the first 10 per track
    are dropped with a counter (never observed in validation: max cuts/track
    was far below 9).

    Deterministic: same rows + gates + kin -> identical output (no RNG)."""
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows_sorted = rows[order]
    out_chunks = []
    stats = {"tracks": 0, "cut_tracks": 0, "segments": 0,
             "dropped_points": 0, "overflow_segments": 0}
    tids = rows_sorted[:, 0]
    boundaries = np.flatnonzero(np.diff(tids)) + 1
    for chunk in np.split(rows_sorted, boundaries):
        stats["tracks"] += 1
        tid = float(chunk[0, 0])
        pts = [(float(r[1]), float(r[2]), float(r[3])) for r in chunk]
        segments, records = cut_track(pts, gates, fps, kin)
        if not records or len(segments) == 1 and len(segments[0]) == len(pts):
            out_chunks.append(chunk)      # uncut: rows pass through verbatim
            stats["segments"] += 1
            continue
        stats["cut_tracks"] += 1
        # frame -> row index within the chunk for slicing by membership
        frame_to_idx = {float(r[1]): i for i, r in enumerate(chunk)}
        used = 0
        for k, seg in enumerate(segments):
            if k >= 10:
                stats["overflow_segments"] += 1
                break
            idxs = [frame_to_idx[p[0]] for p in seg if p[0] in frame_to_idx]
            sub = chunk[idxs].copy()
            sub[:, 0] = CUT_SEG_BASE + tid * 10.0 + k
            out_chunks.append(sub)
            stats["segments"] += 1
            used += len(idxs)
        stats["dropped_points"] += len(pts) - used
    out = np.concatenate(out_chunks, axis=0) if out_chunks else rows_sorted[:0]
    return np.ascontiguousarray(out, dtype=np.float32), stats


def glue_chained_fragments(rows: np.ndarray, gates: dict, fps: float,
                           min_points: int = 5) -> tuple[np.ndarray, dict]:
    """Track Repair Stage 2 (operator identity law, 2026-08-24): re-join the
    fragments of ONE vehicle inside the (already cut) dump, so the replay
    counts each family exactly once — the one-vehicle-one-track guard the
    Stage-1 census demanded (a counted fragment and its recovered
    continuation were the same vehicle counted twice).

    Chains: the frozen track_chains rules + tag gating (A lacks exit, B
    lacks entry) + the Stage-2a direction veto. Members renumber to
    min(member tids); inter-member gaps are BRIDGED one row per frame —
    the replay finalizes any tid silent > TRACK_FINALIZE_GAP_FRAMES and
    re-splits reused tids, and the pipeline timestamps gate crossings by
    trajectory INDEX, so an unbridged or sparse glue is undone or
    time-distorted. Bridge rows are inert by construction: linear cx/cy
    (~= a hold within STITCH_STAT_DIST for stop gaps — the vehicle IS
    parked there), bw/bh = min of the bracketing real rows (bbox length is
    a running max), conf linearly interpolated (a low marker would
    un-protect track_quality and dilute detection_confidence), class_id 2
    (adds no articulated/single-unit votes; birth class comes from the
    first REAL row). Overlapping member rows (STITCH_MOVE allows B born up
    to 0.48 s before A dies) dedupe to one row per (tid, frame): the
    earlier member wins through its death.

    Deterministic. Returns (rows' frame-major, stats);
    stats["families"] maps composite tid -> ordered member tids."""
    from backend.services.entry_gates import classify
    from backend.services.track_chains import (
        _end_speed, chain_tracks, endpoint_bearings)

    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows_sorted = np.asarray(rows)[order]
    stats = {"chains_glued": 0, "glued_members": 0, "bridged_rows": 0,
             "overlap_dropped_rows": 0, "direction_rejections": 0,
             "families": {}}
    if not len(rows_sorted):
        return np.ascontiguousarray(rows_sorted, dtype=np.float32), stats
    ncol = rows_sorted.shape[1]
    boundaries = np.flatnonzero(np.diff(rows_sorted[:, 0])) + 1
    chunks, recs = {}, []
    for chunk in np.split(rows_sorted, boundaries):
        tid = float(chunk[0, 0])
        chunks[tid] = chunk
        if len(chunk) < min_points:
            continue
        pts = [(float(r[1]), float(r[2]), float(r[3])) for r in chunk]
        o, d, *_rest, tag = classify(pts, gates, fps)
        bs, be = endpoint_bearings(pts, fps)
        recs.append({"tid": tid,
                     "birth": (pts[0][0], pts[0][1], pts[0][2]),
                     "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
                     "tag": tag, "v_end": _end_speed(pts),
                     "b_start": bs, "b_end": be})
    glued: set = set()
    out_chunks = []
    for ch in chain_tracks(recs, fps, stats=stats):
        if len(ch) < 2:
            continue
        members = [r["tid"] for r in ch]
        comp = min(members)
        last = None                       # last emitted real row
        parts = []
        for tid in members:
            chunk = chunks[tid]
            if last is not None:
                keep = chunk[:, 1] > last[1]
                stats["overlap_dropped_rows"] += int((~keep).sum())
                chunk = chunk[keep]
                if not len(chunk):
                    continue
                gap = int(chunk[0, 1] - last[1])
                if gap > 1:
                    nb = gap - 1
                    br = np.zeros((nb, ncol), dtype=np.float64)
                    br[:, 0] = comp
                    br[:, 1] = last[1] + 1 + np.arange(nb)
                    t = (br[:, 1] - last[1]) / gap
                    br[:, 2] = last[2] + t * (chunk[0, 2] - last[2])
                    br[:, 3] = last[3] + t * (chunk[0, 3] - last[3])
                    if ncol >= 8:
                        br[:, 4] = min(last[4], chunk[0, 4])
                        br[:, 5] = min(last[5], chunk[0, 5])
                        br[:, 6] = last[6] + t * (chunk[0, 6] - last[6])
                        br[:, 7] = 2.0
                    parts.append(br.astype(np.float32))
                    stats["bridged_rows"] += nb
            sub = chunk.copy()
            sub[:, 0] = comp
            parts.append(sub)
            last = sub[-1]
        glued.update(members)
        stats["chains_glued"] += 1
        stats["glued_members"] += len(members)
        stats["families"][str(int(comp))] = [int(m) for m in members]
        out_chunks.append(np.concatenate(parts, axis=0))
    for tid, chunk in chunks.items():
        if tid not in glued:
            out_chunks.append(chunk)
    out = (np.concatenate(out_chunks, axis=0) if out_chunks
           else rows_sorted[:0])
    out = out[np.lexsort((out[:, 0], out[:, 1]))]      # frame-major
    return np.ascontiguousarray(out, dtype=np.float32), stats


# ---------------------------------------------------------------------------
# Derived-dump resolution (Track Repair Stage 1)
# ---------------------------------------------------------------------------

def _geom_hash(project_id: str, camera_id: int) -> str:
    """Gate-relevant geometry fingerprint (legs + paths + channels), the
    v2_a3_split geom_hash recipe — pins a cut dump to the geometry it was
    cut under so a gate redraw forces a rebuild."""
    import hashlib
    import sqlite3
    from backend.config import PROJECTS_DIR
    db = PROJECTS_DIR / project_id / "project.db"
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    h = hashlib.sha256()
    try:
        for table in ("legs", "intersection_paths", "channels"):
            for row in conn.execute(
                    f"SELECT * FROM {table} WHERE camera_id=? ORDER BY 1",
                    (camera_id,)):
                h.update(repr(row).encode())
    finally:
        conn.close()
    return h.hexdigest()[:16]


def ensure_cut_dump(project_id: str, camera_id: int, variant: str,
                    chash: str, fps: float, base_tdir, base_rows,
                    base_meta: dict):
    """Materialize (or reuse) the a3_-cut derived dump for a base window.

    Returns (variant', tdir', meta', rows'). Reuse when the derived dir
    exists AND its recorded geom_hash matches current geometry AND it was cut
    from the same base row count. kin: fitted from the window's tracklets npz
    when present, else FALLBACK_KIN (px/s) — never the old wrong-units values.

    Deterministic, side-effect-safe: the base dump is never touched.
    """
    import json as _json
    from pathlib import Path
    import numpy as _np
    from backend.database import leg_geometry_for_camera, list_paths_for_camera
    from backend.services.entry_gates import build_gates

    new_variant = f"a3_{variant}"
    dst = Path(str(base_tdir).replace(f"{variant}.tracks",
                                      f"{new_variant}.tracks"))
    ghash = _geom_hash(project_id, camera_id)
    meta_p = dst / "meta.json"
    if meta_p.exists():
        m = _json.loads(meta_p.read_text())
        from backend.config import CHAIN_GLUE as _glue_on
        cut_info = m.get("a3_cut") or {}
        if (cut_info.get("geom_hash") == ghash
                and cut_info.get("rule_rev") == RULE_REV
                and cut_info.get("base_rows") == int(len(base_rows))
                and (cut_info.get("glue") or {}).get("enabled") == _glue_on):
            # plain load (no mmap): a lingering mmap handle blocks the
            # rebuild's overwrite on Windows (EINVAL on open-for-write)
            rows = _np.load(dst / "rows.npy")
            return new_variant, dst, m, rows

    # build gates exactly the way the replay does (drawn gates verbatim;
    # axes derived from the base tracks)
    from backend.services.two_pass import _tracks_from_rows, gate_axes_for
    geom = leg_geometry_for_camera(project_id, camera_id)
    mouths = {lid: g["mouth"] for lid, g in geom.items()}
    heads = {lid: g["heading"] for lid, g in geom.items()}
    drawn = {lid: g["gate"] for lid, g in geom.items() if g["gate"]}
    tracks = _tracks_from_rows(base_rows)
    gates = build_gates(mouths, list_paths_for_camera(project_id, camera_id),
                        heads, leg_axes=gate_axes_for(mouths, tracks.values()),
                        leg_gates=drawn or None)
    if not gates:
        raise RuntimeError(f"cam{camera_id}: no gates — cannot cut")

    kin, kin_src = dict(FALLBACK_KIN), "fallback"
    npz = Path("runs/v2_week1") / f"tracklets_cam{camera_id}_{variant}.npz"
    if npz.exists():
        try:
            import sys as _sys
            if "scripts" not in _sys.path:
                _sys.path.insert(0, "scripts")
            from v2_common import fit_motion_residual, load_table
            kin = fit_motion_residual(load_table(npz))
            kin_src = "fitted"
        except Exception:
            pass  # fallback kin stands

    out_rows, stats = cut_dump_rows(_np.asarray(base_rows), gates, fps, kin)
    from backend.config import CHAIN_GLUE
    glue_info = {"enabled": False}
    if CHAIN_GLUE:
        out_rows, gstats = glue_chained_fragments(out_rows, gates, fps)
        glue_info = {"enabled": True, "families": gstats.pop("families"),
                     **{k: int(v) for k, v in gstats.items()}}
    out_rows = out_rows[_np.lexsort((out_rows[:, 0], out_rows[:, 1]))]
    dst.mkdir(parents=True, exist_ok=True)
    meta2 = dict(base_meta)
    meta2["variant"] = new_variant
    meta2["complete"] = True
    meta2["a3_cut"] = {
        "geom_hash": ghash, "rule_rev": RULE_REV, "base_variant": variant,
        "base_rows": int(len(base_rows)), "kin_src": kin_src,
        "kin": {k: round(float(v), 3) for k, v in kin.items()
                if k != "table" and isinstance(v, (int, float))},
        "glue": glue_info,
        **{k: int(v) for k, v in stats.items()},
    }
    _np.save(dst / "rows.npy", _np.ascontiguousarray(out_rows,
                                                     dtype=_np.float32))
    (dst / "count.txt").write_text(str(len(out_rows)))
    meta_p.write_text(_json.dumps(meta2))
    return new_variant, dst, meta2, out_rows
