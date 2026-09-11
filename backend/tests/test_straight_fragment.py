"""THE STRAIGHT-FRAGMENT RULE (operator ruling 2026-09-07): a vehicle
that never curved cannot be booked as a turn on a guess."""
import pytest

import backend.config as cfg
from backend.services.pipeline import ProcessingPipeline

LEGS = [
    {"leg_id": 22, "cardinal_direction": "S", "reference_heading": 262.5},
    {"leg_id": 23, "cardinal_direction": "N", "reference_heading": 82.7},
    {"leg_id": 24, "cardinal_direction": "W", "reference_heading": 312.9},
    {"leg_id": 25, "cardinal_direction": "E", "reference_heading": 172.8},
]
THROUGH_PATH = {"origin_leg_id": 22, "destination_leg_id": 23,
                "movement_label": "through",
                "polyline": [[0, 0], [1, 1]], "supporting_count": 100}


def _pipe(paths=None):
    p = ProcessingPipeline.__new__(ProcessingPipeline)
    p.legs = LEGS
    p._paths = paths if paths is not None else [THROUGH_PATH]
    return p


def _call(p, **kw):
    args = dict(vehicle={"reference_heading": 262.5},
                trajectory=[(0.0, 0.0), (10.0, 10.0)],
                classification={"num_points": 30,
                                "path_straightness": 0.98,
                                "net_heading_change": 1.5},
                origin_leg_id=22, origin_leg=LEGS[0],
                destination_leg_id=25, movement="right",
                polyline_dest=None, posterior_source=None,
                gate_dest=None, dest_result={"confidence": 0.58})
    args.update(kw)
    return p._straight_fragment_reroute(**args)


@pytest.fixture
def rule_on(monkeypatch):
    monkeypatch.setattr(cfg, "STRAIGHT_FRAGMENT_RULE", True)


class TestStraightFragment:
    def test_guessed_straight_right_rerouted(self, rule_on):
        p = _pipe()
        out = _call(p)
        assert out is not None and out != "drop"
        dest, leg, mv, dres, src = out
        assert dest == 23 and mv == "through"
        assert src == "straight_reroute"
        assert p.n_straight_rerouted == 1

    def test_no_through_path_uses_opposite_cardinal(self, rule_on):
        p = _pipe(paths=[])
        out = _call(p)
        assert out is not None and out != "drop"
        assert out[0] == 23          # N is opposite S

    def test_no_target_drops(self, rule_on):
        p = _pipe(paths=[])
        p.legs = [LEGS[0], LEGS[3]]   # no N leg at all
        out = _call(p)
        assert out == "drop"
        assert p.n_straight_dropped == 1

    def test_curved_right_untouched(self, rule_on):
        out = _call(_pipe(), classification={"num_points": 30,
                                             "path_straightness": 0.98,
                                             "net_heading_change": 40.0})
        assert out is None

    def test_gate_evidenced_dest_untouched(self, rule_on):
        assert _call(_pipe(), gate_dest=25) is None

    def test_bank_path_dest_untouched(self, rule_on, monkeypatch):
        # the narrow rule leaves bank-path destinations alone; the path-fit
        # extension is default ON since 2026-09-11 (G-DEF-4), so pin it off here
        monkeypatch.setattr(cfg, "STRAIGHT_FRAGMENT_INCLUDE_PATH_FITS", False)
        assert _call(_pipe(), polyline_dest={"destination_leg_id": 25}) is None

    def test_posterior_sourced_untouched(self, rule_on):
        assert _call(_pipe(), posterior_source="gate_full") is None

    def test_short_track_untouched(self, rule_on):
        out = _call(_pipe(), classification={"num_points": 5,
                                             "path_straightness": 0.98,
                                             "net_heading_change": 1.0})
        assert out is None

    def test_target_in_bank_turn_pairs_refused(self, rule_on):
        turn = {"origin_leg_id": 22, "destination_leg_id": 23,
                "movement_label": "right", "polyline": [[0, 0], [1, 1]],
                "supporting_count": 50}
        p = _pipe(paths=[turn])       # 22->23 is a bank TURN pair here
        out = _call(p)
        assert out == "drop"          # reroute refused, event dropped

    def test_flag_off_inert(self, monkeypatch):
        import backend.config as _cfg
        monkeypatch.setattr(_cfg, "STRAIGHT_FRAGMENT_RULE", False)   # default ON since 2026-09-10
        assert _call(_pipe()) is None
