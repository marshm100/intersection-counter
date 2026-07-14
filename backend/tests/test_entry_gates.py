"""entry_gates service (item-8 mechanism 1, stage 1): crossing semantics on
synthetic geometry + a corridor regression pin (skipped where the corridor
project isn't present)."""
import json
import sqlite3
from pathlib import Path

import pytest

from backend.services.entry_gates import (
    JITTER_S, _seg_cross, build_gates, classify,
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


def test_pipeline_origin_evidence_extraction():
    """The pipeline's evidence hook (mechanism-1 filter half) reads an inward
    entry crossing off the vehicle trajectory — without a full pipeline."""
    from backend.services.pipeline import ProcessingPipeline

    class P:
        _ensure_entry_gates = ProcessingPipeline._ensure_entry_gates
        _origin_evidence = ProcessingPipeline._origin_evidence

    p = P()
    p._entry_gates = None
    p.fps = 10.0
    p.legs = [{"leg_id": lid, "origin_zone": [list(m)],
               "reference_heading": HEAD[lid]} for lid, m in LEGS.items()]
    p._paths = [dict(pp) for pp in PATHS]
    # entered from leg 1 heading south -> evidence = 1
    veh = {"start_frame": 100,
           "trajectory": [[50.0, -10.0 + 12.0 * i] for i in range(12)]}
    assert p._origin_evidence(veh) == 1
    # born mid-box -> no evidence
    veh2 = {"start_frame": 100,
            "trajectory": [[45.0 + i, 50.0] for i in range(5)]}
    assert p._origin_evidence(veh2) is None
