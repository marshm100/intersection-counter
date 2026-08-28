"""Study-health battery (backend/services/study_health.py) — the
pure verdict layer + signal-shape pins. The corridor integration is
smoke-tested where the corridor project exists (the entry_gates n500
precedent)."""
from backend.services.study_health import classify_signals

CORRIDOR = Path("data/projects/97a7849a/project.db")


class TestClassifySignals:
    def test_green_when_clean(self):
        v = classify_signals({
            "activation": {"activated": True, "coverage": 0.5,
                           "threshold": 0.45},
            "guessed_share": 0.1, "twin_rate": 0.01,
            "entry_coverage": 0.7, "echo_share": 0.01,
            "diverging_cells": []})
        assert v["verdict"] == "green" and v["reasons"] == []

    def test_activation_off_is_red(self):
        v = classify_signals({"activation": {"activated": False,
                                             "coverage": 0.3,
                                             "threshold": 0.45}})
        assert v["verdict"] == "red"
        assert "evidence channel OFF" in v["reasons"][0]

    def test_guessed_share_bands(self):
        assert classify_signals({"guessed_share": 0.4})["verdict"] == "amber"
        assert classify_signals({"guessed_share": 0.6})["verdict"] == "red"

    def test_divergence_red(self):
        v = classify_signals({"diverging_cells": [
            {"cell": "NB_left", "ratio": 2.5, "counted": 300,
             "expected": 120.0}]})
        assert v["verdict"] == "red"
        assert "NB_left" in v["reasons"][0]

    def test_amber_signals(self):
        assert classify_signals({"twin_rate": 0.05})["verdict"] == "amber"
        assert classify_signals({"entry_coverage": 0.45})["verdict"] == "amber"
        assert classify_signals({"entry_coverage": 0.3})["verdict"] == "red"
        assert classify_signals({"echo_share": 0.05})["verdict"] == "amber"

    def test_missing_signals_are_quiet(self):
        v = classify_signals({})
        assert v["verdict"] == "green"


# The corridor integration check lives in
# scripts/calibrate_study_health.py — conftest redirects PROJECTS_DIR
# to a temp dir (the test-isolation law), so live-data smoke belongs
# to scripts, not pytest.
