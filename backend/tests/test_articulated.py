"""Unit tests for the view-invariant articulated (semi) size test (§3-D).

The size logic is the crux; the cache/DB linking in services/articulated.py is
validated on FM51 (~82 articulated vs Miovision 102 at K=2.0). These lock the
pure functions in classifier.py.
"""
from backend.services.classifier import (
    build_car_length_baseline, is_articulated, local_car_length,
)


def test_baseline_is_per_band_median_and_drops_sparse_bands():
    # band width 40px. Band 0 (y 0-40): 20 cars len 30. Band 1 (y 40-80): 5 cars
    # (below min_cars -> untrustworthy median -> dropped).
    cars = [(30.0, 10.0)] * 20 + [(50.0, 50.0)] * 5
    base = build_car_length_baseline(cars, band_px=40, min_cars=20)
    assert base == {0: 30.0}


def test_local_car_length_searches_outward_then_gives_up():
    base = {5: 40.0}
    assert local_car_length(210.0, base, 40) == 40.0   # y210 -> band 5 exact
    assert local_car_length(170.0, base, 40) == 40.0   # y170 -> band 4, +1 finds band 5
    assert local_car_length(1000.0, base, 40) is None   # nothing within a few bands


def test_is_articulated_thresholds_on_local_car_ratio():
    base = {0: 30.0}
    assert is_articulated(70.0, 10.0, base, ratio=2.0, band_px=40) is True    # 2.33x -> semi
    assert is_articulated(50.0, 10.0, base, ratio=2.0, band_px=40) is False   # 1.67x -> single-unit
    assert is_articulated(60.0, 10.0, base, ratio=2.0, band_px=40) is False   # exactly 2.0x -> not (>)


def test_is_articulated_undecidable_without_local_baseline():
    # No car baseline near this row -> None (caller leaves it single-unit, never guesses).
    assert is_articulated(999.0, 1000.0, {0: 30.0}, ratio=2.0, band_px=40) is None
