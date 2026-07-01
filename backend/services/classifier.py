"""Vehicle classification from YOLO detection data.

Maps YOLO COCO classes to simplified vehicle categories and FHWA classes.
Uses bounding-box aspect ratio and area for truck sub-classification.
"""

# Simplified categories used in the app
SIMPLIFIED_CLASSES = [
    "motorcycle", "car", "pickup_van_suv", "bus",
    "single_unit_truck", "multi_unit_truck",
]

# YOLO COCO class → simplified category
YOLO_TO_SIMPLIFIED: dict[int, str | None] = {
    0: None,           # person
    1: None,           # bicycle
    2: "car",          # car
    3: "motorcycle",   # motorcycle
    5: "bus",          # bus
    7: "truck",        # truck → sub-classified by size
}

# Simplified category → best-guess FHWA class
SIMPLIFIED_TO_FHWA: dict[str, int] = {
    "motorcycle": 1,
    "car": 2,
    "pickup_van_suv": 3,
    "bus": 4,
    "single_unit_truck": 5,
    "multi_unit_truck": 9,
}

# FHWA class → human-readable name
FHWA_CLASS_NAMES: dict[int, str] = {
    1: "Motorcycles",
    2: "Passenger Cars",
    3: "Other Two-Axle, Four-Tire Single-Unit Vehicles",
    4: "Buses",
    5: "Two-Axle, Six-Tire Single-Unit Trucks",
    6: "Three-Axle Single-Unit Trucks",
    7: "Four or More Axle Single-Unit Trucks",
    8: "Four or Fewer Axle Single-Trailer Trucks",
    9: "Five-Axle Single-Trailer Trucks",
    10: "Six or More Axle Single-Trailer Trucks",
    11: "Five or Fewer Axle Multi-Trailer Trucks",
    12: "Six-Axle Multi-Trailer Trucks",
    13: "Seven or More Axle Multi-Trailer Trucks",
}


# FHWA class → Miovision report class group. Miovision's deliverable buckets
# vehicles as Lights / Mediums / Articulated Trucks:
#   Lights            = FHWA 1–3  (motorcycles, cars, other 2-axle 4-tire)
#   Mediums           = FHWA 4–7  (buses + single-unit trucks)
#   Articulated Trucks = FHWA 8–13 (single- + multi-trailer trucks)
# NOTE: the current classifier only emits FHWA 9 within the Articulated band (the
# bbox multi-unit heuristic under-calls articulated) — that classification gap is
# §3-D, tracked separately; this mapping is exact and works once §3-D lands.
CLASS_GROUP_ORDER = ["Lights", "Mediums", "Articulated Trucks"]


def fhwa_to_class_group(fhwa_class: int | None) -> str:
    """Map an FHWA class (1–13) to Miovision's Light/Medium/Articulated bucket.
    None (unclassified) falls into Lights (the dominant, lowest-impact bucket)."""
    if fhwa_class is None or fhwa_class <= 3:
        return "Lights"
    if fhwa_class <= 7:
        return "Mediums"
    return "Articulated Trucks"


def classify_vehicle(
    yolo_class_id: int,
    bbox_width: float,
    bbox_height: float,
    bbox_area: float,
    confidence: float,
) -> dict:
    """Classify a detected vehicle into simplified category + FHWA class.

    Uses YOLO class mapping with bbox-based truck sub-classification.
    Returns None fields for non-vehicle detections (person/bicycle).
    """
    base = YOLO_TO_SIMPLIFIED.get(yolo_class_id)

    # Not a vehicle (person, bicycle, or unknown class)
    if base is None:
        return {
            "simplified_class": None,
            "fhwa_class": None,
            "confidence": confidence,
        }

    simplified = base
    aspect_ratio = bbox_width / bbox_height if bbox_height > 0 else 0.0

    # Truck sub-classification by bbox geometry
    if base == "truck":
        if aspect_ratio > 2.0 and bbox_area > 5000:
            simplified = "multi_unit_truck"
        elif aspect_ratio > 1.5:
            simplified = "single_unit_truck"
        else:
            simplified = "pickup_van_suv"

    # Large car reclassified as pickup/van/SUV
    elif base == "car" and bbox_area > 4000:
        simplified = "pickup_van_suv"

    return {
        "simplified_class": simplified,
        "fhwa_class": SIMPLIFIED_TO_FHWA[simplified],
        "confidence": confidence,
    }


def get_all_simplified_classes() -> list[str]:
    """Return the list of all simplified vehicle classes for UI dropdowns."""
    return list(SIMPLIFIED_CLASSES)


def get_fhwa_class_name(fhwa_class: int) -> str:
    """Return human-readable FHWA class name."""
    return FHWA_CLASS_NAMES.get(fhwa_class, "Unknown")
