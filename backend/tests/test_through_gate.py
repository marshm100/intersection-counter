"""Unit tests for the bank-gated through filter (FM51 audit #4).

A 'through' event running between a pair the bank POSITIVELY labels a TURN is a
mis-classification (validated on FM51: S->E is a bank right, and its 33 short
"through" fragments duplicate already-counted main-road vehicles). The rule keys
off the positive turn signal so real throughs whose bank path is channel-drawn /
support-0 are never touched (a 4-way rejects nothing).
"""
from backend.services.through_gate import bank_turn_pairs, is_invalid_through


def _p(o, d, mv, sup):
    return {"origin_leg_id": o, "destination_leg_id": d, "movement_label": mv,
            "supporting_count": sup}


def test_bank_turn_pairs_only_supported_turns():
    paths = [
        _p(1, 2, "through", 32),   # a real through-pair -> NOT a turn-pair
        _p(3, 2, "right", 7),      # a turn -> included
        _p(2, 3, "left", 15),      # a turn -> included
        _p(3, 4, "through", 0),    # phantom through -> not a turn anyway
        _p(1, 4, "right", 0),      # phantom 0-support turn -> EXCLUDED (below min_support)
    ]
    assert bank_turn_pairs(paths, min_support=1) == {(3, 2), (2, 3)}


def test_is_invalid_through_only_for_through_on_a_turn_pair():
    turns = {(3, 2)}
    assert is_invalid_through("through", 3, 2, turns) is True    # through on a bank right
    assert is_invalid_through("right", 3, 2, turns) is False     # a right IS fine
    assert is_invalid_through("through", 1, 2, turns) is False   # through on a non-turn pair (real)
    assert is_invalid_through("through", None, 2, turns) is False
    assert is_invalid_through("left", 3, 2, turns) is False      # only 'through' is gated


def test_four_way_rejects_nothing():
    # A 4-way whose bank has all-through pairs -> no turn-pairs -> no through is invalid.
    paths = [_p(1, 2, "through", 40), _p(2, 1, "through", 38),
             _p(3, 4, "through", 35), _p(4, 3, "through", 33)]
    turns = bank_turn_pairs(paths)
    assert turns == set()
    assert is_invalid_through("through", 1, 2, turns) is False
