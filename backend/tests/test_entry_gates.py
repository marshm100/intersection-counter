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
