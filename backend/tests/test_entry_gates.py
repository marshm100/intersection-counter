"""entry_gates service (item-8 mechanism 1, stage 1): crossing semantics on
synthetic geometry + a corridor regression pin (skipped where the corridor
project isn't present)."""
import json
import sqlite3
from pathlib import Path

import pytest

from backend.services.entry_gates import (
    JITTER_S, _seg_cross, build_gates, cell_census, classify,
)

# A square box: 4 legs at the side midpoints, one straight N-S channel.
LEGS = {1: (50.0, 0.0), 2: (100.0, 50.0), 3: (50.0, 100.0), 4: (0.0, 50.0)}
PATHS = [{"origin_leg_id": 1, "destination_leg_id": 3,
          "polyline": [[50, -20], [50, 120]]},
         {"origin_leg_id": 4, "destination_leg_id": 2,
          "polyline": [[-20, 50], [120, 50]]}]
HEAD = {1: 180.0, 2: 270.0, 3: 0.0, 4: 90.0}


@pytest.fixture(scope="module")
def gates():
    return build_gates(LEGS, PATHS, HEAD)


def test_seg_cross_basic():
    assert _seg_cross((0, 0), (10, 0), (5, -5), (5, 5)) == pytest.approx(0.5)
    assert _seg_cross((0, 0), (10, 0), (20, -5), (20, 5)) is None


def test_full_journey_through(gates):
    # N -> S straight through: origin leg 1, dest leg 3
    track = [(f, 50.0, -10.0 + 12.0 * f) for f in range(12)]
    o, d, fo, fd, *_ , tag = classify(track, gates, fps=10.0)
    assert (o, d, tag) == (1, 3, "full")
    assert fo < fd


def test_entry_only_truncated(gates):
    # enters from N, dies mid-box — the Wall-B class
    track = [(f, 50.0, -10.0 + 12.0 * f) for f in range(6)]
    o, d, *_rest, tag = classify(track, gates, fps=10.0)
    assert (o, d, tag) == (1, None, "entry_only")


def test_no_crossing_midbox_birth(gates):
    # born and dies inside the box — the Wall-C class: NO origin evidence
    track = [(f, 45.0 + f, 50.0) for f in range(5)]
    o, d, *_rest, tag = classify(track, gates, fps=10.0)
    assert tag == "no_crossing" and o is None


def test_jitter_burst_collapses(gates):
    # bbox wobble across gate 1 within JITTER_S keeps only the first crossing
    pts, f = [], 0.0
    for y in (-5, 3, -3, 4, -4, 5):        # wobble, 0.1 s apart (fps 10)
        pts.append((f, 50.0, float(y))); f += 1
    pts += [(f + i, 50.0, 20.0 + 90.0 * i) for i in range(2)]
    o, d, *_rest, tag = classify(pts, gates, fps=10.0)
    assert o == 1     # one entry, not an in/out/in burst


def test_queue_creep_not_uturn(gates):
    # enters gate 1, dwells 2.5 s just inside (below UTURN_MIN_S=5 s), then
    # re-crosses outward at the SAME lane spot — queue creep, not a u-turn
    track = ([(0.0, 50.0, -5.0), (1.0, 50.0, 10.0)]
             + [(1.0 + i, 50.0, 10.0) for i in range(1, 26)]
             + [(27.0, 50.0, -5.0)])
    o, d, *_rest, tag = classify(track, gates, fps=10.0)
    assert tag == "entry_only" and o == 1


class TestCellCensus:
    """Gate-evidence merge expecteds (posterior half stage 3): full journeys
    count 1.0 at their cell; entry-/exit-only evidence distributes over the
    full census's OWN proportions; no-crossing carries nothing."""

    FULL_13 = [(float(f), 50.0, -10.0 + 12.0 * f) for f in range(12)]
    ENTRY_1 = [(float(f), 50.0, -10.0 + 12.0 * f) for f in range(6)]
    # born mid-box, exits S gate outward
    EXIT_3 = [(float(f), 50.0, 60.0 + 12.0 * f) for f in range(6)]
    NO_X = [(float(f), 45.0 + f, 50.0) for f in range(5)]
    # enters N gate, turns, exits E gate
    FULL_12 = [(0.0, 50.0, -5.0), (1.0, 50.0, 30.0), (2.0, 50.0, 50.0),
               (3.0, 70.0, 50.0), (4.0, 105.0, 50.0)]

    def test_full_journeys_count_at_cell(self, gates):
        census = cell_census([self.FULL_13, self.FULL_13], gates, fps=10.0)
        assert census == {(1, 3): pytest.approx(2.0)}

    def test_truncated_evidence_allocated_by_own_mix(self, gates):
        census = cell_census(
            [self.FULL_13, self.FULL_13, self.FULL_12,
             self.ENTRY_1, self.ENTRY_1, self.EXIT_3, self.NO_X],
            gates, fps=10.0)
        # origin-1 mix is 2:1 -> each entry-only splits 2/3 vs 1/3;
        # the exit-only lands wholly on (1,3), the only *->3 cell.
        assert census[(1, 3)] == pytest.approx(2.0 + 2 * (2.0 / 3.0) + 1.0)
        assert census[(1, 2)] == pytest.approx(1.0 + 2 * (1.0 / 3.0))

    def test_no_evidence_contributes_nothing(self, gates):
        assert cell_census([self.NO_X], gates, fps=10.0) == {}

    def test_short_tracks_skipped(self, gates):
        assert cell_census([self.FULL_13[:3]], gates, fps=10.0) == {}


CORRIDOR = Path("data/projects/97a7849a/project.db")


@pytest.mark.skipif(not CORRIDOR.exists(), reason="corridor project not present")
def test_corridor_cam2_gate_pin():
    """Regression pin: cam2 gates from live operator geometry + applied bank.
    Values pinned at the stage-1 port (phase-0 validated this geometry by
    reproducing the published cell signatures)."""
    conn = sqlite3.connect(CORRIDOR)
    legs, head = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id=2"):
        legs[lid] = tuple(json.loads(oz)[0]); head[lid] = rh
    paths = [{"origin_leg_id": o, "destination_leg_id": d,
              "polyline": json.loads(pl)} for o, d, pl in conn.execute(
        "SELECT origin_leg_id, destination_leg_id, polyline "
        "FROM intersection_paths WHERE camera_id=2")]
    conn.close()
    gates = build_gates(legs, paths, head)
    assert set(gates) == {26, 27, 28, 29}
    for leg, (p1, p2, inw) in gates.items():
        assert abs(inw[0] ** 2 + inw[1] ** 2 - 1.0) < 1e-6   # unit normals
        # every gate segment is sane: finite, non-degenerate
        assert 20.0 < ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5 < 2000.0


def _pipeline_shim():
    from backend.services.pipeline import ProcessingPipeline

    class P:
        _ensure_entry_gates = ProcessingPipeline._ensure_entry_gates
        _gate_evidence = ProcessingPipeline._gate_evidence

    p = P()
    p._entry_gates = None
    return p


def test_pipeline_gate_evidence_extraction():
    """The pipeline's evidence hook (mechanism 1) returns the FULL evidence
    tuple (origin, dest, tag) off the vehicle trajectory — without a full
    pipeline. The filter half consumes origin; the posterior half dest/tag."""
    p = _pipeline_shim()
    p.fps = 10.0
    p.legs = [{"leg_id": lid, "origin_zone": [list(m)],
               "reference_heading": HEAD[lid]} for lid, m in LEGS.items()]
    p._paths = [dict(pp) for pp in PATHS]
    # full N->S journey: origin 1, dest 3
    veh = {"start_frame": 100,
           "trajectory": [[50.0, -10.0 + 12.0 * i] for i in range(12)]}
    assert p._gate_evidence(veh) == (1, 3, "full")
    # born mid-box, dies mid-box -> no evidence at all
    veh2 = {"start_frame": 100,
            "trajectory": [[45.0 + i, 50.0] for i in range(5)]}
    assert p._gate_evidence(veh2) == (None, None, "no_crossing")
    # enters from N, dies mid-box -> entry evidence only
    veh3 = {"start_frame": 100,
            "trajectory": [[50.0, -10.0 + 12.0 * i] for i in range(6)]}
    assert p._gate_evidence(veh3) == (1, None, "entry_only")


_CAM2_DUMPS = sorted(Path("data/projects/97a7849a/detections/2").glob(
    "*/study_0700.tracks")) if Path("data/projects/97a7849a/detections/2").exists() else []


@pytest.mark.skipif(not (CORRIDOR.exists() and _CAM2_DUMPS),
                    reason="corridor project / cam2 study_0700 dump not present")
def test_gate_evidence_dump_fidelity_n500():
    """Tuple fidelity on real data: _gate_evidence must agree with a direct
    entry_gates.classify call on the same points for 500 cam2 dump tracks —
    the pipeline hook may never drift from the service (one source of truth)."""
    import numpy as np

    conn = sqlite3.connect(CORRIDOR)
    legs, head = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id=2"):
        legs[lid] = tuple(json.loads(oz)[0]); head[lid] = rh
    paths = [{"origin_leg_id": o, "destination_leg_id": d,
              "polyline": json.loads(pl)} for o, d, pl in conn.execute(
        "SELECT origin_leg_id, destination_leg_id, polyline "
        "FROM intersection_paths WHERE camera_id=2")]
    fps = float(conn.execute(
        "SELECT fps FROM videos WHERE camera_id=2 ORDER BY sort_order LIMIT 1"
    ).fetchone()[0])
    conn.close()

    p = _pipeline_shim()
    p.fps = fps
    p.legs = [{"leg_id": lid, "origin_zone": [list(m)],
               "reference_heading": head[lid]} for lid, m in legs.items()]
    p._paths = paths
    gates = p._ensure_entry_gates()

    tdir = _CAM2_DUMPS[0]
    n = int((tdir / "count.txt").read_text())
    rows = np.load(tdir / "rows.npy", mmap_mode="r")[:min(n, 200_000), :4]
    tracks = {}
    for tid, fr, x, y in np.asarray(rows):
        tracks.setdefault(int(tid), []).append((float(fr), float(x), float(y)))
        if len(tracks) > 520:
            break
    checked = 0
    for tid, pts in tracks.items():
        pts = sorted(pts)
        if len(pts) < 2:
            continue
        veh = {"start_frame": int(pts[0][0]),
               "trajectory": [[x, y] for _f, x, y in pts]}
        f0 = float(int(pts[0][0]))
        direct = classify([(f0 + i, x, y) for i, (_f, x, y) in enumerate(pts)],
                          gates, fps)
        assert p._gate_evidence(veh) == (direct[0], direct[1], direct[6]), tid
        checked += 1
        if checked >= 500:
            break
    assert checked >= 500


class TestDeriveGateAxes:
    """Track-derived gate orientation (plan_v2_gate_axis_2026-08-10)."""

    def _traffic(self, n, x0, y0, dx, dy, sign=1):
        """n straight tracks through (x0,y0) along (dx,dy)."""
        out = []
        for i in range(n):
            off = (i % 5) - 2                      # a little lane spread
            pts = [(float(k), x0 + off + sign*dx*k/4.0,
                    y0 + off + sign*dy*k/4.0) for k in range(5)]
            out.append(pts)
        return out

    def test_axis_recovered_from_straight_traffic(self):
        from backend.services.entry_gates import derive_gate_axes
        # leg 1's mouth at (50,0); road runs N-S (0,1) in screen coords
        tracks = self._traffic(40, 50.0, 0.0, 0.0, 20.0)
        axes = derive_gate_axes({1: (50.0, 0.0)}, tracks)
        ax, ay = axes[1]
        assert abs(abs(ay) - 1.0) < 0.05 and abs(ax) < 0.05

    def test_bidirectional_traffic_does_not_cancel(self):
        """The reason for axial (doubled-angle) averaging: inbound and
        outbound vectors are antiparallel, so a naive vector mean would
        cancel to noise and hand the gate a meaningless direction."""
        from backend.services.entry_gates import derive_gate_axes
        tracks = (self._traffic(30, 50.0, 0.0, 0.0, 20.0, sign=1)
                  + self._traffic(30, 50.0, 0.0, 0.0, 20.0, sign=-1))
        # the naive estimator these tracks defeat
        import math
        vx = vy = 0.0
        for t in tracks:
            dx, dy = t[-1][1]-t[0][1], t[-1][2]-t[0][2]
            L = math.hypot(dx, dy)
            vx += dx/L
            vy += dy/L
        assert math.hypot(vx/len(tracks), vy/len(tracks)) < 0.1   # cancelled
        # the axial estimator still recovers the road axis
        ax, ay = derive_gate_axes({1: (50.0, 0.0)}, tracks)[1]
        assert abs(abs(ay) - 1.0) < 0.05 and abs(ax) < 0.05

    def test_support_floor_omits_thin_and_incoherent_mouths(self):
        from backend.services.entry_gates import derive_gate_axes
        # too few tracks -> omitted (caller keeps channel tangents)
        assert derive_gate_axes({1: (50.0, 0.0)},
                                self._traffic(5, 50.0, 0.0, 0.0, 20.0)) == {}
        # plenty of tracks but no dominant axis -> omitted
        import math
        spun = []
        for i in range(60):
            a = 2*math.pi*i/60.0
            spun.append([(float(k), 50.0 + 20*k*math.cos(a)/4.0,
                          0.0 + 20*k*math.sin(a)/4.0) for k in range(5)])
        assert derive_gate_axes({1: (50.0, 0.0)}, spun) == {}

    def test_axes_are_deterministic(self):
        from backend.services.entry_gates import derive_gate_axes
        tracks = self._traffic(40, 50.0, 0.0, 3.0, 20.0)
        a = derive_gate_axes({1: (50.0, 0.0)}, tracks)
        b = derive_gate_axes({1: (50.0, 0.0)}, list(reversed(tracks)))
        assert a[1] == pytest.approx(b[1], abs=1e-12)

    def test_build_gates_uses_axis_and_leaves_other_legs_alone(self):
        from backend.services.entry_gates import build_gates
        base = build_gates(LEGS, PATHS, HEAD)
        # rotate leg 1's road axis 90 degrees vs its channel (which is N-S)
        rotated = build_gates(LEGS, PATHS, HEAD, leg_axes={1: (1.0, 0.0)})
        assert rotated[1] != base[1]
        for leg in (2, 3, 4):
            assert rotated[leg] == base[leg]

    def test_candidate_paths_cannot_rotate_a_derived_axis(self):
        """G-OR4(b): the axis is a pure function of mouths+tracks, so
        injecting an extra candidate path leaves it untouched (the
        fill-arm confound rule that pipeline._gate_paths protects)."""
        from backend.services.entry_gates import derive_gate_axes
        tracks = self._traffic(40, 50.0, 0.0, 0.0, 20.0)
        before = derive_gate_axes({1: (50.0, 0.0)}, tracks)
        # derive_gate_axes takes no paths at all — the property is structural
        import inspect
        assert "path" not in inspect.signature(derive_gate_axes).parameters
        assert before == derive_gate_axes({1: (50.0, 0.0)}, tracks)
