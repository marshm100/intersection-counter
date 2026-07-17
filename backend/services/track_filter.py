"""Track-quality gate (Phase 1.1 — docs/implementation_plan_architecture_2026-06-11.md).

Companion to a LOOSENED tracker birth threshold. Strict birth gates
(activation/new_track_thresh ~0.25-0.3) exist to keep low-confidence clutter
from becoming tracks in LIVE streams. On recorded video we can afford to birth
from the low-confidence band — recovering fast/blurred vehicles whose
detections never clear 0.25 (Phase 0: structurally uncountable today, e.g.
cam1 07:10:05 crossing 616 px at conf_max 0.113) — and judge track QUALITY at
finalize time instead, with the whole track in hand.

The gate is deliberately asymmetric: a track whose mean detection confidence
is >= PROTECTED_MEAN_CONF passes untouched, so [loose birth + this filter]
admits a SUPERSET of the strict pipeline's events. Only the newly-admitted
low-confidence births must earn their event by moving like a vehicle: enough
points and real net displacement. Clutter (foliage, shadows, parked-car
flicker) births repeatedly but does not TRAVEL.

Enabled per camera via calibration_params["track_quality_filter"] (truthy) so
experiments can A/B it per retrack without touching config.
"""
from __future__ import annotations

import math

# Tracks at/above this mean confidence are what the strict-birth pipeline
# already produced — never filtered (keeps the A/B a pure superset).
PROTECTED_MEAN_CONF = 0.25
# A low-confidence birth must persist at least this many trajectory points...
TQ_MIN_POINTS = 3
# ...and travel at least this far (start->end straight-line px). Phase 0 fast
# misses travel 100-620 px; clutter flicker travels ~0.
TQ_MIN_NET_DISPLACEMENT_PX = 80.0


def track_quality(trajectory: list, confidences: list[float]) -> tuple[bool, str]:
    """(passes, reason) for a finalized track under loose-birth tracking.

    trajectory: list of (x, y) centers. confidences: per-point detection confs.
    """
    if not confidences or not trajectory:
        return False, "empty"
    mean_conf = sum(confidences) / len(confidences)
    if mean_conf >= PROTECTED_MEAN_CONF:
        return True, "protected_high_conf"
    if len(trajectory) < TQ_MIN_POINTS:
        return False, "low_conf_too_few_points"
    net = math.hypot(
        float(trajectory[-1][0]) - float(trajectory[0][0]),
        float(trajectory[-1][1]) - float(trajectory[0][1]),
    )
    if net < TQ_MIN_NET_DISPLACEMENT_PX:
        return False, "low_conf_low_displacement"
    return True, "low_conf_moving"
