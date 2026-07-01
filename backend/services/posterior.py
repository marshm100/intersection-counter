"""Destination-posterior margin — the single source of truth for the
"movement near-tie" signal used by the review flag queue (MASTER_PLAN §3-B,
Feeder 1) and precomputed at event-write time so the feeder can filter on it
in SQL instead of parsing every event's posterior in Python.

margin = P(top) - P(runner-up); 1.0 for a peaked / single-candidate / absent
posterior (i.e. NOT ambiguous). A small margin means the destination movement
was a near-tie and the operator should confirm it.
"""
from __future__ import annotations

import json


def posterior_margin(posterior: dict | None) -> float:
    """Top-1 minus top-2 probability from a {leg_id: prob} map. 1.0 when there
    is 0 or 1 candidate (nothing to be ambiguous about)."""
    if not posterior:
        return 1.0
    probs = sorted(posterior.values(), reverse=True)
    if len(probs) < 2:
        return 1.0
    return float(probs[0]) - float(probs[1])


def margin_from_json(posterior_json: str | None) -> float:
    """posterior_margin() over the stored {str(leg_id): prob} JSON string.
    A missing / unparseable posterior is treated as peaked (margin 1.0),
    matching flag_feeders._posterior_top2."""
    if not posterior_json:
        return 1.0
    try:
        p = json.loads(posterior_json)
    except (TypeError, ValueError):
        return 1.0
    return posterior_margin(p)
