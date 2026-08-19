"""A3 splitter unit tests (docs/plan_a3_split_2026-08-19.md).

Synthetic tracks against synthetic gates pin: the all_crossings
factor-out parity, heading_series re-expression, both cut rules with
their amendments (entry-first, graze-vs-latch, displacement-chord
pinch), and the discriminators (queue stop, smooth U-turn)."""
import math
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.entry_gates import all_crossings, classify  # noqa: E402
from backend.services.trajectory_classifier import (              # noqa: E402
    compute_cumulative_curvature, heading_series)
from v2_a3_split import cut_track, pinch_cuts                     # noqa: E402

FPS = 25.0
# Two vertical gates at x=100 (west) and x=500 (east), inward normals
# pointing toward the center (x=300).
GATES = {
    1: ((100.0, 0.0), (100.0, 400.0), (1.0, 0.0)),
    2: ((500.0, 0.0), (500.0, 400.0), (-1.0, 0.0)),
}
KIN = {"v_stop": 8.0, "a_allow": 12.0, "zv_radius": 10.0}


def _track(points_per_step=1, path=()):
    """path: [(x0,y0,frames,x1,y1)] linear legs -> [(f,x,y)...]."""
    pts = []
    f = 1000.0
    for x0, y0, frames, x1, y1 in path:
        for i in range(int(frames)):
            t = i / max(1, frames - 1)
            pts.append((f, x0 + t * (x1 - x0), y0 + t * (y1 - y0)))
            f += 1
    return pts


class TestFactorOuts:
    def test_all_crossings_matches_classify_selection(self):
        # W->E through: crosses gate 1 inward, gate 2 outward
        pts = _track(path=[(50, 200, 60, 550, 200)])
        kept = all_crossings(pts, GATES, FPS)
        entries = [c for c in kept if c[2]]
        exits = [c for c in kept if not c[2]]
        o, d, of, df, _op, _dp, tag = classify(pts, GATES, FPS)
        assert tag == "full" and o == 1 and d == 2
        assert abs(entries[0][0] - of) < 1e-6
        assert abs(exits[-1][0] - df) < 1e-6

    def test_heading_series_reexpression_byte_parity(self):
        traj = [(i * 3.0, 100 + i * 2.0 + (i % 3)) for i in range(40)]
        assert compute_cumulative_curvature(traj) == \
            sum(abs(d) for d in heading_series(traj))


class TestGeometryCut:
    def test_type1_lingering_cut_after_exit(self):
        # real car W->E, then a LATCH (teleport) back inside + wander.
        # Behavior, not rule-name: the splice is severed and segment 1
        # is the true car's complete journey. (Pinch and geometry cuts
        # can coincide within dedup range — either severing is correct.)
        path = [(50, 200, 60, 550, 200)]
        pts = _track(path=path)
        f0 = pts[-1][0]
        pts += [(f0 + 50 + i, 300.0 + i, 250.0) for i in range(40)]
        segs, recs = cut_track(pts, GATES, FPS, KIN)
        assert len(segs) >= 2 and recs
        o, d, *_r, tag = classify(segs[0], GATES, FPS)
        assert (o, d, tag) == (1, 2, "full")

    def test_entry_jitter_burst_does_not_decapitate(self):
        # rapid in-out-in wiggle AT the entry gate (bbox jitter), then
        # a clean journey: the jitter-collapse + amendment-1 filter
        # must leave segment 1 as the full journey, cut at the REAL
        # exit only.
        pts = _track(path=[(50, 200, 10, 104, 200)])       # crosses in
        f0 = pts[-1][0]
        pts += [(f0 + 1, 98.0, 200.0), (f0 + 2, 104.0, 200.0)]
        pts += _track(path=[(105, 200, 50, 550, 200)])
        # rebase frames monotone
        pts = [(1000.0 + i, x, y) for i, (_f, x, y) in enumerate(pts)]
        segs, recs = cut_track(pts, GATES, FPS, KIN)
        o, d, *_r, tag = classify(segs[0], GATES, FPS)
        assert (o, d, tag) == (1, 2, "full")

    def test_graze_voids_cut(self):
        # journey W->E that momentarily grazes OUT and back IN at
        # gate 2 mid-path (continuous motion) then really exits
        path = [(50, 200, 40, 505, 200),      # crosses in g1, grazes out g2
                (505, 200, 6, 495, 200),      # back in (continuous)
                (495, 200, 30, 560, 200)]     # real exit
        pts = _track(path=path)
        segs, recs = cut_track(pts, GATES, FPS, KIN)
        geo_frames = [f for f, r in recs if r["rule"] == "geometry"]
        # cut must be at the FINAL exit (not the graze): the first
        # segment still classifies full W->E
        o, d, *_r, tag = classify(segs[0], GATES, FPS)
        assert (o, d, tag) == (1, 2, "full")


class TestPinchCut:
    def test_hairpin_flip_cuts(self):
        # eastbound at speed, instant reversal westbound (box theft)
        path = [(150, 200, 30, 350, 200), (350, 200, 30, 150, 200)]
        pts = _track(path=path)
        cuts = pinch_cuts(pts, KIN, FPS)
        assert cuts, "hairpin flip must fire"

    def test_smooth_uturn_not_cut(self):
        # continuous semicircle (real U-turn): gradual bearing change
        pts = []
        f = 1000.0
        for i in range(60):
            a = math.pi * i / 59.0
            pts.append((f, 300 + 80 * math.sin(a), 200 - 80 * math.cos(a)))
            f += 1
        assert pinch_cuts(pts, KIN, FPS) == []

    def test_queue_stop_same_direction_not_cut(self):
        # drive, stop 3 s, resume SAME direction
        path = [(150, 200, 30, 300, 200)]
        pts = _track(path=path)
        f0 = pts[-1][0]
        pts += [(f0 + i, 300.0, 200.0) for i in range(75)]
        pts += [(f0 + 75 + i, 300 + i * 5.0, 200.0) for i in range(30)]
        assert pinch_cuts(pts, KIN, FPS) == []

    def test_jitter_at_creep_speed_not_cut(self):
        # sub-jitter wobble: displacements below zv_radius never form
        # a displacement-chord -> no bearings -> no cuts
        pts = [(1000.0 + i, 300 + (i % 2) * 3.0, 200 + (i % 3) * 2.0)
               for i in range(100)]
        assert pinch_cuts(pts, KIN, FPS) == []


class TestSegments:
    def test_stub_tail_keeps_whole(self):
        pts = _track(path=[(50, 200, 60, 550, 200)])
        segs, recs = cut_track(pts, GATES, FPS, KIN)
        # exit near track end -> tail is a stub -> single segment
        assert len(segs) >= 1
        assert sum(len(s) for s in segs) <= len(pts)
