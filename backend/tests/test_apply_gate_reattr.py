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
        # move 6.7% of mass — over the 0.05 cap (re-frozen 2026-08-13 from
        # the two validated positives per the declared choice rule)
        inc, cand = _counts({(1, 2): 88, (1, 3): 56, (2, 3): 36})
        d, r, _m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.05, CLEAN)
        assert d == "stand_down" and "excessive_movement" in r

    def test_concentrated_movement(self):
        # all moved mass lands in ONE cell (concentration 1.0 > 0.90),
        # sourced from two cells, and the mass (80) is over the
        # CONC_MASS_MIN=40 qualifier — the flood shape stays blocked
        inc = {(1, 2): 1000, (1, 3): 500, (2, 3): 300}
        cand = {(1, 2): 960, (1, 3): 460, (2, 3): 380}
        d, r, _m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.05, CLEAN)
        assert d == "stand_down" and "concentrated_movement" in r

    def test_concentration_small_mass_waived(self):
        # the cam4 T-junction P3 shape: one-cell concentration at mass
        # 28 <= CONC_MASS_MIN=40 — the legitimate capped-composer shape
        inc = {(1, 2): 600, (1, 3): 200, (2, 3): 30}
        cand = {(1, 2): 572, (1, 3): 200, (2, 3): 58}
        d, r, m = adjudicate_reattribution_counts(
            inc, cand, CENSUS, 0.05, CLEAN)
        assert d == "apply" and r == ["gate_pass_reattr"]
        assert m["concentration"] == 1.0 and m["moved_cell_mass"] == 28

    def test_concentration_mass_qualifier_boundary(self):
        # exactly AT the qualifier (40) the guard is waived; one past
        # it (41) the guard binds — the > semantics, pinned
        inc = {(1, 2): 900, (1, 3): 100}
        d40, _r, m40 = adjudicate_reattribution_counts(
            inc, {(1, 2): 860, (1, 3): 140}, CENSUS, 0.05, CLEAN)
        assert d40 == "apply" and m40["moved_cell_mass"] == 40
        d41, r41, _m = adjudicate_reattribution_counts(
            inc, {(1, 2): 859, (1, 3): 141}, CENSUS, 0.05, CLEAN)
        assert d41 == "stand_down" and "concentrated_movement" in r41

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
