"""Tests for vehicle classification service."""

from backend.services.classifier import (
    classify_vehicle,
    get_all_simplified_classes,
    get_fhwa_class_name,
)


# ---------------------------------------------------------------------------
# TestClassifyVehicle
# ---------------------------------------------------------------------------

class TestClassifyVehicle:
    def test_car(self):
        r = classify_vehicle(2, 50, 30, 1500, 0.85)
        assert r["simplified_class"] == "car"
        assert r["fhwa_class"] == 2

    def test_motorcycle(self):
        r = classify_vehicle(3, 20, 15, 300, 0.9)
        assert r["simplified_class"] == "motorcycle"
        assert r["fhwa_class"] == 1

    def test_bus(self):
        r = classify_vehicle(5, 80, 40, 3200, 0.7)
        assert r["simplified_class"] == "bus"
        assert r["fhwa_class"] == 4

    def test_large_truck_multi_unit(self):
        # aspect_ratio = 150/50 = 3.0, area = 7500 > 5000
        r = classify_vehicle(7, 150, 50, 7500, 0.8)
        assert r["simplified_class"] == "multi_unit_truck"
        assert r["fhwa_class"] == 9

    def test_medium_truck_single_unit(self):
        # aspect_ratio = 80/50 = 1.6 > 1.5
        r = classify_vehicle(7, 80, 50, 4000, 0.75)
        assert r["simplified_class"] == "single_unit_truck"
        assert r["fhwa_class"] == 5

    def test_small_truck_is_pickup(self):
        # aspect_ratio = 60/50 = 1.2 <= 1.5
        r = classify_vehicle(7, 60, 50, 3000, 0.7)
        assert r["simplified_class"] == "pickup_van_suv"
        assert r["fhwa_class"] == 3

    def test_large_car_is_suv(self):
        # car with area > 4000 → pickup_van_suv
        r = classify_vehicle(2, 100, 60, 6000, 0.8)
        assert r["simplified_class"] == "pickup_van_suv"
        assert r["fhwa_class"] == 3

    def test_person_returns_none(self):
        r = classify_vehicle(0, 30, 60, 1800, 0.9)
        assert r["simplified_class"] is None
        assert r["fhwa_class"] is None

    def test_native_articulated_direct(self):
        # id 8 = the fine-tuned head's native articulated class
        # (plan_articulated_native_2026-07-17) — FHWA 9 regardless of bbox
        # geometry, no aspect subclassification.
        r = classify_vehicle(8, 40, 35, 1400, 0.6)
        assert r["simplified_class"] == "multi_unit_truck"
        assert r["fhwa_class"] == 9


# ---------------------------------------------------------------------------
# TestHelperFunctions
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    def test_all_simplified_classes(self):
        classes = get_all_simplified_classes()
        assert isinstance(classes, list)
        assert len(classes) == 6

    def test_fhwa_class_names(self):
        assert get_fhwa_class_name(2) == "Passenger Cars"

    def test_fhwa_unknown(self):
        assert get_fhwa_class_name(99) == "Unknown"

    def test_confidence_passthrough(self):
        r = classify_vehicle(2, 50, 30, 1500, 0.85)
        assert r["confidence"] == 0.85
