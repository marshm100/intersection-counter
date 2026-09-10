"""THE LINES ARE THE MOUTHS (operator ruling 2026-09-10): a leg with a
drawn gate takes its mouth point and entry heading from the line."""
import json
import math

import backend.config as cfg

from backend.services.entry_gates import build_gates, mouth_from_gate


def _legs():
    # a box: N gate on the left (x=200), S on the right (x=800); the
    # stored dots are deliberately WRONG (off by hundreds of px)
    return [
        {"leg_id": 1, "origin_zone": json.dumps([[50.0, 50.0]]),
         "reference_heading": 123.0,
         "gate_segment": json.dumps([[200.0, 100.0], [200.0, 500.0]])},
        {"leg_id": 2, "origin_zone": [[950.0, 950.0]], "reference_heading": 7.0,
         "gate_segment": [[800.0, 100.0], [800.0, 500.0]]},
        {"leg_id": 3, "origin_zone": [[500.0, 900.0]], "reference_heading": 0.0,
         "gate_segment": None},                       # no line: untouched
    ]


class TestMouthFromGate:
    def test_midpoint_replaces_the_dot(self):
        out = {d["leg_id"]: d for d in mouth_from_gate(_legs())}
        assert out[1]["origin_zone"] == [[200.0, 300.0]]
        assert out[2]["origin_zone"] == [[800.0, 300.0]]

    def test_heading_is_the_entering_direction(self):
        # entering over the N gate (x=200) means travelling +x (screen
        # right) = heading 90; over the S gate, -x = 270
        out = {d["leg_id"]: d for d in mouth_from_gate(_legs())}
        assert math.isclose(out[1]["reference_heading"], 90.0, abs_tol=1e-6)
        assert math.isclose(out[2]["reference_heading"], 270.0, abs_tol=1e-6)

    def test_leg_without_a_line_is_untouched(self):
        out = {d["leg_id"]: d for d in mouth_from_gate(_legs())}
        assert out[3]["origin_zone"] == [[500.0, 900.0]]
        assert out[3]["reference_heading"] == 0.0

    def test_consistent_with_build_gates_inward(self):
        # build_gates' inward normal from the derived mouths agrees with
        # the derived heading: (sin h, -cos h) == inward
        out = mouth_from_gate(_legs())
        mouths = {d["leg_id"]: tuple(d["origin_zone"][0]) for d in out}
        drawn = {1: ((200.0, 100.0), (200.0, 500.0)),
                 2: ((800.0, 100.0), (800.0, 500.0))}
        gates = build_gates(mouths, [], {d["leg_id"]: d["reference_heading"]
                                         for d in out}, leg_gates=drawn)
        for d in out:
            if d["leg_id"] in drawn:
                h = math.radians(d["reference_heading"])
                ix, iy = gates[d["leg_id"]][2]
                assert math.isclose(ix, math.sin(h), abs_tol=1e-6)
                assert math.isclose(iy, -math.cos(h), abs_tol=1e-6)

    def test_pure_and_does_not_mutate_input(self):
        legs = _legs()
        before = json.dumps(legs, sort_keys=True, default=str)
        mouth_from_gate(legs)
        assert json.dumps(legs, sort_keys=True, default=str) == before

    def test_flag_default_off(self):
        assert cfg.MOUTH_FROM_GATE is False
