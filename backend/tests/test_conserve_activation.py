"""Block D1 — the posterior EXTRAS under the activation precondition.

docs/plan_v2_conserve_activation_2026-08-11.md

census_expecteds + conserve_pass were retired as blind five-camera defaults
per the two-iteration budget for ONE stated reason: not blind-deployable
where evidence coverage is low. The activation precondition decides exactly
that and shipped 2026-07-27 — but it governs the REPLAY only, so the extras
kept their own always-off flag and conserve_pass has never run.

These pin the gate, and in particular pin that the flag is INERT when off
(G-D1a) — a default-OFF flag that is not inert is not a flag.

TRAP these tests exist to encode: two_pass reads ORIGIN_POSTERIOR_ENABLED as
a MODULE-GLOBAL imported at two_pass.py:43, not as config.X. Patching
backend.config does nothing; you must patch backend.services.two_pass. The
same is NOT true of CONSERVE_ON_ACTIVATION, which is read through the config
module at call time — so the two knobs are patched differently on purpose.
"""
from __future__ import annotations

import backend.config as config
from backend.services import two_pass as TP

ACTIVE = {"coverage": 0.564, "threshold": 0.45, "activated": True}
STOOD_DOWN = {"coverage": 0.431, "threshold": 0.45, "activated": False}


class TestPosteriorExtrasGate:
    """two_pass.posterior_extras_enabled — the whole D1 decision."""

    def test_off_by_default_even_when_the_camera_activates(self, monkeypatch):
        # the shipped posture: neither flag set. Activation says ACTIVATE, and
        # the extras must STILL stand down, because that is today's behaviour
        # and D1 must be inert until switched on.
        monkeypatch.setattr(TP, "ORIGIN_POSTERIOR_ENABLED", False)
        monkeypatch.setattr(config, "CONSERVE_ON_ACTIVATION", False)
        assert TP.posterior_extras_enabled(ACTIVE) is False

    def test_posterior_flag_forces_extras_regardless_of_activation(self, monkeypatch):
        # the legacy escape hatch keeps working: ORIGIN_POSTERIOR_ENABLED wins
        # outright, so an operator who sets it gets the old all-cameras
        # behaviour whatever the coverage says.
        monkeypatch.setattr(TP, "ORIGIN_POSTERIOR_ENABLED", True)
        monkeypatch.setattr(config, "CONSERVE_ON_ACTIVATION", False)
        assert TP.posterior_extras_enabled(STOOD_DOWN) is True
        assert TP.posterior_extras_enabled(None) is True

    def test_extras_run_when_activation_clears_the_bar(self, monkeypatch):
        monkeypatch.setattr(TP, "ORIGIN_POSTERIOR_ENABLED", False)
        monkeypatch.setattr(config, "CONSERVE_ON_ACTIVATION", True)
        assert TP.posterior_extras_enabled(ACTIVE) is True

    def test_extras_stand_down_when_coverage_is_below_the_bar(self, monkeypatch):
        # cam3's real number: 0.431 against a 0.45 bar. The whole point of the
        # precondition is that this camera does NOT get the extras.
        monkeypatch.setattr(TP, "ORIGIN_POSTERIOR_ENABLED", False)
        monkeypatch.setattr(config, "CONSERVE_ON_ACTIVATION", True)
        assert TP.posterior_extras_enabled(STOOD_DOWN) is False

    def test_extras_stand_down_when_there_is_no_activation_decision(self, monkeypatch):
        # activation is None when EVIDENCE_ACTIVATION_ENABLED is off. There is
        # then no decision to follow, so the extras must not guess.
        monkeypatch.setattr(TP, "ORIGIN_POSTERIOR_ENABLED", False)
        monkeypatch.setattr(config, "CONSERVE_ON_ACTIVATION", True)
        assert TP.posterior_extras_enabled(None) is False

    def test_a_malformed_activation_block_stands_down(self, monkeypatch):
        # fail closed on a dict that is missing the key rather than raising
        # mid-pass-2.
        monkeypatch.setattr(TP, "ORIGIN_POSTERIOR_ENABLED", False)
        monkeypatch.setattr(config, "CONSERVE_ON_ACTIVATION", True)
        assert TP.posterior_extras_enabled({}) is False
        assert TP.posterior_extras_enabled({"coverage": 0.9}) is False


class TestConserveRejectionScope:
    """conserve_replay_additions only ever rejects ADDITIVE events.

    This is the trap that makes D1's measurement design non-obvious: on an
    all-direct replay the conservation pass is a strict no-op no matter what
    the flag says, so the block can only be measured where the evidence pair
    is ON — which is exactly what the activation gate delivers.
    """

    def test_additive_sources_are_the_only_rejectable_ones(self):
        assert TP._ADDITIVE == ("branch1", "rescue_full", "rescue_supports")

    def test_rank_prefers_rescue_full_then_branch1_then_supports(self):
        # the tie-break order decides WHICH duplicate survives on an
        # all-additive chain; pin it so a reorder is a deliberate act.
        assert TP._ADDITIVE_RANK["rescue_full"] < TP._ADDITIVE_RANK["branch1"]
        assert TP._ADDITIVE_RANK["branch1"] < TP._ADDITIVE_RANK["rescue_supports"]

    def test_every_ranked_source_is_additive(self):
        assert set(TP._ADDITIVE_RANK) <= set(TP._ADDITIVE)
