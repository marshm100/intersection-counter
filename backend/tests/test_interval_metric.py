"""Locks the acceptance metric computation (scripts/interval_metric.py).

The AVG |err| <= 5%/interval number is THE acceptance bar, so its math is unit-
tested directly. Only the pure functions are exercised (no DB / openpyxl / XML);
the CLI loaders are covered by the triangulate_* scripts themselves.
"""
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import interval_metric as IM  # noqa: E402


class TestSummarizeBins:
    def test_avg_max_and_fail_verdict(self):
        # per-bin abs errors 0%, 10%, 10% -> mean 6.7% -> FAIL (>5%)
        s = IM.summarize_bins([("07:00", 100, 100), ("07:15", 110, 100), ("07:30", 90, 100)])
        assert s["n_bins"] == 3
        assert s["avg_abs_err_pct"] == 6.7
        assert s["max_abs_err_pct"] == 10.0
        assert s["worst_interval"] in ("07:15", "07:30")
        assert s["n_over_target"] == 2          # two bins exceed 5%
        assert s["verdict"] == "FAIL"

    def test_pass_verdict(self):
        s = IM.summarize_bins([("a", 102, 100), ("b", 98, 100)])   # 2%, 2%
        assert s["avg_abs_err_pct"] == 2.0 and s["verdict"] == "PASS"

    def test_ref_floor_gates_tiny_bins(self):
        # second bin's reference (5) is below the floor -> dropped, not a 900% blowup
        s = IM.summarize_bins([("a", 100, 100), ("b", 50, 5)], ref_floor=20)
        assert s["n_bins"] == 1 and s["avg_abs_err_pct"] == 0.0

    def test_no_qualifying_bins_is_na(self):
        s = IM.summarize_bins([("a", 1, 2)], ref_floor=20)
        assert s["verdict"] == "n/a" and s["avg_abs_err_pct"] is None


def _permin(per_min_cells):
    return {time(7, m): cell for m, cell in per_min_cells.items()}


class TestPerInterval:
    def test_bins_minutes_and_avg(self):
        ref = _permin({m: {("NB", "thru"): 10} for m in range(15)})    # 150/bin
        ours = _permin({m: {("NB", "thru"): 11} for m in range(15)})   # 165/bin -> 10%
        r = IM.per_interval(ours, ref)
        assert r["n_bins"] == 1 and r["avg_abs_err_pct"] == 10.0 and r["verdict"] == "FAIL"

    def test_min_minutes_gates_partial_bin(self):
        ref = _permin({m: {("NB", "thru"): 10} for m in range(5)})     # only 5 min < MIN_BIN_MINUTES
        ours = _permin({m: {("NB", "thru"): 10} for m in range(5)})
        assert IM.per_interval(ours, ref)["n_bins"] == 0

    def test_by_approach_localizes(self):
        ref = _permin({m: {("NB", "thru"): 10, ("SB", "thru"): 10} for m in range(15)})
        ours = _permin({m: {("NB", "thru"): 10, ("SB", "thru"): 12} for m in range(15)})
        r = IM.per_interval(ours, ref, by_approach=True)
        assert r["per_approach"]["NB"]["avg_abs_err_pct"] == 0.0
        assert r["per_approach"]["SB"]["avg_abs_err_pct"] == 20.0
        assert r["per_approach"]["SB"]["verdict"] == "FAIL"
