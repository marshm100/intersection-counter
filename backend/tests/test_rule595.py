"""The customer standard's rule shape (plan_595_standard_2026-07-28)."""
from datetime import time as dtime

from backend.services.rule595 import (
    compliance, rule_ok, score_cells, tolerance)


class TestRuleShape:
    def test_small_cell_absolute_grace(self):
        assert rule_ok(105, 100)            # exactly +5 at the boundary
        assert not rule_ok(106, 100)
        assert rule_ok(5, 0)                # phantom inside the grace
        assert not rule_ok(6, 0)
        assert rule_ok(3, 8)                # -62% relative, PASSES (small)

    def test_large_cell_five_percent(self):
        assert tolerance(101) == 101 * 0.05
        assert rule_ok(106, 101)            # 4.95% ok
        assert not rule_ok(107, 101)
        assert rule_ok(380, 400) and not rule_ok(379, 400)   # 5% of 400 = 20

    def test_window_scaling_small_branch(self):
        # 30-min window (2 bins): per-bin ref 60 <= 100 -> tol 10
        assert tolerance(120, bins_equiv=2) == 10
        assert rule_ok(130, 120, bins_equiv=2)
        assert not rule_ok(131, 120, bins_equiv=2)
        # per-bin ref 125 > 100 -> 5% relative, scale-free
        assert tolerance(250, bins_equiv=2) == 12.5

    def test_score_cells_and_compliance(self):
        minutes = [dtime(7, m) for m in range(30)]
        ours = {dtime(7, 0): {("N", "through"): 90},
                dtime(7, 20): {("N", "through"): 120, ("S", "left"): 7}}
        ref = {dtime(7, 0): {("N", "through"): 96},
               dtime(7, 20): {("N", "through"): 110}}
        rows = score_cells(ours, ref, minutes)
        by = {(r["bin"], r["cell"]): r for r in rows}
        assert by[("07:00", "N through")]["ok"] is False   # 90 vs 96, small, |6|>5
        assert by[("07:15", "N through")]["ok"] is False   # 120 vs 110
        assert by[("07:15", "S left")]["ok"] is False      # phantom 7 > 5
        c = compliance(rows)
        assert c["cells_scored"] == 3 and c["compliant"] == 0
        assert c["worst"][0]["cell"] == "N through"        # biggest |delta| first
