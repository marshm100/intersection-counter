"""GATE-AG2 — the pure reattribution rule (plan_gate_ag2_2026-08-13).
The recall-mode rule (adjudicate_counts) is untouched; its own tests
stand. These pin the new pure function's guards one by one."""
from backend.services.apply_gate import adjudicate_reattribution_counts

CENSUS = {(1, 2): 100.0, (1, 3): 50.0, (2, 3): 30.0}
CLEAN = {"ids_mismatch": False, "moved": 10, "violations": 0,
         "fulls_moved": 0, "unclassifiable_moved": 0}


def _counts(over=None):
    inc = {(1, 2): 100, (1, 3): 50, (2, 3): 30}
    cand = dict(inc)
    cand.update(over or {})
    return inc, cand


class TestReattrGuards:
    def test_clean_pass(self):
        # gains spread over two cells (concentration 0.5 < 0.90)
        inc, cand = _counts({(1, 2): 98, (1, 3): 51, (2, 3): 31})
        d, r, m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.05, CLEAN)
        assert d == "apply" and r == ["gate_pass_reattr"]
        assert m["moved_cell_mass"] == 2 and m["cand_total"] == m["inc_total"]

    def test_mass_change_added(self):
        inc, cand = _counts({(1, 2): 101})
        d, r, _m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.05, CLEAN)
        assert d == "stand_down" and "mass_change" in r

    def test_mass_change_ids(self):
        inc, cand = _counts()
        integ = dict(CLEAN, ids_mismatch=True)
        d, r, _m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.05, integ)
        assert d == "stand_down" and "mass_change" in r

    def test_endpoint_integrity(self):
        inc, cand = _counts({(1, 2): 98, (1, 3): 52})
        integ = dict(CLEAN, violations=1)
        d, r, _m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.05, integ)
        assert d == "stand_down" and "endpoint_integrity" in r

    def test_excessive_movement(self):
        # move 3.3% of mass — over the 0.025 frozen cap
        inc, cand = _counts({(1, 2): 94, (1, 3): 56})
        d, r, _m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.05, CLEAN)
        assert d == "stand_down" and "excessive_movement" in r

    def test_concentrated_movement(self):
        # all moved mass lands in ONE cell (concentration 1.0 > 0.90) but
        # sourced from two cells so no single loss mirrors the gain
        inc = {(1, 2): 100, (1, 3): 50, (2, 3): 30}
        cand = {(1, 2): 98, (1, 3): 48, (2, 3): 34}
        d, r, _m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.05, CLEAN)
        assert d == "stand_down" and "concentrated_movement" in r

    def test_saturated_geometry(self):
        inc, cand = _counts({(1, 2): 98, (1, 3): 52})
        d, r, _m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.30, CLEAN)
        assert d == "stand_down" and "saturated_geometry" in r

    def test_no_movement_is_a_clean_pass(self):
        inc, cand = _counts()
        integ = dict(CLEAN, moved=0)
        d, _r, m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.05, integ)
        assert d == "apply" and m["concentration"] == 0.0
