"""ON-SCREEN ONLY (config.ON_SCREEN_ONLY, 2026-09-30): a vehicle's movement
may come only from what the video shows for that vehicle, never from how
common a movement is among other vehicles (operator rulings 2026-09-29/30)."""
import backend.config as cfg
from backend.services import partial_evidence as pe
from backend.services.pipeline import ProcessingPipeline


def _cand(leg, support, cost):
    return {"path": {"origin_leg_id": leg, "destination_leg_id": leg,
                     "supporting_count": support}, "cost": cost}


def test_default_off():
    assert cfg.ON_SCREEN_ONLY is False


def test_posterior_ignores_other_vehicles_counts(monkeypatch):
    # leg 1 fits the vehicle's own path better; leg 2 is far more common
    cands = [_cand(1, 5, 2.0), _cand(2, 500, 6.0)]
    marg_off, _ = pe.origin_posterior(cands)
    assert max(marg_off, key=marg_off.get) == 2           # legacy: popularity wins
    monkeypatch.setattr(cfg, "ON_SCREEN_ONLY", True)
    marg_on, _ = pe.origin_posterior(cands)
    assert max(marg_on, key=marg_on.get) == 1             # own shape wins


def test_popularity_only_rescue_is_removed(monkeypatch):
    paths = [{"destination_leg_id": 2, "supporting_count": 100},
             {"destination_leg_id": 3, "supporting_count": 5}]
    assert pe.supports_posterior(paths)[0]                # legacy guesses
    monkeypatch.setattr(cfg, "ON_SCREEN_ONLY", True)
    assert pe.supports_posterior(paths) == ({}, {})


def test_cell_label_is_shared_label_or_geometry(monkeypatch):
    p = ProcessingPipeline.__new__(ProcessingPipeline)
    agree = [{"movement_label": "left", "supporting_count": 3},
              {"movement_label": "left", "supporting_count": 90}]
    split = [{"movement_label": "left", "supporting_count": 3},
             {"movement_label": "u_turn", "supporting_count": 90}]
    assert p._cell_movement_label(split) == "u_turn"      # legacy: most supported
    monkeypatch.setattr(cfg, "ON_SCREEN_ONLY", True)
    assert p._cell_movement_label(agree) == "left"
    assert p._cell_movement_label(split) is None          # caller uses leg geometry
    assert p._cell_movement_label([]) is None
