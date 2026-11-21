"""Track Repair Stage 0/1 — the service port + the dump-level transform.

cut_track/pinch_cuts behavior is pinned by test_a3_split.py (unchanged).
Here: cut_dump_rows — determinism, tid renumbering, uncut passthrough,
float32 exactness, and the no-wrong-units-fallback policy.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.services.track_cut import (
    FALLBACK_KIN, MIN_SEG_PTS, cut_dump_rows, cut_track,
)

# One horizontal gate the track crosses outward, then (spliced) re-approaches.
# gates: {leg: (p1, p2, inward_normal)} — inward normal points +y (down).
GATES = {29: ((0.0, 100.0), (200.0, 100.0), (0.0, 1.0))}
FPS = 25.0


def _rows(tracks):
    """{tid: [(frame, x, y), ...]} -> dump rows [N,8] float32."""
    out = []
    for tid, pts in tracks.items():
        for f, x, y in pts:
            out.append([tid, f, x, y, 20.0, 12.0, 0.9, 2.0])
    return np.array(out, dtype=np.float32)


def _spliced_track():
    """Crosses the gate outbound at ~frame 50, then a latch teleport back
    inside and a long second life — the Type-1 geometry-cut shape."""
    a = [(float(f), 100.0, 150.0 - 2.0 * f) for f in range(0, 51)]      # exits y<100 ~f25
    b = [(float(f), 100.0 + (f - 90) * 1.5, 140.0) for f in range(90, 140)]
    return a + b


def _clean_track():
    """Never crosses the gate; smooth; nothing to cut."""
    return [(float(f), 50.0 + f, 200.0) for f in range(0, 40)]


class TestCutDumpRows:
    def test_uncut_tracks_pass_through_verbatim(self):
        rows = _rows({7: _clean_track()})
        out, stats = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        assert stats["cut_tracks"] == 0
        assert np.array_equal(np.sort(out, axis=0), np.sort(rows, axis=0))
        assert out.dtype == np.float32

    def test_spliced_track_cut_and_thief_debris_dropped(self):
        # rev 6: segment 1 (the real journey, gate-crossing) survives under
        # its new tid; the thief ride never crosses a gate -> debris, gone.
        rows = _rows({7: _spliced_track()})
        out, stats = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        assert stats["cut_tracks"] == 1
        assert stats["debris_segments"] == 1
        assert stats["debris_rows"] > 0
        tids = sorted(set(out[:, 0].tolist()))
        assert tids == [1000070.0]              # CUT_SEG_BASE + tid*10 + k
        assert (out[:, 0] == 1000070.0).sum() >= MIN_SEG_PTS

    def test_deterministic(self):
        rows = _rows({7: _spliced_track(), 9: _clean_track()})
        a, _ = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        b, _ = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        assert np.array_equal(a, b)

    def test_mixed_dump_keeps_clean_tids(self):
        rows = _rows({7: _spliced_track(), 9: _clean_track()})
        out, stats = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        tids = set(out[:, 0].tolist())
        assert 9.0 in tids                    # clean tid untouched
        assert 7.0 not in tids                # spliced tid replaced by segments
        assert 1000070.0 in tids              # thief debris dropped (rev 6)
        assert 1000071.0 not in tids

    def test_float32_tid_exactness(self):
        big = 200000                          # realistic upper tid range
        pts = _spliced_track()
        rows = _rows({big: pts})
        out, _ = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        tids = sorted(set(out[:, 0].tolist()))
        assert tids == [1_000_000.0 + big * 10]  # exact in float32


class TestKinPolicy:
    def test_fallback_kin_units_are_px_per_second(self):
        # the wrong-units fallback (0.8/0.5) must not exist anywhere reachable
        assert FALLBACK_KIN["v_stop"] == 8.0
        assert FALLBACK_KIN["a_allow"] == 12.0

    def test_cut_track_smooth_turner_uncut_under_fallback(self):
        """A smooth 90-degree turner (the false-cut class the pinch gate must
        not fire on) stays whole under the correct-units fallback."""
        pts = []
        for f in range(0, 30):                # southbound approach
            pts.append((float(f), 100.0, 300.0 - 4.0 * f))
        for k in range(1, 31):                # gentle arc to eastbound
            ang = (k / 30.0) * (np.pi / 2)
            pts.append((float(30 + k), 100.0 + 60.0 * np.sin(ang),
                        180.0 - 60.0 * (1 - np.cos(ang))))
        segments, records = cut_track(pts, {}, FPS, dict(FALLBACK_KIN))
        assert records == []
        assert len(segments) == 1 and len(segments[0]) == len(pts)


# ---------------------------------------------------------------------------
# Stage 1a — the graze amendment (operator identity law, 2026-08-24)
# ---------------------------------------------------------------------------

# Two horizontal gates: 28 at y=100 (the grazed line), 29 at y=300 (real
# exit for a southbound through). Inward normals point at the box interior
# between them (28's +y, 29's -y). Entry gate 27 at y=20 (+y inward).
GATES3 = {
    27: ((0.0, 20.0), (200.0, 20.0), (0.0, 1.0)),
    28: ((0.0, 100.0), (200.0, 100.0), (0.0, -1.0)),
    29: ((0.0, 300.0), (200.0, 300.0), (0.0, -1.0)),
}


def _sb_through_graze():
    """IN:27 -> graze OUT:28 -> real OUT:29, smooth throughout."""
    return [(float(f), 100.0, 4.0 * f) for f in range(0, 90)]  # y 0..356


def _real_exit_then_thief():
    """IN:27 -> OUT:29 (real, smooth) then a teleport latch and a long
    opposite ride — the 14859 class."""
    a = [(float(f), 100.0, 4.0 * f) for f in range(0, 80)]      # exits y=300 ~f75
    b = [(float(f), 140.0, 320.0 - 3.0 * (f - 120)) for f in range(120, 180)]
    return a + b


class TestGrazeAmendment:
    def test_smooth_graze_is_skipped_cut_at_real_exit(self):
        segments, records = cut_track(_sb_through_graze(), GATES3, FPS,
                                      dict(FALLBACK_KIN))
        geo = [r for r in records if r[1].get("rule") == "geometry"]
        assert len(geo) == 1
        # cut at the FINAL crossing (29 at y=300 ~ frame 75), not the graze (28 ~ f25)
        assert geo[0][0] > 60 * 1.0
        # segment 1 retains the full journey: crosses 27 in, 28 graze, 29 out
        from backend.services.entry_gates import classify
        o, d, *_r, tag = classify(segments[0], GATES3, FPS)
        assert (o, d, tag) == (27, 29, "full")

    def test_thief_after_real_exit_cut_at_the_theft(self):
        pts = _real_exit_then_thief()
        segments, records = cut_track(pts, GATES3, FPS, dict(FALLBACK_KIN))
        geo = [r for r in records if r[1].get("rule") == "geometry"]
        assert len(geo) == 1
        # the discontinuity follows the ~f75 exit -> cut there (+1s margin)
        assert 70 <= geo[0][0] <= 110
        from backend.services.entry_gates import classify
        o, d, *_r, tag = classify(segments[0], GATES3, FPS)
        assert (o, d) == (27, 29) and tag == "full"
        assert len(segments) >= 2          # the thief survives as its own track

    def test_tail_discontinuity_does_not_cut_at_graze(self):
        """A teleport AFTER the final crossing must not implicate the graze
        (span bounding): the geometry cut stays at the final crossing."""
        pts = _sb_through_graze()
        # teleport tail beyond the final crossing
        pts += [(float(f), 400.0, 380.0) for f in range(150, 160)]
        segments, records = cut_track(pts, GATES3, FPS, dict(FALLBACK_KIN))
        geo = [r for r in records if r[1].get("rule") == "geometry"]
        assert len(geo) == 1
        assert geo[0][0] > 60          # at the y=300 crossing, not the graze
        from backend.services.entry_gates import classify
        o, d, *_r, tag = classify(segments[0], GATES3, FPS)
        assert (o, d, tag) == (27, 29, "full")

    def test_single_exit_tail_trim_unchanged(self):
        """Simple track with one exit and a short smooth tail: cut at the
        exit + margin — identical to pre-amendment behavior."""
        pts = [(float(f), 100.0, 4.0 * f) for f in range(0, 100)]  # one entry 27? crosses 27,28,29
        # use a single-gate world to isolate: entry-free single outbound
        one = {29: ((0.0, 300.0), (200.0, 300.0), (0.0, -1.0))}
        segments, records = cut_track(pts, one, FPS, dict(FALLBACK_KIN))
        geo = [r for r in records if r[1].get("rule") == "geometry"]
        assert len(geo) == 1
        assert abs(geo[0][0] - (75 + 25)) <= 3     # crossing ~f75 + 1s margin


# ---------------------------------------------------------------------------
# Stage 2 — direction gate + chain glue (operator identity law, 2026-08-24)
# ---------------------------------------------------------------------------

from backend.config import TRACK_FINALIZE_GAP_FRAMES
from backend.services.track_cut import CUT_SEG_BASE
from backend.services.track_chains import (
    STITCH_STAT_DIST, _end_speed, chain_tracks, endpoint_bearings,
)


def _rec(tid, pts, tag):
    """A chain_tracks rec built exactly the way glue builds them."""
    bs, be = endpoint_bearings(pts, FPS)
    return {"tid": tid, "birth": (pts[0][0], pts[0][1], pts[0][2]),
            "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
            "tag": tag, "v_end": _end_speed(pts),
            "b_start": bs, "b_end": be}


def _east(tid_f0, n, x0, y=300.0, v=4.0):
    f0 = float(tid_f0)
    return [(f0 + i, x0 + v * i, y) for i in range(n)]


class TestDirectionGate:
    def test_opposite_direction_moving_pair_vetoed(self):
        a = _east(0, 51, 10.0)                       # dies (210,300) moving E
        b = [(52.0 + i, 215.0 - 4.0 * i, 300.0) for i in range(50)]  # moving W
        stats = {}
        chains = chain_tracks([_rec(1, a, "entry_only"),
                               _rec(2, b, "exit_only")], FPS, stats=stats)
        assert all(len(c) == 1 for c in chains)
        assert stats["direction_rejections"] >= 1

    def test_same_direction_chains(self):
        a = _east(0, 51, 10.0)
        b = _east(52, 50, 215.0)
        chains = chain_tracks([_rec(1, a, "entry_only"),
                               _rec(2, b, "exit_only")], FPS)
        assert any(len(c) == 2 for c in chains)

    def test_stop_side_waiver(self):
        """A ends stationary (queue dwell has no direction) — even a 90°
        discharge (a turner) chains under the frozen stationary rule."""
        a = ([(float(f), 100.0, 100.0 + 2.0 * f) for f in range(0, 50)]
             + [(float(f), 100.0, 198.0) for f in range(50, 120)])  # SB, stops
        b = [(500.0 + i, 105.0 + 4.0 * i, 200.0) for i in range(50)]  # E out
        ra, rb = _rec(1, a, "entry_only"), _rec(2, b, "exit_only")
        assert ra["b_end"] is None            # dwelling endpoint: no bearing
        chains = chain_tracks([ra, rb], FPS)
        assert any(len(c) == 2 for c in chains)

    def test_recs_without_bearing_keys_waived(self):
        """Older callers build recs without bearing keys — untouched."""
        a = _east(0, 51, 10.0)
        b = [(52.0 + i, 215.0 - 4.0 * i, 300.0) for i in range(50)]
        recs = []
        for tid, pts, tag in ((1, a, "entry_only"), (2, b, "exit_only")):
            recs.append({"tid": tid,
                         "birth": (pts[0][0], pts[0][1], pts[0][2]),
                         "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
                         "tag": tag, "v_end": _end_speed(pts)})
        chains = chain_tracks(recs, FPS)
        assert any(len(c) == 2 for c in chains)   # veto waived, rule holds

    def test_endpoint_bearings_shapes(self):
        moving = _east(0, 50, 10.0)
        bs, be = endpoint_bearings(moving, FPS)
        assert bs is not None and be is not None
        stopped_end = ([(float(f), 100.0, 100.0 + 2.0 * f) for f in range(50)]
                       + [(float(f), 100.0, 198.0) for f in range(50, 120)])
        bs2, be2 = endpoint_bearings(stopped_end, FPS)
        assert bs2 is not None and be2 is None
        jitter = [(float(f), 100.0 + (f % 2), 200.0) for f in range(40)]
        assert endpoint_bearings(jitter, FPS) == (None, None)


class TestCollisionFix:
    def test_cut_segments_disjoint_from_uncut_tids(self):
        """Pre-fix, track 1's segments became tids 10 and 11 — colliding
        with the real uncut track 10 and silently merging two vehicles."""
        rows = _rows({1: _spliced_track(), 10: _clean_track()})
        out, stats = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        assert stats["cut_tracks"] == 1
        tids = set(out[:, 0].tolist())
        assert tids == {10.0, CUT_SEG_BASE + 10.0}   # thief debris dropped
        # the clean vehicle's rows are exactly its own
        assert (out[:, 0] == 10.0).sum() == len(_clean_track())


class TestDebrisEligibility:
    """Rev 6 (operator ruling after the G-TR-1 MISS): a cut piece with no
    gate crossings can neither be counted nor vote on gate activation."""

    def test_gate_blind_cut_track_falls_back_uncut(self):
        # A pinch-cuttable out-and-back far from any gate: every segment
        # would be debris, so the repair stands down and the ORIGINAL rows
        # pass through — production behavior for gate-blind tracks.
        pts = [(float(f), 10.0 + 4.0 * f, 300.0) for f in range(0, 30)]
        pts += [(30.0 + i, 126.0 - 4.0 * i, 300.0) for i in range(1, 30)]
        segments, records = cut_track(pts, {}, FPS, dict(FALLBACK_KIN))
        assert records, "fixture must actually pinch-cut"
        rows = _rows({7: pts})
        out, stats = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        assert stats["debris_fallback_tracks"] == 1
        assert stats["cut_tracks"] == 0
        assert set(out[:, 0].tolist()) == {7.0}
        assert len(out) == len(rows)

    def test_partial_evidence_segments_survive(self):
        # exit_only / entry_only segments carry gate evidence and stay
        # countable (the window-clipped-journey class must not vanish).
        pts = _spliced_track()
        rows = _rows({7: pts})
        out, _ = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        from backend.services.entry_gates import classify
        seg1 = sorted((float(r[1]), float(r[2]), float(r[3]))
                      for r in out[out[:, 0] == 1000070.0])
        *_r, tag = classify(seg1, GATES, FPS)
        assert tag != "no_crossing"
