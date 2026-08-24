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

    def test_spliced_track_is_segmented_and_renumbered(self):
        rows = _rows({7: _spliced_track()})
        out, stats = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        assert stats["cut_tracks"] == 1
        tids = sorted(set(out[:, 0].tolist()))
        assert tids == [70.0, 71.0]           # tid*10+k
        # each segment respects MIN_SEG_PTS
        for t in tids:
            assert (out[:, 0] == t).sum() >= MIN_SEG_PTS
        # segment 0 ends before segment 1 begins (cut extends in time)
        f0 = out[out[:, 0] == 70.0][:, 1].max()
        f1 = out[out[:, 0] == 71.0][:, 1].min()
        assert f0 < f1

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
        assert {70.0, 71.0} <= tids

    def test_float32_tid_exactness(self):
        big = 200000                          # realistic upper tid range
        pts = _spliced_track()
        rows = _rows({big: pts})
        out, _ = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        tids = sorted(set(out[:, 0].tolist()))
        assert tids == [float(big * 10), float(big * 10 + 1)]  # exact in float32


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
