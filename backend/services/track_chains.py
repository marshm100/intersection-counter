"""Fragment chains on raw dump tracks (mechanism ① iteration 3 — the
conservation pass, docs/plan_conservation_pass_2026-07-15.md).

Verbatim port of the B3 chaining machinery from scripts/boxclip_pass2.py
(docs/plan_boxclip_b3_chaining_2026-07-08.md), proven at Gate B — the script
re-imports from here (the entry_gates port pattern; one source of truth).
The dedup-ceiling lesson is structural: only journey-INCOMPLETE tracks may
chain (A still lacks its exit, B still lacks its entry) — a box-full journey
never chains, so a 1–2 s-headway FOLLOWER on a dense arterial cannot be
merged into its leader. Constants frozen 2026-07-08; this module adds none.
"""
from __future__ import annotations

import bisect
import math

from backend.services.entry_gates import classify

STITCH_MOVE_GAP_S = (-0.48, 3.0)  # seconds: occlusion break mid-box
STITCH_MOVE_DIST = 70.0           # px
STITCH_STAT_SPEED_PXS = 10.0      # px/SECOND: "ended stationary" (stop bar)
STITCH_STAT_GAP_S = 50.0          # seconds (~a red): resumes where it stopped
STITCH_STAT_DIST = 35.0           # px


def _end_speed(pts, tail=6):
    seg = pts[-tail:] if len(pts) > tail else pts
    df = seg[-1][0] - seg[0][0]
    return (math.hypot(seg[-1][1] - seg[0][1], seg[-1][2] - seg[0][2]) / df
            if df > 0 else 0.0)


def chain_tracks(recs, fps):
    """B3 (docs/plan_boxclip_b3_chaining_2026-07-08.md): global fragment
    chaining. Edge A->B iff B plausibly continues A (the proven break rules,
    applied to EVERY pair, not just entry x exit). Greedy on (dist + 0.5*gap),
    each rec <=1 predecessor and <=1 successor; chains strictly extend in time
    (no cycles). Returns a list of chains (time-ordered lists of recs)."""
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
        lo = bisect.bisect_left(births, fa + STITCH_MOVE_GAP_S[0] * fps)
        hi = bisect.bisect_right(births, fa + STITCH_STAT_GAP_S * fps)
        a_slow = a["v_end"] * fps < STITCH_STAT_SPEED_PXS
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
            moving = (STITCH_MOVE_GAP_S[0] * fps <= gap <= STITCH_MOVE_GAP_S[1] * fps
                      and dist <= STITCH_MOVE_DIST)
            stat = a_slow and 0 < gap <= STITCH_STAT_GAP_S * fps and dist <= STITCH_STAT_DIST
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


def build_chain_map_ev(tracks, gates, fps, min_points: int = 5):
    """(chain_map, evidence) over a dump's tracks. chain_map exactly as
    build_chain_map. evidence: {tid: (origin_leg, dest_leg, tag)} for every
    >= min_points track — the classify() output this builder always computed
    and previously DISCARDED (C-1, docs/plan_v2_c1_arbitration_2026-08-12.md).
    The evidence-ranked arbitration joins it to events by vehicle_track_id;
    legs are the same leg_id space as vehicle_events.origin/destination_leg_id
    (the merge-rescue comparison precedent, two_pass.py)."""
    recs = []
    evidence = {}
    for tid, pts in tracks.items():
        pts = sorted(pts)
        if len(pts) < min_points:
            continue
        o, d, *_rest, tag = classify(pts, gates, fps)
        evidence[tid] = (o, d, tag)
        recs.append({"tid": tid,
                     "birth": (pts[0][0], pts[0][1], pts[0][2]),
                     "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
                     "tag": tag, "v_end": _end_speed(pts)})
    chains = chain_tracks(recs, fps)
    return ({r["tid"]: ci for ci, ch in enumerate(chains) for r in ch}, evidence)


def build_chain_map(tracks, gates, fps, min_points: int = 5):
    """{track_id: chain_id} over a dump's tracks. tracks: {tid: [(f,x,y),...]}.
    Tags come from the PINNED entry gates (same geometry the pipeline's
    evidence gate uses). Tracks below min_points are left unmapped (they
    cannot chain and cannot carry events that matter)."""
    return build_chain_map_ev(tracks, gates, fps, min_points)[0]
