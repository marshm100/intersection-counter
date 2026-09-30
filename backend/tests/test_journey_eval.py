"""Journey-label scoring (backend/services/journey_eval.py): every labelled
vehicle gets one outcome from what the arm counted for the tracks under the
operator's clicks."""
import numpy as np

from backend.services.journey_eval import mcnemar, score_clip, track_at, index_rows

CLIP = {"start_frame": 0, "end_frame": 100}


def _track(tid, f0, f1, x0, y0, dx=0.0, dy=5.0, w=20.0, h=14.0):
    return [(tid, f, x0 + dx * (f - f0), y0 + dy * (f - f0), w, h, 0.9, 2)
            for f in range(f0, f1 + 1)]


def _label(lid, fi, xi, yi, fo, xo, yo, o=1, d=3):
    return {"label_id": lid, "entry_frame": fi, "entry_x": xi, "entry_y": yi,
            "exit_frame": fo, "exit_x": xo, "exit_y": yo,
            "entry_leg_id": o, "exit_leg_id": d}


def _ev(tid, o=1, d=3, f=10):
    return {"vehicle_track_id": tid, "origin_leg_id": o, "destination_leg_id": d,
            "start_frame": f}


ROWS = np.array(
    _track(1, 0, 20, 100, 0)            # car A: one clean track, y 0..100
    + _track(2, 30, 40, 300, 0)         # car B: split into two pieces
    + _track(3, 42, 55, 300, 60)
    + _track(4, 60, 80, 500, 0)         # car C: tracked, never counted
    + _track(5, 60, 80, 700, 0)         # car D: counted with the wrong exit
    + _track(9, 85, 95, 900, 0),        # an unlabelled track with an event: phantom
    dtype=float)


def test_track_at_finds_the_box_under_the_click():
    byf = index_rows(ROWS, 0, 100)
    assert track_at(byf, 10, 100, 50) == 1
    assert track_at(byf, 10, 400, 400) is None


def test_each_vehicle_gets_one_outcome():
    labels = [_label(1, 0, 100, 0, 20, 100, 100),
              _label(2, 30, 300, 0, 55, 300, 125),
              _label(3, 60, 500, 0, 80, 500, 100),
              _label(4, 60, 700, 0, 80, 700, 100),
              _label(5, 90, 1500, 0, 95, 1500, 20)]           # no box under the click
    events = [_ev(1), _ev(2, f=30), _ev(3, f=42), _ev(5, d=2, f=60), _ev(9, f=85)]
    r = score_clip(labels, ROWS, events, CLIP)
    out = {v["label_id"]: v["outcome"] for v in r["per_vehicle"]}
    assert out == {1: "correct", 2: "double", 3: "missed", 4: "wrong", 5: "no_track"}
    assert [v["broken"] for v in r["per_vehicle"]] == [False, True, False, False, False]
    assert r["phantoms"] == 1 and r["broken"] == 1
    assert r["correct_rate"] == 0.2


def test_a_partial_label_claims_its_track_but_is_not_scored():
    labels = [dict(_label(1, 0, 100, 0, 20, 100, 100), exit_frame=None,
                   exit_x=None, exit_y=None)]
    r = score_clip(labels, ROWS, [_ev(1)], CLIP)
    assert r["n_full"] == 0 and r["phantoms"] == 0


def test_mcnemar_counts_discordant_vehicles():
    a = {"per_vehicle": [{"label_id": i, "outcome": "correct"} for i in range(6)]}
    b = {"per_vehicle": [{"label_id": i, "outcome": "correct" if i < 2 else "missed"}
                         for i in range(6)]}
    m = mcnemar(a, b)
    assert m["a_only_correct"] == 4 and m["b_only_correct"] == 0
    assert abs(m["p_value"] - 0.125) < 1e-9


def test_exit_click_just_after_the_track_ends_at_the_edge_is_the_same_car():
    # tracked to y 100 at frame 20; the operator clicks the exit 3 frames
    # later, 12 px further on (the car leaving the screen)
    labels = [_label(1, 0, 100, 0, 23, 100, 112)]
    r = score_clip(labels, ROWS, [_ev(1)], CLIP, fps=10.0)
    assert r["outcomes"] == {"correct": 1}


def test_a_track_that_died_well_before_the_exit_is_still_no_track():
    labels = [_label(1, 0, 100, 0, 35, 100, 300)]           # 1.5 s later, far on
    r = score_clip(labels, ROWS, [_ev(1)], CLIP, fps=10.0)
    assert r["outcomes"] == {"no_track": 1}


def test_a_neighbour_in_a_platoon_is_not_charged_to_this_car():
    # cars 1 and 2 leave side by side; car 1's exit click lands on car 2's box
    rows = np.array(_track(1, 0, 20, 100, 0) + _track(2, 0, 20, 118, 0), dtype=float)
    labels = [_label(1, 0, 100, 0, 20, 116, 100),
              _label(2, 0, 118, 0, 20, 118, 100)]
    r = score_clip(labels, rows, [_ev(1), _ev(2)], CLIP)
    assert r["outcomes"] == {"correct": 2}
