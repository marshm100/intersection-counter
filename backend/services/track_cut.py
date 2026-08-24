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
            sub[:, 0] = tid * 10.0 + k
            out_chunks.append(sub)
            stats["segments"] += 1
            used += len(idxs)
        stats["dropped_points"] += len(pts) - used
    out = np.concatenate(out_chunks, axis=0) if out_chunks else rows_sorted[:0]
    return np.ascontiguousarray(out, dtype=np.float32), stats
